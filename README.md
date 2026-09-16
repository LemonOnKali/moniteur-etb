# moniteur-etb

Moniteur de stock **gratuit** qui tourne sur GitHub Actions et envoie une alerte
Discord dès qu'un produit passe en stock. Aucune dépendance : Python 3.12 et sa
bibliothèque standard, c'est tout.

## Comment ça marche

- GitHub Actions lance `moniteur.py` toutes les 15 min (et à la demande). Chaque
  exécution surveille pendant ~6 h et la suivante prend le relais : couverture
  continue même quand GitHub retarde ses crons.
- Une vérification **toutes les 60 s**, tous les produits **en parallèle**.
- Une alerte `🚨 EN STOCK : nom à prix €` + lien part sur Discord **uniquement au
  passage en stock**. L'état est conservé entre les exécutions (cache Actions),
  donc pas de doublon, et jamais deux alertes à moins de 10 min pour un même produit.
- Les produits en stock **au-dessus de `PRIX_MAX`** (100 € par défaut) sont
  ignorés : pas d'alerte pour les revendeurs spéculateurs.
- Un lancement manuel envoie `✅ Moniteur lancé` pour vérifier que tout fonctionne.

## Installation (2 minutes)

1. Sur Discord : *Paramètres du salon → Intégrations → Webhooks → Nouveau webhook*,
   copie l'URL.
2. Sur GitHub : *Settings → Secrets and variables → Actions → New repository secret*,
   nom `DISCORD_WEBHOOK`, valeur = l'URL du webhook. **Ne mets jamais l'URL dans
   le code.**
3. (Optionnel) Onglet *Variables* → `DISCORD_MENTION` = `@everyone` ou
   `<@&ID_DU_ROLE>` pour être pingé, `PRIX_MAX` pour changer le prix plafond.
4. Onglet *Actions* → *Moniteur de stock* → *Run workflow*. Tu dois recevoir
   `✅ Moniteur lancé` sur Discord.

> Le dépôt doit rester **public** pour que les minutes Actions soient illimitées
> (un dépôt privé n'a que 2 000 min/mois, épuisées en une journée).

## Boutiques surveillées

Voir `produits.json`. Actuellement, le Coffret Dresseur d'Élite 30e Anniversaire chez :
LorenZone, PokeMael, Collect Avenue, Poke-Geek, Hikaru Distribution, Outpost Brussels (Shopify) ·
Ecardstore, PixelHeart, Guizette Family (WooCommerce) · Foxchip, Les Gentlemen du Jeu, BCD Jeux,
Pokesumo, Ludocortex, Pokezenith, Plaza TCG, Fantastik, 1001hobbies (PrestaShop) ·
UltraJeux, Au Dé Mon du Jeu, Smartoys, Philibert, JouéClub, La Grande Récré (page HTML).

Les grandes enseignes (Amazon, Fnac, Cdiscount, Carrefour, Smyths, Cultura,
Courses U) bloquent les robots venant des serveurs GitHub. Elles sont
dans `produits-pc.json`, surveillé par le workflow **Moniteur de stock (PC)** qui
tourne sur ton propre ordinateur (voir ci-dessous).

## Surveiller les grandes enseignes depuis ton PC

Le workflow `monitor-pc.yml` exécute le même script sur ton ordinateur, avec
ton adresse IP de box, via un *runner auto-hébergé* GitHub. Les alertes arrivent
sur le même Discord.

1. Installe Python 3.12 depuis https://www.python.org/downloads/ en cochant
   **Add python.exe to PATH** et, dans *Customize installation*, **Install for
   all users**.
2. Sur GitHub : *Settings → Actions → Runners → New self-hosted runner*, choisis
   ton système et copie-colle les commandes affichées dans un terminal. À la
   question « run as service », réponds `Y` pour qu'il démarre avec le PC.
3. Onglet *Actions* → *Tester les boutiques* → *Run workflow* avec le choix `pc`
   pour vérifier ce que chaque enseigne répond depuis chez toi.
4. Onglet *Actions* → *Moniteur de stock (PC)* → *Run workflow*.

Pour retrouver les fiches produit des enseignes sur une page « où acheter »
(LeCrocoDeal, etc.) : *Tester les boutiques* → *Run workflow* en renseignant
le champ « page_liens » avec l'adresse de la page, ou en local :
`python moniteur.py --liens URL`.

Le PC doit rester allumé (un Raspberry Pi convient). Si une enseigne affiche
« page anti-robot » même depuis chez toi, elle exige un vrai navigateur : garde
ses alertes officielles.

## Ajouter une boutique

Ajoute une entrée dans `produits.json`, puis lance le workflow **Tester les
boutiques** (onglet *Actions*) : il vérifie chaque produit une fois, sans Discord,
et affiche des extraits de la page pour choisir le bon réglage.

```json
[
  {
    "nom": "LorenZone ETB 30 ans",
    "url": "https://lorenzone.fr/products/etb-30eme-anniversaire",
    "type": "shopify"
  },
  {
    "nom": "Boutique PrestaShop",
    "url": "https://exemple.fr/pokemon/1234-etb-30-ans.html",
    "type": "prestashop"
  },
  {
    "nom": "Site sans API",
    "url": "https://exemple.fr/etb-151",
    "type": "texte",
    "mots_rupture": ["rupture", "épuisé", "me prévenir"],
    "prix_max": 80
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
| `type` | non | `shopify`, `woocommerce`, `prestashop`, `texte` ou `auto` (défaut : `auto`, essaie les quatre dans l'ordre et mémorise le bon). |
| `mots_rupture` | non | Type `texte` : produit dispo si **aucun** de ces mots n'apparaît dans le texte visible. Défaut : `rupture`, `épuisé`, `indisponible`, `sold out`, `plus disponible`, `me prévenir`. |
| `mots_stock` | non | Type `texte` : produit dispo si **un** de ces mots apparaît (ex. `"ajouter au panier"`). Prioritaire sur `mots_rupture`. |
| `regex_rupture` | non | Type `texte` : expression régulière sur le HTML brut, rupture si elle matche (ex. `class="dispoFiche"[^>]*>\s*RUPTURE`). |
| `regex_stock` | non | Type `texte` : expression régulière sur le HTML brut, en stock si elle matche. |
| `variante` | non | Shopify : ne surveiller que les variantes dont le titre contient ce texte (ex. `"ETB"`). |
| `prix_max` | non | Prix plafond pour ce produit (remplace `PRIX_MAX`). |
| `actif` | non | `false` pour mettre un produit en pause sans le supprimer. |
| `note` | non | Commentaire libre, ignoré par le script. |

Quel type choisir ?

- **shopify** : l'URL contient `/products/`. Le plus fiable (JSON officiel, prix
  exact, variantes). Pour vérifier : ouvre `https://boutique/products/xxx.js`.
- **woocommerce** : site WordPress, URL en `/produit/` ou `/product/`. Utilise
  l'API publique du magasin.
- **prestashop** : URL du type `/1234-nom-du-produit.html`. Lit les données
  produit intégrées à la page (disponibilité, quantité, prix).
- **texte** : tout le reste. Le script lit d'abord les données structurées
  schema.org de la page (`InStock` / `OutOfStock`), sinon `regex_*`, sinon les
  mots (texte visible seulement, accents et majuscules ignorés).
- **auto** : essaie les quatre et mémorise le bon.

## Tester en local

```bash
python moniteur.py --diagnostic                     # un passage détaillé, sans Discord
FICHIER_PRODUITS=produits-pc.json python moniteur.py --diagnostic   # idem pour les enseignes
python moniteur.py --une-fois                       # un cycle normal, sans Discord
DISCORD_WEBHOOK=https://discord.com/api/webhooks/... python moniteur.py --test-discord
```

Réglages par variables d'environnement (ou variables de dépôt GitHub pour le
workflow) : `DUREE_MINUTES` (350), `INTERVALLE_SECONDES` (60), `TIMEOUT_SECONDES`
(15), `PRIX_MAX` (100), `ANTI_SPAM_MINUTES` (10), `ALERTE_RUPTURE=1` pour être
prévenu aussi quand un produit repasse en rupture.
