# moniteur-etb

Moniteur de stock **gratuit** qui tourne sur GitHub Actions et envoie une alerte
Discord dès qu'un produit passe en stock. Aucune dépendance : Python 3.12 et sa
bibliothèque standard, c'est tout.

## Comment ça marche

- GitHub Actions lance `moniteur.py` toutes les 15 min (et à la demande).
- Chaque exécution surveille pendant 20 min, une vérification **toutes les 60 s**,
  tous les produits **en parallèle**. Les exécutions s'enchaînent : la couverture
  est continue.
- Une alerte `🚨 EN STOCK : nom à prix €` + lien part sur Discord **uniquement au
  passage en stock**. L'état est conservé entre les exécutions (cache Actions),
  donc pas de doublon.
- Un lancement manuel (onglet *Actions* → *Run workflow*) envoie `✅ Moniteur lancé`
  pour vérifier que tout fonctionne.

## Installation (2 minutes)

1. Sur Discord : *Paramètres du salon → Intégrations → Webhooks → Nouveau webhook*,
   copie l'URL.
2. Sur GitHub : *Settings → Secrets and variables → Actions → New repository secret*,
   nom `DISCORD_WEBHOOK`, valeur = l'URL du webhook. **Ne mets jamais l'URL dans
   le code.**
3. (Optionnel) Pour être pingé : *Variables → New repository variable*, nom
   `DISCORD_MENTION`, valeur `@everyone` ou `<@&ID_DU_ROLE>`.
4. Onglet *Actions* → *Moniteur de stock* → *Run workflow*. Tu dois recevoir
   `✅ Moniteur lancé` sur Discord.

> Le dépôt doit rester **public** pour que les minutes Actions soient illimitées
> (un dépôt privé n'a que 2 000 min/mois, épuisées en ~2 jours).

## Ajouter une boutique

Ajoute une entrée dans `produits.json` :

```json
[
  {
    "nom": "LorenZone ETB 30 ans",
    "url": "https://lorenzone.fr/products/etb-30eme-anniversaire",
    "type": "shopify"
  },
  {
    "nom": "Boutique WooCommerce",
    "url": "https://exemple.fr/produit/etb-prismatic",
    "type": "woocommerce"
  },
  {
    "nom": "Site sans API",
    "url": "https://exemple.fr/etb-151",
    "type": "texte",
    "mots_rupture": ["rupture de stock", "épuisé", "indisponible", "sold out", "me prévenir"]
  },
  {
    "nom": "Je ne sais pas quel type",
    "url": "https://exemple.fr/produit/xyz",
    "type": "auto"
  }
]
```

| Champ | Obligatoire | Description |
|---|---|---|
| `nom` | oui | Nom affiché dans l'alerte. |
| `url` | oui | Page du produit. |
| `type` | non | `shopify`, `woocommerce`, `texte` ou `auto` (défaut : `auto`). |
| `mots_rupture` | non | Type `texte` : produit dispo si **aucun** de ces mots n'apparaît. Défaut : `rupture de stock`, `épuisé`, `indisponible`, `sold out`. |
| `mots_stock` | non | Type `texte` : produit dispo si **un** de ces mots apparaît (ex. `"ajouter au panier"`). Prioritaire sur `mots_rupture`. |
| `variante` | non | Shopify : ne surveiller que les variantes dont le titre contient ce texte (ex. `"ETB"`). |
| `actif` | non | `false` pour mettre un produit en pause sans le supprimer. |

Quel type choisir ?

- **shopify** : l'URL contient `/products/`. Le plus fiable (JSON officiel, prix
  exact, variantes). Pour vérifier : ouvre `https://boutique/products/xxx.js`.
- **woocommerce** : site WordPress, URL en `/produit/` ou `/product/`. Utilise
  l'API publique du magasin.
- **texte** : tout le reste. Le script ne lit que le texte visible de la page
  (pas le JS du thème), accents et majuscules ignorés.
- **auto** : essaie les trois dans l'ordre et mémorise le bon.

## Tester en local

```bash
python moniteur.py --une-fois                       # un cycle, sans Discord
DISCORD_WEBHOOK=https://discord.com/api/webhooks/... python moniteur.py --test-discord
```

Réglages possibles via variables d'environnement : `DUREE_MINUTES` (20),
`INTERVALLE_SECONDES` (60), `TIMEOUT_SECONDES` (15), `ALERTE_RUPTURE=1` pour
être prévenu aussi quand un produit repasse en rupture.
