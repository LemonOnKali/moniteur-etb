import os
import unittest
from unittest import mock

from moniteur_etb.boutiques import Boutique, analyser, couverture, fiche_prestashop, fiche_shopify, fiche_woocommerce
from moniteur_etb.collection import Collection
from moniteur_etb.http import PAUSES, ErreurHTTP, en_pause

from faux_web import FauxWeb

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COLLECTION = Collection.charger(os.path.join(RACINE, "collection.json"))
FR = frozenset({"fr"})


def produit_shopify(handle, titre, dispo, prix="69.90", variantes=None):
    return {
        "handle": handle,
        "title": titre,
        "images": [{"src": f"https://cdn.shopify.com/{handle}.jpg"}],
        "variants": variantes or [{"title": "Default Title", "available": dispo, "price": prix}],
    }


class TestFiches(unittest.TestCase):
    def test_shopify_variantes_et_langue(self):
        p = produit_shopify("etb", "ETB 30 ans", False, variantes=[
            {"title": "Français", "available": False, "price": "69.90"},
            {"title": "Japonais", "available": True, "price": "49.90"},
        ])
        f = fiche_shopify(p, "https://boutique.fr", filtre=lambda t: "japonais" not in t.lower())
        self.assertFalse(f.dispo)  # seule la variante japonaise est dispo : ignorée
        self.assertEqual(f.prix, 69.9)
        self.assertEqual(f.url, "https://boutique.fr/products/etb")
        self.assertEqual(f.image, "https://cdn.shopify.com/etb.jpg")

    def test_shopify_recherche(self):
        p = {"handle": "upc", "title": "UPC Journée 30 ans", "available": True, "price": "239.99",
             "image": "https://cdn.shopify.com/upc.jpg", "url": "/products/upc?_pos=1"}
        f = fiche_shopify(p, "https://boutique.fr")
        self.assertTrue(f.dispo)
        self.assertEqual(f.prix, 239.99)
        self.assertEqual(f.cle, "boutique.fr/products/upc")

    def test_woocommerce(self):
        p = {"id": 12, "name": "Coffret Dresseur d&rsquo;&Eacute;lite 30 ans", "permalink": "https://w.fr/produit/etb/",
             "is_in_stock": True, "is_purchasable": True, "prices": {"price": "6990", "currency_minor_unit": 2},
             "images": [{"src": "https://w.fr/etb.jpg"}], "low_stock_remaining": 3}
        f = fiche_woocommerce(p)
        self.assertEqual(f.titre, "Coffret Dresseur d’Élite 30 ans")
        self.assertTrue(f.dispo)
        self.assertEqual((f.prix, f.quantite, f.ref), (69.9, 3, "12"))

    def test_prestashop(self):
        p = {"id_product": 5, "name": "Bundle 30 ans", "url": "https://p.fr/5-bundle.html", "availability": "unavailable",
             "quantity": 0, "price_amount": 39.9, "add_to_cart_url": None,
             "cover": {"bySize": {"home_default": {"url": "https://p.fr/5.jpg"}}}}
        f = fiche_prestashop(p, "https://p.fr")
        self.assertFalse(f.dispo)
        self.assertEqual((f.prix, f.image), (39.9, "https://p.fr/5.jpg"))
        # Produit à déclinaisons disponible : pas de bouton panier en liste, mais bien en stock.
        p.update(availability="available", quantity=4)
        self.assertTrue(fiche_prestashop(p, "https://p.fr").dispo)

    def test_couverture(self):
        sources = {"categorie:30-ans": {"a", "b", "c"}, "recherche:anniversaire": {"a", "b"}, "recherche:30 ans": {"d"}}
        self.assertEqual(couverture(sources), ["categorie:30-ans", "recherche:30 ans"])
        self.assertEqual(couverture({}), [])


class TestAnalyse(unittest.TestCase):
    def setUp(self):
        PAUSES.vider()
        attente = mock.patch("moniteur_etb.boutiques._attendre")
        attente.start()
        self.addCleanup(attente.stop)

    def test_shopify_decouverte_puis_verification(self):
        web = FauxWeb({
            "/collections.json": {"collections": [
                {"handle": "pokemon-30-ans", "title": "Pokémon 30 ans"},
                {"handle": "mega-evolution", "title": "Méga-Évolution"},
            ]},
            "/collections/pokemon-30-ans/products.json": {"products": [
                produit_shopify("etb-pikachu", "Coffret Dresseur d'Élite Pikachu", True),
                produit_shopify("bundle", "Bundle 6 boosters", False, prix="35.99"),
                produit_shopify("protection", "Protection acrylique ETB", True, prix="14.90"),
            ]},
            "/search/suggest.json": {"resources": {"results": {"products": [
                {"handle": "upc-jour", "title": "Collection Ultra-Premium Journée 30 ans", "available": False,
                 "price": "239.99", "variants": [{"title": "Default Title", "available": False, "price": "239.99"}]},
                {"handle": "etb-mega", "title": "ETB Méga-Évolution", "available": True, "price": "59.90"},
            ]}}},
        })
        b = Boutique(nom="Test", url="https://shop.fr", plateforme="shopify")
        with web.actif():
            a = analyser(b, COLLECTION, FR, decouvrir=True)
        items = {o.item.id: o for o in a.offres}
        self.assertEqual(set(items), {"etb", "bundle", "upc-journee"})
        self.assertTrue(items["etb"].dispo)
        self.assertEqual(items["etb"].prix_max, 100)
        self.assertEqual(b.categories_trouvees, ["pokemon-30-ans"])
        self.assertIn("Protection acrylique ETB", [f.titre for f in a.autres])  # sous le prix plancher
        self.assertIn("ETB Méga-Évolution", [f.titre for f in a.autres])  # hors gamme

        # Cycle suivant : la catégorie + une seule recherche couvrent tout.
        web.appels.clear()
        with web.actif():
            a2 = analyser(b, COLLECTION, FR, decouvrir=False)
        self.assertEqual(len(web.appels), 2)
        self.assertEqual(len(a2.offres), 3)
        self.assertFalse(a2.decouverte)

    def test_woocommerce_verifie_par_ids(self):
        etb = {"id": 7, "name": "ETB 30e anniversaire", "permalink": "https://w.fr/produit/etb/", "is_in_stock": False,
               "prices": {"price": "6990", "currency_minor_unit": 2}}
        web = FauxWeb({"include=7": [dict(etb, is_in_stock=True)], "search=": [etb]})
        b = Boutique(nom="Woo", url="https://w.fr", plateforme="woocommerce")
        with web.actif():
            a = analyser(b, COLLECTION, FR, decouvrir=True)
            self.assertFalse(a.offres[0].dispo)
            web.appels.clear()
            a2 = analyser(b, COLLECTION, FR, decouvrir=False)
        self.assertEqual(len(web.appels), 1)
        self.assertIn("include=7", web.appels[0])
        self.assertTrue(a2.offres[0].dispo)

    def test_prestashop_json(self):
        produits = [{"name": "Coffret Poster 30e Anniversaire", "url": "https://p.fr/12-poster.html",
                     "availability": "available", "quantity": 2, "price_amount": 29.9}]
        web = FauxWeb({"controller=search": {"products": produits}})
        b = Boutique(nom="Presta", url="https://p.fr", plateforme="prestashop")
        with web.actif():
            a = analyser(b, COLLECTION, FR, decouvrir=True)
        self.assertEqual([o.item.id for o in a.offres], ["poster"])
        self.assertTrue(a.offres[0].dispo)
        self.assertEqual(a.offres[0].quantite, 2)
        self.assertIn("ajax=1", web.appels[0])

    def test_prestashop_sans_json_lit_les_fiches(self):
        recherche = (
            '<html><script>var prestashop = {};</script>'
            '<a href="https://p.fr/menu/55-etb-mega.html">ETB Méga-Évolution</a>'
            '<a href="/pokemon/12617-etb-30.html" class="thumbnail"><img src="x.jpg"></a>'
            '<h3 class="name"><a href="/pokemon/12617-etb-30.html">Coffret Dresseur d&#039;Élite 30 ans</a></h3>'
            '<a href="https://autre-site.fr/1-x.html">Pub</a></html>'
        )
        fiche = (
            '<div data-product="{&quot;name&quot;:&quot;Coffret Dresseur d\'Élite 30 ans&quot;,'
            '&quot;availability&quot;:&quot;available&quot;,&quot;quantity&quot;:3,&quot;price_amount&quot;:69.9}"></div>'
        )
        web = FauxWeb({"ajax=1": "pas du json", "controller=search": recherche, "12617-etb-30.html": fiche})
        b = Boutique(nom="Presta", url="https://p.fr", plateforme="prestashop")
        with web.actif(), mock.patch("moniteur_etb.boutiques.telecharger_page", lambda url: web.telecharger(url).texte()):
            a = analyser(b, COLLECTION, FR, decouvrir=True)
            self.assertTrue(b.presta_html)
            self.assertEqual([(o.item.id, o.dispo, o.prix) for o in a.offres], [("etb", True, 69.9)])
            web.appels.clear()
            a2 = analyser(b, COLLECTION, FR, decouvrir=False)  # cycle suivant : la fiche seule
        self.assertEqual(web.appels, ["https://p.fr/pokemon/12617-etb-30.html"])
        self.assertTrue(a2.offres[0].dispo)

    def test_categories_shopify_filtrees(self):
        web = FauxWeb({
            "/collections.json": {"collections": [
                {"handle": "cartes-a-lunites-30-ans-m6a-jpn", "title": "Cartes à l'unité 30 ans"},
                {"handle": "30-ans-pokemon-japonais", "title": "30 ans japonais"},
                {"handle": "pokemon-30-ans", "title": "Pokémon 30 ans"},
            ]},
            "/products.json": {"products": []},
            "/search/suggest.json": {"resources": {"results": {"products": []}}},
        })
        b = Boutique(nom="Test", url="https://shop.fr", plateforme="shopify")
        with web.actif():
            analyser(b, COLLECTION, FR, decouvrir=True)
        self.assertEqual(b.categories_trouvees, ["pokemon-30-ans"])
        recherches = [u for u in web.appels if "suggest" in u]
        self.assertEqual(len(recherches), 3)  # catégorie trouvée : 3 recherches seulement

    def test_limite_de_recherche_shopify(self):
        # 429 sur la recherche : pas de pause de la boutique, fiches déjà connues gardées.
        web = FauxWeb({
            "/collections.json": {"collections": []},
            "suggest.json?q=anniversaire": {"resources": {"results": {"products": [
                {"handle": "etb", "title": "ETB 30 ans", "available": False, "price": "69.90"}]}}},
            "suggest.json": ErreurHTTP(429, "Too Many Requests"),
            "/products/etb": {"handle": "etb", "title": "ETB 30 ans", "variants": []},
        })
        b = Boutique(nom="Test", url="https://shop.fr", plateforme="shopify")
        with web.actif():
            a = analyser(b, COLLECTION, FR, decouvrir=True)
        self.assertEqual(a.erreurs, [])
        self.assertIn("429", a.notes[0])
        self.assertEqual([o.item.id for o in a.offres], ["etb"])
        self.assertFalse(en_pause("https://shop.fr"))
        self.assertEqual(b.sources, {"recherche:anniversaire": {"shop.fr/products/etb"}})

    def test_detection_automatique(self):
        web = FauxWeb({"/products.json?limit=1": {"products": []}, "/collections.json": {"collections": []},
                       "/search/suggest.json": {"resources": {"results": {"products": []}}}})
        b = Boutique(nom="Auto", url="https://a.fr")
        with web.actif():
            a = analyser(b, COLLECTION, FR, decouvrir=True)
        self.assertEqual(b.detectee, "shopify")
        self.assertEqual(a.erreurs, [])

    def test_plateforme_inconnue_ne_reessaie_pas_a_chaque_cycle(self):
        web = FauxWeb({})
        b = Boutique(nom="Inconnue", url="https://x.fr")
        with web.actif():
            a = analyser(b, COLLECTION, FR, decouvrir=True)
            self.assertTrue(a.erreurs)
            web.appels.clear()
            analyser(b, COLLECTION, FR, decouvrir=False)
        self.assertEqual(web.appels, [])

    def test_langue_refusee(self):
        web = FauxWeb({"search=": [{"id": 1, "name": "ETB 30 ans Japonais", "permalink": "https://w.fr/produit/jp/",
                                    "is_in_stock": True, "prices": {"price": "5990", "currency_minor_unit": 2}}]})
        b = Boutique(nom="Woo", url="https://w.fr", plateforme="woocommerce")
        with web.actif():
            a = analyser(b, COLLECTION, FR, decouvrir=True)
        self.assertEqual(a.offres, [])
        with web.actif():
            b2 = Boutique(nom="Woo", url="https://w.fr", plateforme="woocommerce")
            a2 = analyser(b2, COLLECTION, frozenset({"fr", "jp"}), decouvrir=True)
        self.assertEqual(len(a2.offres), 1)


if __name__ == "__main__":
    unittest.main()
