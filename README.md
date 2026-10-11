# moniteur-etb — toute la gamme Pokémon 30 ans

Moniteur de stock **gratuit** qui tourne sur GitHub Actions et envoie une alerte
Discord dès qu'un produit de la gamme **JCC Pokémon 30e Anniversaire** passe en
stock, dans des dizaines de boutiques. Aucune dépendance : Python 3.12 et sa
bibliothèque standard, c'est tout.

## Ce qui est surveillé

**Toute la gamme** (fichier `collection.json`), chaque produit avec son plafond
anti-spéculateurs :

| Produit | Plafond |
|---|---|
| 📦 Coffret Dresseur d'Élite (ETB) | 100 € |
| 🏆 Coffret Dresseur d'Élite Pokémon Center | 130 € |
| ☀️ 🌙 Collections Ultra-Premium Journée (Mentali) / Soirée (Noctali) | 300 € |
| 🟣 Collection Premium Métamorph | 80 € |
| 🧸 Collections Figurine Mew / Mewtwo | 65 € |
| 🎁 Bundle 6 boosters | 60 € |
| 📒 Collection Classeur | 60 € |
| 🎀 Coffrets Nymphali-ex / Amphinobi-ex · 🥫 Pokébox | 45 € |
| 🎂 Coffret Pokémon Day 2026 | 45 € |
| 🖼️ Collection Poster | 40 € |
| 🏷️ Collections Autocollants (Noadkoko / Lucario) | 32 € |
| ⚔️ Decks de Combat Mentali-ex / Noctali-ex | 30 € |
| 🃏 Tripack · Duopack Évoli | 28 € · 20 € |
| 🥫 Mini Tins Jour / Nuit | 25 € |
| 🥊 Collection K.O. | 22 € |
| 🎴 Booster à l'unité | 9 € |

Les cartes à l'unité, cartes gradées, accessoires (protections, sleeves…),
boîtes vides, autres jeux (Magic 30th…) et l'ancienne gamme 25 ans
(Célébrations) sont ignorés. Un prix plancher écarte aussi les faux positifs
(une « protection acrylique ETB » à 15 € n'est pas un ETB).

**Dans toutes ces boutiques** :

- `boutiques.json` — boutiques **surveillées en entier** : Shopify, WooCommerce
  et PrestaShop. Le moniteur trouve tout seul leurs fiches 30 ans (catégorie
  « 30 ans » de la boutique + recherche), **y compris celles mises en ligne
  après son lancement**.
- `produits.json` — fiches surveillées une par une : enseignes sans catalogue
  exploitable (UltraJeux, JouéClub, Micromania…).
- `produits-pc.json` — grandes enseignes qui bloquent les serveurs GitHub
  (Amazon, Carrefour…), surveillées depuis ton PC (voir plus bas).

## Comment ça marche

- GitHub Actions lance le moniteur toutes les 15 min ; chaque exécution
  surveille ~6 h et la suivante prend le relais : couverture continue.
- **Vérification toutes les 30 s**, toutes les boutiques **en parallèle**. Une
  boutique entière ne coûte que 1 à 3 requêtes par cycle (catégorie Shopify,
  liste d'ids WooCommerce, recherche PrestaShop).
- **Recherche de nouvelles fiches toutes les 15 min** dans chaque boutique.
- **Alerte uniquement au passage en stock** (ou quand le prix repasse sous le
  plafond). L'état est conservé entre les exécutions : pas de doublon, et
  jamais deux alertes à moins de 10 min pour une même fiche.
- Un site qui bloque (403/429) ou ne répond pas est mis **en pause** (2 min,
  puis 4, 8… 30 min au plus) au lieu d'être martelé.
- Filtre de langue : cartes **françaises** par défaut (variable `LANGUES`).

### Sur Discord

Chaque alerte est une carte avec l'image du produit, le prix, la boutique, la
langue, le stock restant quand la boutique le donne, et le lien direct :

```
@everyone 🚨 Bundle 6 boosters en stock chez LorenZone à 39,90 €
┃ 🎁 Bundle 6 boosters
┃ Pokémon Bundle 6 Boosters 30e Anniversaire FR
┃ 🆕 Nouvelle fiche
┃ 💶 39,90 €   🏪 LorenZone   🌐 🇫🇷 FR   📊 3 restant(s)
```

Plusieurs alertes dans le même cycle partent dans un seul message (10 cartes
max). Un lancement manuel envoie un **résumé** : nombre de boutiques par
produit, fiches suivies, sources en erreur.

## Installation (2 minutes)

1. Sur Discord : *Paramètres du salon → Intégrations → Webhooks → Nouveau webhook*,
   copie l'URL.
2. Sur GitHub : *Settings → Secrets and variables → Actions → New repository secret*,
   nom `DISCORD_WEBHOOK`, valeur = l'URL du webhook. **Ne mets jamais l'URL dans
   le code.**
3. (Optionnel) Onglet *Variables* :
   - `DISCORD_MENTION` = `@everyone` ou `<@&ID_DU_ROLE>` pour être pingé ;
   - `LANGUES` = `fr,en` pour accepter aussi les cartes anglaises ;
   - `INTERVALLE_SECONDES` (30), `DECOUVERTE_MINUTES` (15) ;
   - `PRIX_MAX` : plafond des produits qui n'en ont pas dans `collection.json`.
4. Onglet *Actions* → *Moniteur de stock* → *Run workflow*. Tu dois recevoir
   le résumé `✅ Moniteur lancé` sur Discord.

> Le dépôt doit rester **public** pour que les minutes Actions soient illimitées
> (un dépôt privé n'a que 2 000 min/mois, épuisées en une journée).

## Ajouter une boutique

**Shopify, WooCommerce ou PrestaShop** (la grande majorité des boutiques TCG) :
onglet *Actions* → *Tester les boutiques* → *Run workflow*, et colle les
adresses dans « Boutiques à tester » (séparées par des espaces) :

```
https://boutique-une.fr https://boutique-deux.com
```

Le test détecte la plateforme, liste les fiches 30 ans trouvées et affiche les
lignes à copier dans `boutiques.json` :

```json
{"nom": "LorenZone", "url": "https://lorenzone.fr", "plateforme": "shopify"}
```

| Champ | Description |
|---|---|
| `nom`, `url` | Nom affiché et adresse de la boutique (avec `/fr` si la boutique a un préfixe de langue). |
| `plateforme` | `shopify`, `woocommerce`, `prestashop` ou `auto` (défaut : détectée au démarrage). |
| `categories` | Shopify : handles des catégories à surveiller, si la détection automatique ne les trouve pas. |
| `recherches` | Termes de recherche propres à cette boutique (défaut : ceux de `collection.json`). |
| `prix_max` | Plafond pour toute la boutique (remplace ceux de `collection.json`). |
| `actif` | `false` pour mettre la boutique en pause. |

**Autre site** : ajoute la fiche dans `produits.json` :

```json
{
  "boutique": "UltraJeux",
  "nom": "Coffret Dresseur d'Élite 30 ans",
  "url": "https://www.ultrajeux.com/produit-32960-....html",
  "type": "texte"
}
```

| Champ | Description |
|---|---|
| `boutique`, `nom`, `url` | Boutique et nom affichés, adresse de la fiche. Le nom sert à classer le produit (ETB, UPC…). |
| `item` | Force le produit (`etb`, `bundle`, `upc-journee`… voir `collection.json`). |
| `type` | `shopify`, `woocommerce`, `prestashop`, `texte` ou `auto` (défaut). |
| `mots_rupture` / `mots_stock` | Type `texte` : rupture si un mot de rupture apparaît / en stock si un mot de stock apparaît. |
| `regex_rupture` / `regex_stock` | Type `texte` : expression régulière sur le HTML brut. |
| `variante` | Shopify : ne surveiller que les variantes dont le titre contient ce texte. |
| `prix_max` | Plafond pour cette fiche. |
| `actif`, `note` | Pause sans suppression ; commentaire libre. |

Le type `texte` lit d'abord les données structurées de la page (schema.org
`InStock` / `OutOfStock`, Proximis de JouéClub…), puis `regex_*`, puis les mots
du texte visible. Il refuse de conclure « en stock » sur une page presque vide.

Ensuite : *Tester les boutiques* sans option lance un diagnostic complet de
`boutiques.json` et `produits.json` (fiches trouvées, prix, erreurs, extraits
de page pour régler une fiche `texte`).

## Ajuster la gamme

`collection.json` décrit chaque produit : `motifs` (mots du titre, « a + b »
exige les deux), `prix_max` (plafond) et `prix_min` (plancher). Le premier
produit qui correspond l'emporte, les plus précis sont donc en premier.
`marqueurs` dit ce qui fait partie de la gamme (30e anniversaire, 30 ans,
30th, ME05.5…) et `exclusions` ce qui n'en fait jamais partie.

## Surveiller les grandes enseignes depuis ton PC

Amazon, Carrefour et Courses U bloquent les serveurs GitHub mais répondent
depuis une box internet. Le workflow **Moniteur de stock (PC)** exécute le
moniteur sur ton ordinateur avec `produits-pc.json`, via un *runner
auto-hébergé* GitHub. Les alertes arrivent sur le même Discord.

1. Installe Python 3.12 depuis https://www.python.org/downloads/ en cochant
   **Add python.exe to PATH** et, dans *Customize installation*, **Install for
   all users**.
2. Sur GitHub : *Settings → Actions → Runners → New self-hosted runner*, choisis
   ton système et copie-colle les commandes affichées dans un terminal. À la
   question « run as service », réponds `Y` pour qu'il démarre avec le PC.
3. *Tester les boutiques* → *Run workflow* avec le choix `pc` pour vérifier ce
   que chaque enseigne répond depuis chez toi.
4. *Moniteur de stock (PC)* → *Run workflow*.

Fnac, Cdiscount et Smyths exigent un vrai navigateur (Datadome, PerimeterX) et
restent hors de portée : garde leurs alertes officielles.

Pour retrouver les fiches des enseignes depuis une page « où acheter »
(comparateur, article) : *Tester les boutiques* avec le champ « page_liens »,
ou `python moniteur.py --liens URL`.

## En local

```bash
python moniteur.py --diagnostic                   # un passage détaillé, sans Discord
python moniteur.py --decouvrir https://boutique.fr  # tester une nouvelle boutique
python moniteur.py --une-fois                     # un cycle normal
DISCORD_WEBHOOK=https://discord.com/api/webhooks/... python moniteur.py --test-discord
python -m unittest discover -s tests              # tests (hors ligne)
```

Réglages (variables d'environnement ou variables de dépôt) : `DUREE_MINUTES`
(350 sur GitHub), `INTERVALLE_SECONDES` (30), `DECOUVERTE_MINUTES` (15),
`TIMEOUT_SECONDES` (15), `LANGUES` (`fr`), `PRIX_MAX`, `ANTI_SPAM_MINUTES` (10),
`ALERTE_RUPTURE=1` pour être prévenu aussi des ruptures.

## Organisation du code

```
moniteur.py               point d'entrée
moniteur_etb/
  collection.py           reconnaître et classer un produit de la gamme
  boutiques.py            découverte et vérification d'une boutique entière
  pages.py                vérification d'une fiche précise (produits.json)
  surveillance.py         cycles, décisions d'alerte, état
  discord.py              messages Discord (embeds groupés)
  http.py                 téléchargements, pauses par site
  diagnostic.py           --diagnostic, --decouvrir, --liens
tests/                    tests unitaires hors ligne
```
