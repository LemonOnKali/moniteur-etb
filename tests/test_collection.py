import os
import unittest

from moniteur_etb.collection import Collection, langue_acceptee

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COLLECTION = Collection.charger(os.path.join(RACINE, "collection.json"))

# (titre de fiche, item attendu ou None si hors gamme)
CAS = [
    ("Coffret Dresseur d'Élite Pokémon 30ᵉ Anniversaire FR", "etb"),
    ("Pokémon : Coffret Dresseur d’élite 30ᵉ Anniversaire du JCC Pokémon (1 Carte Promo, 9 boosters)", "etb"),
    ("Pokemon 30A Coffret Dresseur d Elite", "etb"),
    ("ETB ME05.5 Pikachu", "etb"),
    ("Coffret ETB 30 ans + protection offerte", "etb"),
    ("ETB 30 ans Pokémon Center", "etb-pokemon-center"),
    ("Pokémon - Bundle 6 Boosters 30ème Anniversaire", "bundle"),
    ("Lot de boosters 30e anniversaire", "bundle"),
    ("Collection Ultra-Premium Journée 30e anniversaire", "upc-journee"),
    ("UPC Soirée Noctali 30 ans", "upc-soiree"),
    ("Coffret Collection Ultra Premium 30 ans", "upc"),
    ("Pokébox 30ᵉ Anniversaire Pokémon-ex Nymphali ou Amphinobi", "pokebox"),
    ("Coffret Pokémon 30ᵉ Anniversaire Nymphali-ex ou Amphinobi-ex", "coffret-ex"),
    ("Coffret Poster Pokémon 30ᵉ Anniversaire + 3 Boosters", "poster"),
    ("Collection K.O. 30 ans", "collection-ko"),
    ("Duopack Évoli 30e anniversaire", "duopack"),
    ("Blister 2 boosters 30 ans", "duopack"),
    ("Tripack 30 ans", "tripack"),
    ("Mini Tin Jour 30 ans", "mini-tin"),
    ("Collection Classeur 30e anniversaire", "classeur"),
    ("Deck de combat Mentali-ex 30 ans", "deck-combat"),
    ("Collection Premium Métamorph 30e Anniversaire", "metamorph-premium"),
    ("Coffret Collection Figurine Mew & Mewtwo - 30e Anniversaire - Français", "figurine"),
    ("Collection autocollants Noadkoko d'Alola 30 ans", "autocollants"),
    ("Booster 30e anniversaire", "booster"),
    ("Coffret Pokémon Day 2026 Pikachu", "pokemon-day"),
    # Hors gamme
    ("Display 30 ans japonais", None),
    ("Pikachu 025/196 30e anniversaire", None),
    ("Magic 30th Anniversary Edition", None),
    ("Celebrations ETB 25 ans", None),
    ("ETB 30 ans vide", None),
    ("Coffret Dresseur d'Élite Méga-Évolution", None),  # pas de marqueur 30 ans
    ("Carte Dracaufeu ex 30e anniversaire PSA 10", None),
]


class TestClassement(unittest.TestCase):
    def test_cas(self):
        for titre, attendu in CAS:
            with self.subTest(titre=titre):
                c = COLLECTION.classer(titre)
                self.assertEqual(c.item.id if c else None, attendu)

    def test_categorie_sans_marqueur(self):
        # Fiche venant d'une catégorie « 30 ans » : le titre n'a pas à le répéter.
        c = COLLECTION.classer("Coffret Dresseur d'Élite Pikachu", exiger_marqueur=False)
        self.assertEqual(c.item.id, "etb")

    def test_langues(self):
        self.assertEqual(COLLECTION.classer("Pokémon 30th Celebration Elite Trainer Box (EN)").langue, "en")
        self.assertEqual(COLLECTION.classer("ETB 30 ans version anglaise").langue, "en")
        self.assertEqual(COLLECTION.classer("ETB 30 ans Japonais").langue, "jp")
        self.assertEqual(COLLECTION.classer("ETB 30 ans FR").langue, "fr")
        self.assertEqual(COLLECTION.classer("Elite Trainer Box 30th version française").langue, "fr")
        self.assertEqual(COLLECTION.classer("Coffret Dresseur d'Élite 30 ans").langue, "?")
        self.assertTrue(langue_acceptee("?", frozenset({"fr"})))
        self.assertFalse(langue_acceptee("en", frozenset({"fr"})))
        self.assertTrue(langue_acceptee("en", frozenset({"fr", "en"})))

    def test_prix_plancher(self):
        etb = COLLECTION.item("etb")
        self.assertFalse(etb.prix_plausible(19.9))  # protection acrylique
        self.assertTrue(etb.prix_plausible(69.9))
        self.assertTrue(etb.prix_plausible(None))

    def test_categories_shopify(self):
        self.assertTrue(COLLECTION.fait_partie("pokemon-30e-anniversaire"))
        self.assertTrue(COLLECTION.fait_partie("30-ans-pokemon"))
        self.assertTrue(COLLECTION.fait_partie("Pokémon 30th Celebration"))
        self.assertFalse(COLLECTION.fait_partie("pokemon-mega-evolution"))


if __name__ == "__main__":
    unittest.main()
