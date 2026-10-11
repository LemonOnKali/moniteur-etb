"""Boucle de surveillance : un cycle vérifie toutes les boutiques et fiches en parallèle,
compare à l'état précédent et envoie les alertes Discord au passage en stock."""

from __future__ import annotations

import json
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from . import etat as etat_mod
from .boutiques import Analyse, Boutique, analyser
from .collection import Collection
from .discord import BLEU, ORANGE, Discord, embed_offre, embed_rupture, resume_alertes
from .modeles import Offre, cle_url
from .pages import Produit, verifier
from .reglages import Reglages
from .texte import formater_prix


MAX_DECOUVERTES_PAR_CYCLE = 3  # hors premier cycle, où chaque boutique est découverte


def log(message: str) -> None:
    print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {message}", flush=True)


def maintenant() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------- #
# Chargement des fichiers de configuration
# --------------------------------------------------------------------------- #


def _lire_liste(chemin: str, cle: str) -> list[Any]:
    try:
        with open(chemin, encoding="utf-8") as f:
            brut = json.load(f)
    except FileNotFoundError:
        sys.exit(f"Fichier {chemin} introuvable.")
    except json.JSONDecodeError as err:
        sys.exit(f"{chemin} n'est pas un JSON valide : {err}")
    if isinstance(brut, dict) and cle in brut:
        brut = brut[cle]
    if not isinstance(brut, list):
        sys.exit(f"{chemin} doit contenir une liste.")
    return brut


def charger_produits(chemin: str) -> list[Produit]:
    if not chemin:
        return []
    produits: list[Produit] = []
    vues: set[str] = set()
    for index, element in enumerate(_lire_liste(chemin, "produits")):
        try:
            produit = Produit.depuis_dict(element, index)
        except ValueError as err:
            log(f"⚠️  Produit ignoré — {err}")
            continue
        if not produit.actif:
            continue
        if cle_url(produit.url) in vues:
            log(f"⚠️  Produit ignoré — URL en double : {produit.url}")
            continue
        vues.add(cle_url(produit.url))
        produits.append(produit)
    return produits


def charger_boutiques(chemin: str) -> list[Boutique]:
    if not chemin:
        return []
    boutiques: list[Boutique] = []
    vues: set[str] = set()
    for index, element in enumerate(_lire_liste(chemin, "boutiques")):
        try:
            boutique = Boutique.depuis_dict(element, index)
        except ValueError as err:
            log(f"⚠️  Boutique ignorée — {err}")
            continue
        if not boutique.actif:
            continue
        if boutique.url in vues:
            log(f"⚠️  Boutique ignorée — URL en double : {boutique.url}")
            continue
        vues.add(boutique.url)
        boutiques.append(boutique)
    return boutiques


# --------------------------------------------------------------------------- #
# Cycle
# --------------------------------------------------------------------------- #


@dataclass
class Bilan:
    offres: list[Offre] = field(default_factory=list)
    alertes: int = 0
    en_stock: int = 0
    rupture: int = 0
    erreurs: dict[str, str] = field(default_factory=dict)  # source (boutique ou fiche) → message
    requetes: int = 0
    decouvertes: int = 0
    duree: float = 0.0


class Surveillance:
    def __init__(
        self,
        reglages: Reglages,
        collection: Collection,
        produits: list[Produit],
        boutiques: list[Boutique],
        discord: Discord,
        etat: dict[str, dict[str, Any]],
    ):
        self.reglages = reglages
        self.collection = collection
        self.produits = produits
        self.boutiques = boutiques
        self.discord = discord
        self.etat = etat
        self.cycle_n = 0
        self._erreurs_vues: dict[str, str] = {}

    # -- Vérifications ------------------------------------------------------ #

    def offre_produit(self, produit: Produit) -> Offre:
        """Vérifie une fiche de produits.json et la classe dans la gamme."""
        r = verifier(produit)
        classement = self.collection.classer(produit.nom, exiger_marqueur=False)
        item = self.collection.item(produit.item) or (classement.item if classement else self.collection.item_defaut)
        return Offre(
            cle=cle_url(produit.url),
            boutique=produit.boutique,
            titre=produit.nom,
            url=produit.url,
            item=item,
            langue=classement.langue if classement else "?",
            dispo=r.dispo,
            prix=r.prix,
            prix_max=produit.prix_max if produit.prix_max is not None else item.prix_max,
            image=r.image,
            quantite=r.quantite,
            detail=r.detail,
            source=produit.type_detecte or r.source or produit.type,
            erreur=r.detail if r.dispo is None else "",
        )

    def verifier_tout(self, executeur: ThreadPoolExecutor, forcer_decouverte: bool = False) -> tuple[list[Offre], Bilan]:
        bilan = Bilan()
        intervalle_decouverte = self.reglages.decouverte_minutes * 60
        futurs: dict[Any, Boutique | Produit] = {}
        # Découvertes étalées : quelques boutiques par cycle (les plus anciennes d'abord)
        # plutôt que toutes en même temps toutes les 15 min.
        dues = sorted((b for b in self.boutiques if b.decouverte_due(intervalle_decouverte)),
                      key=lambda b: b.derniere_decouverte or 0.0)
        a_decouvrir = {id(b) for b in (dues if forcer_decouverte else dues[:MAX_DECOUVERTES_PAR_CYCLE])}
        for b in self.boutiques:
            decouvrir = b.derniere_decouverte is None or id(b) in a_decouvrir
            if not decouvrir and not b.verification_due():
                continue
            futurs[executeur.submit(analyser, b, self.collection, self.reglages.langues, decouvrir)] = b
        for p in self.produits:
            futurs[executeur.submit(self.offre_produit, p)] = p

        offres: dict[str, Offre] = {}
        for futur in as_completed(futurs):
            origine = futurs[futur]
            if isinstance(origine, Boutique):
                analyse: Analyse = futur.result()
                bilan.requetes += analyse.requetes
                if analyse.decouverte:
                    bilan.decouvertes += 1
                    self._log_decouverte(origine, analyse)
                if analyse.erreurs:
                    bilan.erreurs[origine.nom] = " | ".join(analyse.erreurs)
                for o in analyse.offres:
                    offres.setdefault(o.cle, o)
            else:
                bilan.requetes += 1
                o = futur.result()
                if o.dispo is None:
                    bilan.erreurs[f"{o.boutique} · {o.titre}"] = o.erreur
                # Une fiche listée à la main prime sur la même fiche trouvée dans le catalogue.
                if o.dispo is not None or o.cle not in offres:
                    offres[o.cle] = o
        return list(offres.values()), bilan

    def _log_decouverte(self, b: Boutique, analyse: Analyse) -> None:
        compte = Counter(o.item.nom for o in analyse.offres)
        resume = ", ".join(f"{n}× {nom}" if n > 1 else nom for nom, n in compte.most_common()) or "aucune fiche 30 ans"
        categories = f" · catégories {', '.join(b.categories_trouvees)}" if b.categories_trouvees else ""
        log(f"🔎 {b.nom} [{b.detectee or '?'}] : {resume} ({analyse.requetes} requête(s){categories})")

    # -- Décisions ---------------------------------------------------------- #

    def cycle(self, executeur: ThreadPoolExecutor, forcer_decouverte: bool = False) -> Bilan:
        self.cycle_n += 1
        debut = time.monotonic()
        offres, bilan = self.verifier_tout(executeur, forcer_decouverte)
        bilan.offres = offres
        horodatage = maintenant()
        premier = self.cycle_n == 1
        etat_vierge = not self.etat
        alertes: list[tuple[Offre, bool]] = []
        ruptures: list[Offre] = []

        for o in sorted(offres, key=lambda o: (o.item.nom, o.boutique)):
            precedent = self.etat.get(o.cle, {})
            if o.dispo is None:
                self.etat.setdefault(o.cle, {}).update({"derniere_erreur": f"{horodatage} {o.erreur}", "maj": horodatage})
                continue
            if o.prix_max is None:
                o.prix_max = self.reglages.prix_max
            dispo = bool(o.dispo) and not o.trop_chere
            avant = precedent.get("dispo")
            change = avant is not dispo or precedent.get("prix") != o.prix
            if dispo:
                bilan.en_stock += 1
            else:
                bilan.rupture += 1
            if premier or change:
                self._log_offre(o, dispo)

            derniere_alerte = precedent.get("alerte")
            if dispo and avant is not True:
                if self._alerte_recente(derniere_alerte):
                    log(f"🔕 {o.boutique} · {o.item.nom} : déjà signalé il y a moins de {self.reglages.anti_spam_minutes:.0f} min")
                else:
                    alertes.append((o, o.cle not in self.etat and not etat_vierge))
            elif not dispo and avant is True and self.reglages.alerte_rupture:
                ruptures.append(o)

            self.etat[o.cle] = {
                "nom": o.titre,
                "boutique": o.boutique,
                "item": o.item.id,
                "url": o.url,
                "dispo": dispo,
                "prix": o.prix,
                "alerte": derniere_alerte,
                "source": o.source,
                "vu": horodatage,
                "maj": horodatage,
            }

        self._envoyer_alertes(alertes, horodatage)
        if ruptures:
            self.discord.embeds("", [embed_rupture(o) for o in ruptures])
        self._log_erreurs(bilan.erreurs)
        bilan.alertes = len(alertes)
        bilan.duree = time.monotonic() - debut
        return bilan

    def _alerte_recente(self, derniere: str | None) -> bool:
        if not derniere:
            return False
        try:
            ecart = datetime.now(timezone.utc) - datetime.fromisoformat(derniere)
        except ValueError:
            return False
        return ecart.total_seconds() < self.reglages.anti_spam_minutes * 60

    def _envoyer_alertes(self, alertes: list[tuple[Offre, bool]], horodatage: str) -> None:
        if not alertes:
            return
        offres = [o for o, _ in alertes]
        resultats = self.discord.embeds(
            resume_alertes(offres), [embed_offre(o, nouvelle) for o, nouvelle in alertes], mention=True
        )
        for o, ok in zip(offres, resultats):
            if ok:
                self.etat[o.cle]["alerte"] = horodatage
                log(f"🔔 Alerte Discord envoyée : {o.item.nom} chez {o.boutique}")
            elif self.discord.webhook:
                # Échec d'envoi : on ne mémorise pas le passage en stock, le cycle suivant réessaiera.
                self.etat[o.cle]["dispo"] = None

    def _log_offre(self, o: Offre, dispo: bool) -> None:
        prix = formater_prix(o.prix)
        texte = f"{o.boutique} · {o.item.nom}" + (f"  {prix}" if prix else "")
        if o.trop_chere:
            log(f"💸 trop cher   {texte} > {formater_prix(o.prix_max)} — {o.titre}")
        elif dispo:
            log(f"✅ EN STOCK    {texte} — {o.titre}" + (f" [{o.detail}]" if o.detail else ""))
        else:
            log(f"⛔ rupture     {texte} — {o.titre}")

    def _log_erreurs(self, erreurs: dict[str, str]) -> None:
        """N'affiche une erreur que si elle est nouvelle ou a changé (journaux lisibles)."""
        for source, message in erreurs.items():
            if self._erreurs_vues.get(source) != message:
                log(f"⚠️  {source} : {message}")
        for source in set(self._erreurs_vues) - set(erreurs):
            log(f"👌 {source} : de nouveau joignable")
        self._erreurs_vues = dict(erreurs)

    # -- Résumé ------------------------------------------------------------- #

    def resume_discord(self, bilan: Bilan, duree_min: float, intervalle_s: float) -> None:
        """Message de lancement (exécution manuelle) : ce qui est couvert, ce qui coince."""
        par_item: dict[str, list[Offre]] = {}
        for o in bilan.offres:
            if o.dispo is not None:
                par_item.setdefault(f"{o.item.emoji} {o.item.nom}", []).append(o)
        lignes = []
        for nom, liste in sorted(par_item.items(), key=lambda kv: -len(kv[1])):
            dispo = sum(1 for o in liste if self.etat.get(o.cle, {}).get("dispo"))
            boutiques = len({o.boutique for o in liste})
            lignes.append(f"{nom} — {boutiques} boutique(s)" + (f" · **{dispo} en stock**" if dispo else ""))
        description = "\n".join(lignes) or "Aucune fiche 30 ans trouvée pour l'instant."
        embeds: list[dict[str, Any]] = [{
            "title": f"✅ Moniteur lancé — {self.collection.nom}",
            "description": description[:4000],
            "color": BLEU,
            "fields": [
                {"name": "Boutiques", "value": str(len(self.boutiques)), "inline": True},
                {"name": "Fiches suivies", "value": str(len(bilan.offres)), "inline": True},
                {"name": "Rythme", "value": f"toutes les {intervalle_s:.0f} s pendant {duree_min:.0f} min", "inline": True},
            ],
            "timestamp": maintenant(),
        }]
        if bilan.erreurs:
            texte = "\n".join(f"• **{s}** : {m[:150]}" for s, m in sorted(bilan.erreurs.items()))
            embeds.append({"title": f"⚠️ {len(bilan.erreurs)} source(s) en erreur", "description": texte[:4000], "color": ORANGE})
        self.discord.embeds("", embeds)


def executer(surveillance: Surveillance, une_fois: bool = False) -> int:
    """Enchaîne les cycles pendant DUREE_MINUTES, ou un seul cycle si une_fois."""
    import signal

    r = surveillance.reglages
    duree = 0.0 if une_fois else r.duree_minutes * 60
    intervalle = r.intervalle_secondes
    arret = {"demande": False}

    def demander_arret(signum: int, _frame: Any) -> None:
        log(f"Signal {signum} reçu, arrêt propre après ce cycle.")
        arret["demande"] = True

    signal.signal(signal.SIGTERM, demander_arret)
    signal.signal(signal.SIGINT, demander_arret)

    debut = time.monotonic()
    fin = debut + duree
    taches = len(surveillance.boutiques) + len(surveillance.produits)
    with ThreadPoolExecutor(max_workers=max(1, min(r.max_workers, taches))) as executeur:
        while True:
            top = time.monotonic()
            bilan = surveillance.cycle(executeur)
            etat_mod.sauvegarder(r.fichier_etat, surveillance.etat)
            log(
                f"— cycle {surveillance.cycle_n} en {bilan.duree:.1f} s ({bilan.requetes} requêtes"
                + (f", {bilan.decouvertes} découverte(s)" if bilan.decouvertes else "")
                + f") : {len(bilan.offres)} fiches, {bilan.en_stock} en stock, {bilan.rupture} en rupture, "
                f"{len(bilan.erreurs)} source(s) en erreur"
            )
            if surveillance.cycle_n == 1 and r.evenement_github == "workflow_dispatch":
                surveillance.resume_discord(bilan, duree / 60, intervalle)
            if une_fois or arret["demande"]:
                break
            prochain = top + intervalle
            if prochain + 1.0 >= fin:  # le prochain cycle dépasserait la durée prévue
                break
            while time.monotonic() < prochain and not arret["demande"]:
                time.sleep(min(1.0, prochain - time.monotonic()))
    log(f"Terminé après {surveillance.cycle_n} cycle(s) et {(time.monotonic() - debut) / 60:.1f} min.")
    return 0
