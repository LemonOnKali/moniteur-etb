import unittest

from moniteur_etb.texte import formater_prix, lire_prix, mots, normaliser


class TestTexte(unittest.TestCase):
    def test_lire_prix(self):
        self.assertEqual(lire_prix("69.90"), 69.9)
        self.assertEqual(lire_prix("69,90 €"), 69.9)
        self.assertEqual(lire_prix("1 299,90 €"), 1299.9)
        self.assertEqual(lire_prix("1.299,90"), 1299.9)
        self.assertEqual(lire_prix("1,299.90"), 1299.9)
        self.assertEqual(lire_prix(6990, centimes=True), 69.9)
        self.assertIsNone(lire_prix(0))
        self.assertIsNone(lire_prix("0.00"))
        self.assertIsNone(lire_prix(None))
        self.assertIsNone(lire_prix(True))
        self.assertIsNone(lire_prix("gratuit"))

    def test_mots(self):
        self.assertEqual(mots("Coffret Dresseur d'Élite 30ᵉ Anniversaire"), "coffret dresseur d elite 30e anniversaire")
        self.assertEqual(mots("Collection K.O."), "collection k o")
        self.assertEqual(mots("Dresseur d&rsquo;&Eacute;lite"), "dresseur d elite")

    def test_normaliser(self):
        self.assertEqual(normaliser("  Épuisé   SOLD out "), "epuise sold out")

    def test_formater_prix(self):
        self.assertEqual(formater_prix(1299.9), "1 299,90 €")
        self.assertEqual(formater_prix(None), "")


class TestPrestashop16(unittest.TestCase):
    def test_variables_js(self):
        from moniteur_etb.pages import lire_prestashop_16

        page = ('<meta property="og:title" content="Coffret Dresseur d&#039;Élite 30 ans">'
                "<script>var productAvailableForOrder=true;var quantityAvailable=0;"
                "var allowBuyWhenOutOfStock=false;var productPrice=69.9;</script>")
        r = lire_prestashop_16(page)
        self.assertEqual((r.dispo, r.prix, r.titre), (False, 69.9, "Coffret Dresseur d'Élite 30 ans"))
        r = lire_prestashop_16(page.replace("quantityAvailable=0", "quantityAvailable=4"))
        self.assertEqual((r.dispo, r.quantite), (True, 4))


class TestReglages(unittest.TestCase):
    def test_aucune_boutique(self):
        import os
        from unittest import mock

        from moniteur_etb.reglages import Reglages

        for valeur, attendu in (("aucun", ""), ("", ""), ("Aucun", ""), ("autres.json", "autres.json")):
            with mock.patch.dict(os.environ, {"FICHIER_BOUTIQUES": valeur}):
                self.assertEqual(Reglages.depuis_env().fichier_boutiques, attendu)
        with mock.patch.dict(os.environ, {}, clear=True):  # Windows : variable vide = absente
            self.assertEqual(Reglages.depuis_env().fichier_boutiques, "boutiques.json")


if __name__ == "__main__":
    unittest.main()
