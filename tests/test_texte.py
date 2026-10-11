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


if __name__ == "__main__":
    unittest.main()
