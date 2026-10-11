#!/usr/bin/env python3
"""Moniteur de stock Pokémon 30e Anniversaire — GitHub Actions + Discord.

Bibliothèque standard uniquement. Voir README.md et `python moniteur.py --help`.

Fichiers :
  collection.json   la gamme 30 ans : comment reconnaître et classer chaque produit
  boutiques.json    boutiques surveillées en entier (Shopify, WooCommerce, PrestaShop)
  produits.json     fiches surveillées une par une (Amazon, JouéClub, Carrefour…)

Variables d'environnement principales :
  DISCORD_WEBHOOK       URL du webhook Discord (jamais dans le code !)
  DISCORD_MENTION       optionnel, ex. "@everyone" ou "<@&ID_DU_ROLE>"
  INTERVALLE_SECONDES   délai entre deux cycles (défaut 30)
  DUREE_MINUTES         durée totale d'une exécution (défaut 20)
  DECOUVERTE_MINUTES    délai entre deux recherches de nouvelles fiches (défaut 15)
  LANGUES               langues acceptées, ex. "fr" (défaut) ou "fr,en"
  PRIX_MAX              plafond pour les produits sans plafond dans collection.json
"""

import sys

from moniteur_etb.cli import main

if __name__ == "__main__":
    sys.exit(main())
