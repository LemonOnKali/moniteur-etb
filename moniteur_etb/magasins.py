"""Stock en magasin autour d'une zone (retrait 1h / click & collect).

magasins.json :

    {
      "zone": {"nom": "Marseille", "latitude": 43.2965, "longitude": 5.3698,
               "rayon_km": 20, "code_postal": "13001"},
      "enseignes": [{"nom": "Micromania", "type": "micromania", ...}]
    }

Pour chaque enseigne, deux temps comme pour une boutique :

- **découverte** : les pages « 30 ans » et les recherches de l'enseigne donnent
  les fiches de la gamme (UPC, ETB… y compris celles mises en ligne plus tard) ;
- **vérification** : pour chaque fiche, la liste des magasins de la zone qui
  l'ont en stock, avec la quantité quand l'enseigne la donne.

Chaque couple magasin × produit est une offre : l'alerte part quand un magasin
passe de « rien » à « en stock ». Le stock affiché par l'enseigne vient de son
logiciel de caisse : il peut avoir quelques heures de retard sur le rayon.
"""

from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import quote, urlsplit, urlunsplit

from .boutiques import Analyse, liens_fiches
from .collection import Collection, Item, langue_acceptee
from .http import ACCEPT_HTML, PAUSES, ErreurVerification, en_pause, telecharger, telecharger_json
from .modeles import Offre
from .pages import page_anti_robot
from .texte import texte_visible

INTERVALLE_DEFAUT_S = 120.0
RECHERCHES_DEFAUT = ["pokemon 30 ans"]


@dataclass
class Zone:
    nom: str
    latitude: float
    longitude: float
    rayon_km: float = 20.0
    code_postal: str = ""

    def distance_km(self, latitude: float, longitude: float) -> float:
        """Distance à vol d'oiseau (formule de haversine)."""
        p1, p2 = math.radians(self.latitude), math.radians(latitude)
        dp, dl = p2 - p1, math.radians(longitude - self.longitude)
        a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        return 6371.0 * 2 * math.asin(math.sqrt(a))

    @classmethod
    def depuis_dict(cls, brut: Any) -> "Zone":
        if not isinstance(brut, dict):
            raise ValueError("'zone' doit être un objet : nom, latitude, longitude, rayon_km, code_postal")
        try:
            return cls(
                nom=str(brut.get("nom") or "zone"),
                latitude=float(brut["latitude"]),
                longitude=float(brut["longitude"]),
                rayon_km=float(brut.get("rayon_km", 20)),
                code_postal=str(brut.get("code_postal") or ""),
            )
        except (KeyError, TypeError, ValueError):
            raise ValueError("'zone' : latitude et longitude (nombres) obligatoires") from None


@dataclass
class Magasin:
    id: str
    nom: str
    adresse: str
    distance_km: float


@dataclass
class FicheMagasin:
    """Un produit 30 ans de l'enseigne, suivi dans tous les magasins de la zone."""

    ref: str
    url: str
    titre: str
    item: Item
    langue: str = "?"


@dataclass
class Enseigne:
    nom: str
    type: str
    url: str
    zone: Zone
    pages: list[str] = field(default_factory=list)
    recherche_url: str | None = None
    recherches: list[str] = field(default_factory=lambda: list(RECHERCHES_DEFAUT))
    motif_fiche: re.Pattern[str] | None = None
    intervalle: float = INTERVALLE_DEFAUT_S
    ecart: float | None = None
    actif: bool = True
    produits: list[dict[str, str]] = field(default_factory=list)  # liste fixe : ref (EAN…), nom, url, item
    items: frozenset[str] = frozenset()  # produits suivis en magasin (ids de collection.json) ; vide = toute la gamme

    def suit(self, item: Item) -> bool:
        return not self.items or item.id in self.items

    # État d'exécution
    detectee: str = "magasins"
    categories_trouvees: list[str] = field(default_factory=list)
    fiches: dict[str, FicheMagasin] = field(default_factory=dict)  # ref → fiche
    magasins: dict[str, Magasin] = field(default_factory=dict)  # id → magasin de la zone
    derniere_decouverte: float | None = None
    derniere_verification: float | None = None
    derniere_erreur: str = ""

    @property
    def racine(self) -> str:
        parts = urlsplit(self.url)
        return urlunsplit((parts.scheme, parts.netloc, "", "", ""))

    def decouverte_due(self, intervalle_s: float) -> bool:
        return self.derniere_decouverte is None or time.monotonic() - self.derniere_decouverte >= intervalle_s

    def verification_due(self) -> bool:
        return self.derniere_verification is None or time.monotonic() - self.derniere_verification >= self.intervalle - 1

    @classmethod
    def depuis_dict(cls, brut: Any, zone: Zone, index: int, items: frozenset[str] = frozenset()) -> "Enseigne":
        if not isinstance(brut, dict):
            raise ValueError(f"enseigne n°{index + 1} : doit être un objet JSON")
        nom = str(brut.get("nom", "")).strip()
        type_ = str(brut.get("type", "")).strip().lower()
        if not nom:
            raise ValueError(f"enseigne n°{index + 1} : champ 'nom' manquant")
        if type_ not in LECTEURS:
            raise ValueError(f"enseigne '{nom}' : type {type_!r} inconnu ({', '.join(sorted(LECTEURS))})")
        lecteur = LECTEURS[type_]
        url = str(brut.get("url") or lecteur.url).rstrip("/")
        recherche_url = str(brut.get("recherche_url") or "").strip() or None
        if recherche_url and "{q}" not in recherche_url:
            raise ValueError(f"enseigne '{nom}' : 'recherche_url' doit contenir {{q}}")
        pages = brut.get("pages") or []
        recherches = brut.get("recherches")
        if not isinstance(pages, list) or (recherches is not None and not isinstance(recherches, list)):
            raise ValueError(f"enseigne '{nom}' : 'pages' et 'recherches' doivent être des listes")
        produits = brut.get("produits") or []
        if not isinstance(produits, list) or not all(isinstance(p, dict) and p.get("ref") and p.get("nom") for p in produits):
            raise ValueError(f"enseigne '{nom}' : 'produits' doit être une liste d'objets avec 'ref' et 'nom'")
        if not pages and not recherche_url and not produits:
            raise ValueError(f"enseigne '{nom}' : 'pages', 'recherche_url' ou 'produits' obligatoire (quels produits suivre)")
        try:
            motif = re.compile(str(brut.get("motif_fiche") or lecteur.motif_fiche))
            intervalle = float(brut.get("intervalle_secondes", INTERVALLE_DEFAUT_S))
            ecart = float(brut["ecart_secondes"]) if brut.get("ecart_secondes") is not None else None
        except re.error as err:
            raise ValueError(f"enseigne '{nom}' : 'motif_fiche' invalide ({err})") from None
        except (TypeError, ValueError):
            raise ValueError(f"enseigne '{nom}' : 'intervalle_secondes' et 'ecart_secondes' doivent être des nombres") from None
        zone_propre = Zone.depuis_dict(brut["zone"]) if "zone" in brut else zone
        return cls(
            nom=nom,
            type=type_,
            url=url,
            zone=zone_propre,
            pages=[str(p).strip() for p in pages if str(p).strip()],
            recherche_url=recherche_url,
            recherches=[str(r) for r in recherches] if recherches is not None else list(RECHERCHES_DEFAUT),
            motif_fiche=motif,
            intervalle=intervalle,
            ecart=ecart,
            actif=bool(brut.get("actif", True)),
            produits=[{k: str(v) for k, v in p.items()} for p in produits],
            items=_items(brut["items"], nom) if "items" in brut else items,
        )


_PETITS_MOTS = {"de", "du", "des", "la", "le", "les", "d", "l", "et", "en", "sur", "sous", "au", "aux"}


def joli_nom(nom: str) -> str:
    """« MARSEILLE TERRASSES DU PORT » → « Marseille Terrasses du Port »."""
    mots_ = re.split(r"(\s+|-|')", nom.strip().lower())
    sortie = []
    for i, m in enumerate(mots_):
        sortie.append(m if (i and m in _PETITS_MOTS) else m[:1].upper() + m[1:])
    return "".join(sortie)


def _json(url: str) -> Any:
    """JSON d'un service d'enseigne. Une page HTML à la place (anti-robot) met le site en pause."""
    try:
        return telecharger_json(url, ajax=True, cadence="hote")
    except ErreurVerification as err:
        if str(err).startswith("réponse non JSON"):
            duree = PAUSES.echec(urlsplit(url).hostname or "")
            raise ErreurVerification(f"page anti-robot au lieu des données — pause {duree / 60:.0f} min") from None
        raise


# --------------------------------------------------------------------------- #
# Lecteurs par enseigne
# --------------------------------------------------------------------------- #


class Lecteur(Protocol):
    url: str
    motif_fiche: str

    def ref(self, url: str) -> str | None: ...

    def magasins(self, e: Enseigne, ref: str, en_stock: bool) -> list[tuple[Magasin, int | None]]: ...


class Micromania:
    """Demandware (Salesforce Commerce Cloud) : service « Retrait 1h » de la fiche produit.

    Stores-InventorySearch renvoie les magasins autour d'un code postal ; avec
    isCC=true&isPDP=true, seulement ceux qui ont le produit en stock, avec la
    quantité (preferredStoreStock).
    """

    url = "https://www.micromania.fr"
    motif_fiche = r"/p/[^/]+-\d+\.html$"
    RAYONS = (15, 30, 50, 100, 300)  # seules valeurs acceptées par le service
    _RE_REF = re.compile(r"-(\d+)\.html$")

    def ref(self, url: str) -> str | None:
        m = self._RE_REF.search(urlsplit(url).path)
        return m.group(1) if m else None

    def magasins(self, e: Enseigne, ref: str, en_stock: bool) -> list[tuple[Magasin, int | None]]:
        rayon = next((r for r in self.RAYONS if r >= e.zone.rayon_km), self.RAYONS[-1])
        url = (
            f"{e.racine}/on/demandware.store/Sites-Micromania-Site/fr_FR/Stores-InventorySearch"
            f"?showMap=false&products={quote(ref)}%3A1&radius={rayon}&postalCode={quote(e.zone.code_postal)}"
            + ("&isCC=true&isPDP=true" if en_stock else "")
        )
        donnees = _json(url)
        magasins = donnees.get("stores") if isinstance(donnees, dict) else None
        if not isinstance(magasins, list):
            raise ErreurVerification("réponse Micromania inattendue (pas de liste de magasins)")
        resultat: list[tuple[Magasin, int | None]] = []
        for s in magasins:
            if not isinstance(s, dict) or not s.get("ID"):
                continue
            try:
                distance = e.zone.distance_km(float(s["latitude"]), float(s["longitude"]))
            except (KeyError, TypeError, ValueError):
                continue
            if distance > e.zone.rayon_km:
                continue
            quantite = s.get("preferredStoreStock")
            quantite = int(quantite) if isinstance(quantite, (int, float)) and not isinstance(quantite, bool) else None
            if en_stock and (s.get("availableInStore") is False or quantite == 0):
                continue
            ville = joli_nom(str(s.get("city") or ""))
            adresse = ", ".join(x for x in (s.get("address1"), s.get("address2"), f"{s.get('postalCode') or ''} {ville}".strip()) if x)
            nom = joli_nom(str(s.get("name") or s["ID"]))
            resultat.append((Magasin(id=str(s["ID"]), nom=nom, adresse=adresse, distance_km=distance), quantite))
        return resultat


class Leclerc:
    """E.Leclerc : offres « retrait magasin » d'un code-barres autour d'un point.

    /api/rest/offer/cnc-offer-pickups-by-ean/{EAN} (service de la fiche produit)
    renvoie les magasins qui proposent le produit en retrait, avec leur distance
    en km ; pas de quantité. /api/rest/locator/pdv donne les magasins de la zone.
    """

    url = "https://www.e.leclerc"
    motif_fiche = r"/fp/[^/]+-\d{8,14}$"
    _RE_REF = re.compile(r"-(\d{8,14})$")
    ACTIVITE_HYPER = "101"

    def ref(self, url: str) -> str | None:
        m = self._RE_REF.search(urlsplit(url).path.rstrip("/"))
        return m.group(1) if m else None

    def magasins(self, e: Enseigne, ref: str, en_stock: bool) -> list[tuple[Magasin, int | None]]:
        z = e.zone
        if not en_stock:
            donnees = _json(f"{e.racine}/api/rest/locator/pdv?lat={z.latitude}&long={z.longitude}&limit=30")
            departements = donnees.get("list") if isinstance(donnees, dict) else None
            if not isinstance(departements, list):
                raise ErreurVerification("réponse Leclerc inattendue (pas de liste de magasins)")
            resultat = []
            for d in departements:
                for s in (d.get("stores") or []) if isinstance(d, dict) else []:
                    if not isinstance(s, dict) or s.get("activityCode") != self.ACTIVITE_HYPER or not s.get("signCode"):
                        continue
                    distance = float(s.get("distance") or 0) / 1000  # mètres
                    if distance <= z.rayon_km:
                        resultat.append((Magasin(id=str(s["signCode"]), nom=joli_nom(str(s.get("name") or s["signCode"])),
                                                 adresse=self._adresse(s.get("address"), "zipCode"), distance_km=distance), None))
            return resultat
        donnees = _json(f"{e.racine}/api/rest/offer/cnc-offer-pickups-by-ean/{quote(ref)}?lat={z.latitude}&long={z.longitude}&limit=30")
        departements = donnees.get("departments") if isinstance(donnees, dict) else None
        if not isinstance(departements, list):
            raise ErreurVerification("réponse Leclerc inattendue (pas de liste d'offres retrait)")
        resultat = []
        for d in departements:
            for p in (d.get("pickups") or []) if isinstance(d, dict) else []:
                if not isinstance(p, dict) or not p.get("signCode"):
                    continue
                try:
                    distance = float(p["distance"])  # km
                except (KeyError, TypeError, ValueError):
                    continue
                if distance <= z.rayon_km:
                    resultat.append((Magasin(id=str(p["signCode"]), nom=joli_nom(str(p.get("shopName") or p["signCode"])),
                                             adresse=self._adresse(p.get("address"), "postalCode"), distance_km=distance), None))
        return resultat

    @staticmethod
    def _adresse(adresse: Any, cle_cp: str) -> str:
        if not isinstance(adresse, dict):
            return ""
        ville = f"{adresse.get(cle_cp) or ''} {joli_nom(str(adresse.get('city') or ''))}".strip()
        return ", ".join(x for x in (str(adresse.get("lines") or "").strip().title(), ville) if x)


LECTEURS: dict[str, Lecteur] = {"micromania": Micromania(), "leclerc": Leclerc()}


# --------------------------------------------------------------------------- #
# Découverte et vérification
# --------------------------------------------------------------------------- #


def _decouvrir(e: Enseigne, lecteur: Lecteur, collection: Collection, langues: frozenset[str], analyse: Analyse) -> None:
    sources = list(e.pages)
    if e.recherche_url:
        sources += [e.recherche_url.replace("{q}", quote(t)) for t in e.recherches]
    trouvees: dict[str, FicheMagasin] = {}
    echecs = 0
    for url in sources:
        analyse.requetes += 1
        try:
            page = telecharger(url, accept=ACCEPT_HTML, cadence="hote").texte()
        except ErreurVerification as err:
            echecs += 1
            analyse.erreurs.append(f"{url} : {err}")
            if en_pause(url):
                break
            continue
        assert e.motif_fiche is not None
        liens = liens_fiches(page, e.racine, e.motif_fiche)
        if not liens:
            raison = page_anti_robot(page, texte_visible(page))
            if not raison and url not in e.pages:
                continue  # recherche sans résultat : produit pas encore en ligne, pas un blocage
            raison = raison or "aucune fiche sur la page (blocage anti-robot ?)"
            echecs += 1
            duree = PAUSES.echec(urlsplit(url).hostname or "")
            analyse.erreurs.append(f"{url} : {raison} — pause {duree / 60:.0f} min")
            break
        for f in liens:
            ref = lecteur.ref(f.url)
            if not ref or ref in trouvees:
                continue
            classement = collection.classer(f.titre, exiger_marqueur=True)
            if classement is None or not langue_acceptee(classement.langue, langues) or not e.suit(classement.item):
                analyse.autres.append(f)
                continue
            trouvees[ref] = FicheMagasin(ref=ref, url=f.url, titre=f.titre, item=classement.item, langue=classement.langue)
    if trouvees or not echecs:
        # Pages en échec : on garde les fiches de la fois précédente (pas de trou de surveillance).
        e.fiches = {**(e.fiches if echecs else {}), **trouvees}
    e.derniere_decouverte = time.monotonic()


def analyser_magasins(e: Enseigne, collection: Collection, langues: frozenset[str], decouvrir: bool) -> Analyse:
    """Découverte (si due) puis stock de chaque fiche dans les magasins de la zone. Ne lève jamais."""
    analyse = Analyse(offres=[], autres=[])
    lecteur = LECTEURS[e.type]
    decouvrir = decouvrir or e.derniere_decouverte is None
    analyse.decouverte = decouvrir
    e.derniere_verification = time.monotonic()
    try:
        if e.produits and not e.fiches:
            for p in e.produits:
                item = collection.item(p.get("item", "")) or getattr(collection.classer(p["nom"], exiger_marqueur=False), "item", None)
                if item is None:
                    analyse.erreurs.append(f"{p['nom']} : produit non reconnu (ajoute 'item')")
                    continue
                if not e.suit(item):
                    continue
                url = p.get("url") or e.url
                e.fiches[p["ref"]] = FicheMagasin(ref=p["ref"], url=url, titre=p["nom"], item=item)
        if decouvrir and (e.pages or e.recherche_url):
            _decouvrir(e, lecteur, collection, langues, analyse)
        elif decouvrir:
            e.derniere_decouverte = time.monotonic()
        if decouvrir or not e.magasins:  # liste manquée (site en pause) : on la redemande au tour suivant
            if e.fiches and not en_pause(e.url):
                # Liste des magasins de la zone (même ceux sans stock) : leur état « rien en
                # stock » est connu, l'alerte partira bien quand le stock arrivera.
                analyse.requetes += 1
                try:
                    tous = lecteur.magasins(e, next(iter(e.fiches)), en_stock=False)
                    e.magasins.update({m.id: m for m, _ in tous})
                except ErreurVerification as err:
                    analyse.erreurs.append(f"liste des magasins : {err}")
        for fiche in list(e.fiches.values()):
            if en_pause(e.url):
                analyse.erreurs.append("site en pause : vérification reportée")
                break
            analyse.requetes += 1
            try:
                stocks = {m.id: (m, q) for m, q in lecteur.magasins(e, fiche.ref, en_stock=True)}
            except ErreurVerification as err:
                analyse.erreurs.append(f"{fiche.titre} : {err}")
                continue
            for m, _ in stocks.values():
                e.magasins.setdefault(m.id, m)
            for mid, magasin in e.magasins.items():
                quantite = stocks[mid][1] if mid in stocks else None
                analyse.offres.append(_offre(e, fiche, magasin, mid in stocks, quantite))
    except Exception as err:  # garde-fou : un bug sur une enseigne ne stoppe pas le moniteur
        analyse.erreurs.append(f"erreur inattendue {type(err).__name__} : {err}")
    e.derniere_erreur = " | ".join(analyse.erreurs)
    return analyse


def _offre(e: Enseigne, fiche: FicheMagasin, magasin: Magasin, dispo: bool, quantite: int | None) -> Offre:
    distance = f"{magasin.distance_km:.1f} km".replace(".", ",")
    return Offre(
        cle=f"magasin:{e.type}:{magasin.id}:{fiche.ref}".lower(),
        boutique=f"{e.nom} {magasin.nom}",
        titre=fiche.titre,
        url=fiche.url,
        item=fiche.item,
        langue=fiche.langue,
        dispo=dispo,
        quantite=quantite if dispo else None,
        detail=f"{magasin.adresse} · {distance}",
        source="magasin",
        extras={"enseigne": e.nom, "magasin": magasin.nom, "adresse": magasin.adresse, "distance": distance},
    )


def charger_enseignes(brut: Any, source: str = "magasins.json") -> list[Enseigne]:
    """magasins.json déjà lu (objet avec « zone » et « enseignes »). Lève ValueError."""
    if not isinstance(brut, dict) or not isinstance(brut.get("enseignes"), list):
        raise ValueError(f"{source} : objet avec 'zone' et 'enseignes' (liste) attendu")
    zone = Zone.depuis_dict(brut.get("zone"))
    items = _items(brut["items"], source) if "items" in brut else frozenset()
    return [Enseigne.depuis_dict(e, zone, i, items) for i, e in enumerate(brut["enseignes"])]


def _items(brut: Any, ou: str) -> frozenset[str]:
    """« items » : ids des produits suivis en magasin (etb, upc-journee…, voir collection.json)."""
    if not isinstance(brut, list) or not all(isinstance(i, str) and i.strip() for i in brut):
        raise ValueError(f"{ou} : 'items' doit être une liste d'ids de collection.json (ex. [\"etb\", \"upc-journee\"])")
    return frozenset(i.strip() for i in brut)

