"""Point d'entrée en ligne de commande (python moniteur.py --help)."""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor

from . import VERSION, etat, http
from .collection import Collection
from .diagnostic import decouvrir, diagnostiquer_boutique, diagnostiquer_produit, lister_liens
from .discord import Discord
from .reglages import Reglages
from .surveillance import Surveillance, charger_boutiques, charger_produits, executer, log


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
    args = parseur.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # emojis sous Windows
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
