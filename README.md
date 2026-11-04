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
| 🏆 Coffret Dresseur d'Élite Pokémon Center | 130 € |
| 📦 Coffret Dresseur d'Élite (ETB) | 100 € |
| ☀️ Collection Ultra-Premium Journée (Mentali) | 300 € |
| 🌙 Collection Ultra-Premium Soirée (Noctali) | 300 € |
| 💎 Collection Ultra-Premium | 300 € |
| 🟣 Collection Premium Métamorph | 80 € |
| ⚔️ Deck de Combat Mentali-ex / Noctali-ex | 30 € |
| 📒 Collection Classeur | 60 € |
| 🥫 Mini Tin Jour / Nuit | 25 € |
| 🎁 Bundle 6 boosters | 70 € |
| 🥫 Pokébox Nymphali / Amphinobi | 45 € |
| 🎀 Coffret Nymphali-ex / Amphinobi-ex | 45 € |
| 🖼️ Collection Poster | 40 € |
| 🏷️ Collection Autocollants (Noadkoko / Lucario) | 32 € |
| 🧸 Collection Figurine Mew / Mewtwo | 65 € |
| 📌 Collection Pin's Deluxe Premiers Partenaires | 60 € |
| 🌱 Collection Illustration Premiers Partenaires | 60 € |
| 🎂 Coffret Journée Pokémon (Pokémon Day 2026) | 45 € |
| 🥊 Collection K.O. | 22 € |
| 🃏 Tripack (3 boosters) | 28 € |
| 🃏 Duopack Évoli (2 boosters) | 20 € |
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

Boutiques couvertes aujourd'hui (≈ 250 fiches 30 ans suivies) :

| Plateforme | Boutiques |
|---|---|
| Shopify (catalogue entier) | LorenZone, PokeMael, Collect Avenue, Poke-Geek, Hikaru Distribution, Outpost Brussels, TradingCards XXX, VCollect, Cartes-Pokemon.com |
| WooCommerce (catalogue entier) | Ecardstore, PixelHeart, Guizette Family, GoRetroGaming, PokeShop.cards |
| PrestaShop (catalogue entier) | Pokezenith, Foxchip, BCD Jeux, Pokesumo, 1001hobbies, Fantastik, Le Monde Imaginaire, Pokémon Carte, Espace Kids |
| Grandes enseignes (recherche ou page « 30 ans », puis fiche par fiche) | Auchan, JouéClub, Micromania |
| Grandes enseignes par code-barres (15 références dont les 2 UPC) | E.Leclerc (`produits.json`), Carrefour (`produits-pc.json`) |
| Fiches (`produits.json`) | UltraJeux, Au Dé Mon du Jeu, Dstrib, Ludocortex, Plaza TCG, Les Gentlemen du Jeu, Blazing Tail |
| Depuis le PC (`boutiques-pc.json`, `produits-pc.json`) | Carrefour, King Jouet, Cultura (recherche), Amazon (ETB, UPC, Mini Tins), Courses U, MediaMarkt |

Les UPC (et toute fiche « à venir ») sont suivies avant même leur mise en ligne :
tant que l'enseigne n'a pas publié la fiche, elle compte comme « pas encore en
ligne » ; l'alerte part dès qu'elle apparaît en stock.

Hors de portée sans vrai navigateur : Fnac, Cdiscount, Smyths (anti-robot),
Play-in (stock chargé en JavaScript), Pokémon Center.

## Stock en magasin (Marseille + 20 km)

En plus des sites, le moniteur regarde le **stock des magasins physiques**
autour de Marseille (fichier `magasins.json`) et prévient dès qu'un magasin
reçoit un produit de la gamme :

> 🚨 **Collection Ultra-Premium Journée (Mentali)** en stock **en magasin** chez
> **Micromania La Valentine** (4 pièce(s)) — adresse, distance, lien de la fiche.

| Enseigne | Ce qu'on lit | Quantité | Magasins à moins de 20 km |
|---|---|---|---|
| Micromania | service « Retrait 1h » de la fiche produit | ✅ nombre de pièces | Terrasses du Port, Bonneveine, Grand Littoral, La Valentine, Avant Cap (Cabriès), Vitrolles, Aubagne |
| E.Leclerc | offres « retrait magasin » par code-barres | ❌ disponible / pas disponible | Sormiou, Cabriès (Plan de Campagne), Vitrolles, Marignane |

Micromania est vérifié toutes les 4 min, Leclerc toutes les 5 min (15
références par code-barres, y compris les UPC avant leur sortie). Les produits
Micromania sont retrouvés tout seuls sur sa page « 30 ans » : une fiche mise en
ligne plus tard est suivie dès la découverte suivante (toutes les 15 min). Si
une enseigne répond par une page anti-robot, elle est laissée tranquille
quelques minutes avant de réessayer.

Ce stock vient du logiciel de caisse de l'enseigne : il peut avoir quelques
heures de retard sur le rayon (carton en réserve, mise en rayon le lendemain).
Appelle le magasin ou réserve en « retrait » avant de te déplacer.

**Changer de ville ou de rayon** : dans `magasins.json`, `zone` → `latitude`,
`longitude` (clic droit sur Google Maps → coordonnées), `code_postal` et
`rayon_km`.

Auchan, JouéClub, Carrefour, King Jouet, Cultura, Fnac et Smyths ne sont pas
suivis en magasin : leur stock par magasin n'est lisible qu'avec un vrai
navigateur et un magasin choisi (session), ou leur site bloque les robots.

## Comment ça marche

- GitHub Actions lance le moniteur toutes les 15 min ; chaque exécution
  surveille ~6 h et la suivante prend le relais : couverture continue.
- **Vérification toutes les 30 s**, toutes les boutiques **en parallèle**. Une
  boutique entière ne coûte que 1 à 3 requêtes par cycle (catégorie Shopify,
  liste d'ids WooCommerce, recherche PrestaShop).
- **Recherche de nouvelles fiches toutes les 15 min** dans chaque boutique,
  étalée sur plusieurs cycles (3 boutiques au plus par cycle).
- Shopify limite le débit par adresse IP sur l'ensemble de ses boutiques : les
  requêtes Shopify passent par une file commune (1,5 s d'écart, ralentie
  automatiquement si Shopify répond 429).
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
lignes à copier dans `boutiques.json`. Une adresse de **fiche produit** (Amazon,
Micromania, JouéClub…) est testée comme une fiche et donne la ligne à copier
dans `produits.json`.

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
| `intervalle_secondes` | Délai minimal entre deux vérifications de cette boutique (défaut : chaque cycle ; 120 s pour une boutique lue fiche par fiche). |
| `recherche_url`, `pages`, `motif_fiche` | Plateforme `html` (grandes enseignes) : page de recherche avec `{q}` pour le terme, pages à parcourir (catégorie « 30 ans »), et expression des adresses de fiche. Voir Auchan, JouéClub, Micromania dans `boutiques.json` et Carrefour, King Jouet, Cultura dans `boutiques-pc.json`. |
| `ecart_secondes` | Écart minimal entre deux pages du site (défaut 2 s) : les grandes enseignes bloquent les rafales. |
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
| `a_venir` | `true` pour un produit annoncé dont la fiche n'est pas encore en ligne : un 404 compte comme « pas encore en ligne » au lieu d'une erreur, et l'alerte part dès que la fiche apparaît en stock. Chez Leclerc et Carrefour, l'adresse se construit avec le code-barres (EAN). |
| `type` | `shopify`, `woocommerce`, `prestashop`, `texte` ou `auto` (défaut). |
| `mots_rupture` / `mots_stock` | Type `texte` : rupture si un mot de rupture apparaît / en stock si un mot de stock apparaît. |
| `regex_rupture` / `regex_stock` | Type `texte` : expression régulière sur le HTML brut. |
| `variante` | Shopify : ne surveiller que les variantes dont le titre contient ce texte. |
| `prix_max` | Plafond pour cette fiche. |
| `intervalle_secondes`, `ecart_secondes` | Délai entre deux vérifications de la fiche, écart minimal entre deux pages du même site. |
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

## Lancer le moniteur sur ton PC

Amazon, Carrefour, King Jouet, Cultura, Courses U et MediaMarkt bloquent les
serveurs GitHub mais répondent depuis une box internet. Sur ton PC, le
moniteur surveille ces grandes enseignes (`produits-pc.json`,
`boutiques-pc.json`) ; les boutiques spécialisées et E.Leclerc restent suivies
24 h/24 par GitHub. Les alertes arrivent sur le même Discord, sans doublon.

**Une seule fois**

1. Installe Python 3.12 depuis https://www.python.org/downloads/ en cochant
   **Add python.exe to PATH**.
2. Sur la page GitHub du dépôt : **Code → Download ZIP**, puis extrais le
   dossier (par exemple dans `Documents\moniteur-etb`). Avec `git clone` à la
   place, le lanceur se met à jour tout seul à chaque démarrage.

**Le lancer** : double-clic sur **`lancer-pc.bat`**.

- Au premier lancement il demande l'URL du webhook Discord (*Paramètres du
  salon → Intégrations → Webhooks → Copier l'URL*) et qui pinger. Elles sont
  gardées dans `discord-webhook.txt` / `discord-mention.txt`, sur ton PC
  uniquement (jamais envoyées sur GitHub).
- Tu reçois `✅ Moniteur lancé` sur Discord, puis les alertes. Une vérification
  toutes les 30 s ; chaque enseigne est interrogée à son rythme (une page toutes
  les 5 à 10 s) pour ne pas être bloquée.
- La fenêtre doit rester ouverte (tu peux la réduire). En cas de coupure
  internet ou d'erreur, le moniteur repart seul au bout de 30 s. Pour
  l'arrêter : ferme la fenêtre.
- Empêche la mise en veille : *Paramètres → Système → Alimentation → Mise en
  veille : Jamais* (un PC en veille ne surveille rien).
- Démarrage automatique avec Windows : touche Windows + R, tape
  `shell:startup`, Entrée, et place dans ce dossier un raccourci vers
  `lancer-pc.bat` (clic droit → *Afficher d'autres options → Créer un
  raccourci*).

**Tout surveiller depuis le PC** : `lancer-pc.bat tout` (dans une invite de
commandes ouverte dans le dossier, ou un raccourci dont la cible se termine par
` tout`) ajoute toutes les boutiques et E.Leclerc. À n'utiliser que si le
moniteur GitHub est arrêté, sinon chaque alerte arrive deux fois.

Linux, macOS ou Raspberry Pi : `./lancer-pc.sh` (ou `./lancer-pc.sh tout`).

**Ajouter un produit d'une grande enseigne** : ouvre sa fiche dans ton
navigateur, copie l'adresse, puis dans une invite de commandes ouverte dans le
dossier : `python moniteur.py --decouvrir URL` donne la ligne à copier dans
`produits-pc.json`. Une fiche pas encore en ligne (précommande à venir) se suit
avec `"a_venir": true` : tant que le site répond 404, elle compte comme « pas
encore disponible », sans erreur, et l'alerte part dès qu'elle est en vente.

**Variante : runner GitHub.** Le workflow *Moniteur de stock (PC)* fait la même
chose à travers un runner auto-hébergé (*Settings → Actions → Runners → New
self-hosted runner*, Windows, « run as service » : `Y`), lancé depuis l'onglet
*Actions*. N'utilise pas le runner et `lancer-pc.bat` en même temps (alertes
en double). *Tester les boutiques* avec `ou = pc` montre ce que chaque enseigne
répond depuis chez toi.

Fnac, Cdiscount et Smyths exigent un vrai navigateur (Datadome, PerimeterX) et
restent hors de portée : garde leurs alertes officielles (application, « me
prévenir »).

Pour retrouver les fiches des enseignes depuis une page « où acheter »
(comparateur, article) : *Tester les boutiques* avec le champ « page_liens »,
ou `python moniteur.py --liens URL`.

## En local

```bash
python moniteur.py --diagnostic                   # un passage détaillé, sans Discord
python moniteur.py --decouvrir https://boutique.fr  # tester une boutique (ou une fiche produit)
python moniteur.py --une-fois                     # un cycle normal
python moniteur.py --pc                           # lancement PC (ce que fait lancer-pc.bat)
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
  magasins.py             stock en magasin autour d'une zone (magasins.json)
  diagnostic.py           --diagnostic, --decouvrir, --liens
tests/                    tests unitaires hors ligne
```
