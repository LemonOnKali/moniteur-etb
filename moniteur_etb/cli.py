"""Point d'entrée en ligne de commande (python moniteur.py --help)."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Callable
from concurrent.futures import ThreadPoolExecutor

from . import VERSION, etat, http
from .collection import Collection
from .diagnostic import decouvrir, diagnostiquer_boutique, diagnostiquer_produit, lister_liens
from .discord import Discord
from .reglages import Reglages
from .surveillance import Surveillance, charger_boutiques, charger_produits, executer, log


RACINE = Path(__file__).resolve().parent.parent
URL_WEBHOOK = ("https://discord.com/api/webhooks/", "https://discordapp.com/api/webhooks/",
               "https://ptb.discord.com/api/webhooks/", "https://canary.discord.com/api/webhooks/")


def _lire_ou_demander(fichier: Path, question: str, valide: Callable[[str], bool]) -> str | None:
    """Première ligne de `fichier`, sinon demandée une fois au clavier et enregistrée.

    Le fichier reste sur ce PC : il est ignoré par git, l'URL du webhook ne part jamais sur GitHub.
    """
    if fichier.exists():
        return next((l.strip() for l in fichier.read_text(encoding="utf-8").splitlines() if l.strip()), "")
    if not sys.stdin or not sys.stdin.isatty():
        return None
    while True:
        reponse = input(question).strip()
        if valide(reponse):
            fichier.write_text(reponse + "\n", encoding="utf-8")
            return reponse
        print("  Ce n'est pas une adresse valide, recommence.")


def preparer_pc(tout: bool) -> None:
    """Réglages du lancement direct sur un PC (lancer-pc.bat / lancer-pc.sh).

    - Grandes enseignes qui bloquent les serveurs GitHub (Carrefour, King Jouet,
      Cultura, Amazon…) ; avec --tout, toutes les boutiques en plus.
    - En continu tant que la fenêtre reste ouverte, résumé Discord au démarrage.
    - Webhook et mention lus dans discord-webhook.txt / discord-mention.txt
      (demandés au premier lancement).
    """
    os.chdir(RACINE)
    os.environ.setdefault("FICHIER_PRODUITS", "produits.json,produits-pc.json" if tout else "produits-pc.json")
    os.environ.setdefault("FICHIER_BOUTIQUES", "boutiques.json,boutiques-pc.json" if tout else "boutiques-pc.json")
    os.environ.setdefault("FICHIER_ETAT", "etat-pc.json")
    os.environ.setdefault("DUREE_MINUTES", "525600")  # un an : en pratique, jusqu'à la fermeture de la fenêtre
    os.environ.setdefault("INTERVALLE_SECONDES", "30")
    os.environ.setdefault("GITHUB_EVENT_NAME", "workflow_dispatch")  # résumé « Moniteur lancé » sur Discord
    if not os.environ.get("DISCORD_WEBHOOK"):
        webhook = _lire_ou_demander(
            RACINE / "discord-webhook.txt",
            "Colle l'URL du webhook Discord (Paramètres du salon > Intégrations > Webhooks) puis Entrée :\n> ",
            lambda r: r.startswith(URL_WEBHOOK),
        )
        if webhook:
            os.environ["DISCORD_WEBHOOK"] = webhook
            if not (RACINE / "discord-mention.txt").exists() and sys.stdin and sys.stdin.isatty():
                mention = input("Qui pinger à chaque alerte ? (@everyone, <@&ID_DU_ROLE>, ou Entrée pour personne)\n> ").strip()
                (RACINE / "discord-mention.txt").write_text(mention + "\n", encoding="utf-8")
    fichier_mention = RACINE / "discord-mention.txt"
    if not os.environ.get("DISCORD_MENTION") and fichier_mention.exists():
        mention = fichier_mention.read_text(encoding="utf-8").strip()
        if mention:
            os.environ["DISCORD_MENTION"] = mention


def main(argv: list[str] | None = None) -> int:
    parseur = argparse.ArgumentParser(description="Moniteur de stock Pokémon 30 ans avec alertes Discord.")
    parseur.add_argument("--une-fois", action="store_true", help="un seul cycle puis sortie")
    parseur.add_argument("--test-discord", action="store_true", help="envoie un message de test et quitte")
    parseur.add_argument("--diagnostic", action="store_true",
                         help="un passage détaillé sans Discord (boutiques et fiches), pour régler chaque site")
    parseur.add_argument("--decouvrir", nargs="+", metavar="URL",
                         help="teste des boutiques (Shopify, WooCommerce, PrestaShop) ou des fiches produit "
                              "et propose les lignes à ajouter")
    parseur.add_argument("--liens", metavar="URL", help="liste les liens marchands d'une page (comparateur) et quitte")
    parseur.add_argument("--pc", action="store_true",
                         help="lancement direct sur ce PC (grandes enseignes), en continu ; webhook lu dans discord-webhook.txt")
    parseur.add_argument("--tout", action="store_true",
                         help="avec --pc : surveille aussi toutes les boutiques (si le moniteur GitHub est arrêté)")
    args = parseur.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # emojis sous Windows
    if args.pc:
        preparer_pc(args.tout)
    reglages = Reglages.depuis_env()
    http.TIMEOUT_S = reglages.timeout_secondes
    discord = Discord(reglages.discord_webhook, reglages.discord_mention, reglages.timeout_secondes)

    if args.test_discord:
        return 0 if discord.texte("🧪 Test du moniteur : le webhook fonctionne.") else 1
    if args.liens:
        return lister_liens(args.liens)

    try:
        collection = Collection.charger(reglages.fichier_collection)
    except (OSError, ValueError) as err:
        sys.exit(f"{reglages.fichier_collection} illisible : {err}")
    if args.decouvrir:
        surveillance = Surveillance(reglages, collection, [], [], discord, {})
        return decouvrir(args.decouvrir, collection, reglages.langues, surveillance.offre_produit)

    produits = charger_produits(reglages.fichier_produits)
    boutiques = charger_boutiques(reglages.fichier_boutiques)
    if not produits and not boutiques:
        log("Rien à surveiller : vérifie boutiques.json et produits.json.")
        return 1

    if args.diagnostic:
        surveillance = Surveillance(reglages, collection, produits, boutiques, discord, {})
        with ThreadPoolExecutor(max_workers=max(1, min(reglages.max_workers, len(produits) + len(boutiques)))) as ex:
            analyses = list(ex.map(lambda b: diagnostiquer_boutique(b, collection, reglages.langues), boutiques))
            offres = list(ex.map(surveillance.offre_produit, produits))
        for produit, offre in zip(produits, offres):
            diagnostiquer_produit(produit, offre)
        fiches = [o for a in analyses for o in a.offres] + offres
        en_stock = sum(1 for o in fiches if o.dispo and not o.trop_chere)
        boutiques_ko = sum(1 for a in analyses if a.erreurs and not a.offres)
        print(
            f"\n{len(boutiques)} boutique(s) ({boutiques_ko} sans résultat à cause d'erreurs), {len(produits)} fiche(s) "
            f"listée(s) : {len(fiches)} fiche(s) 30 ans, {en_stock} en stock à un prix acceptable, "
            f"{sum(1 for o in offres if o.dispo is None)} fiche(s) en erreur"
        )
        return 0

    log(
        f"Moniteur v{VERSION} — {len(boutiques)} boutique(s) et {len(produits)} fiche(s), "
        f"toutes les {reglages.intervalle_secondes:.0f} s pendant {reglages.duree_minutes:.0f} min, "
        f"langues {','.join(sorted(reglages.langues))}"
    )
    if not reglages.discord_webhook:
        log("⚠️  DISCORD_WEBHOOK n'est pas défini : les alertes seront seulement affichées ici.")
    surveillance = Surveillance(reglages, collection, produits, boutiques, discord, etat.charger(reglages.fichier_etat))
    return executer(surveillance, une_fois=args.une_fois)
