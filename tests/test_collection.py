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


# Titres relevés dans de vraies boutiques lors des tests sur GitHub Actions.
CAS_REELS = [
    ("POKEMON - 30ème Anniversaire - Collection Poster - FR", "poster"),
    ("POKEMON -30ème Anniversaire -Collection Ultra Premium (1) Mentali - FR", "upc-journee"),
    ("POKEMON - 30ème Anniversaire - Battle Deck - Noctali / Mentali - FR", "deck-combat"),
    ("Deck du Dresseur Pokémon 30e Anniversaire Mentali / Noctali (Modèle Aléatoire)", "deck-combat"),
    ("Tripack Collection Autocollant Pokémon 30e Anniversaire (Modèle Aléatoire)", "autocollants"),
    ("Coffret Collection Figurine Pokémon 30e Anniversaire : Mewtwo", "figurine"),
    ("[Précommande] Coffret Collection avec Figurine Mew Pokémon 30e Anniversaire (FR)", "figurine"),
    ("[Précommande] Mini Tin Mewtwo (Nuit) Pokémon 30e Anniversaire (FR)", "mini-tin"),
    ("Coffret - Pokémon Day 2026 / 30 ans", "pokemon-day"),
    ("Coffret Journée Pokémon 2026 : Collection 30 Ans - Pikachu", "pokemon-day"),
    ("Coffret 30 Ans Journée 2026 Pikachu – FR", "pokemon-day"),
    ("Coffret Ultra-Premium (UPC) - 30ème Anniversaire", "upc"),
    ("30TH Anniversaire Pokémon Mentali UPC – Version Française", "upc-journee"),
    ("Pokémon · 30e Anniversaire - Collection Ultra Mentali Ex - FR", "upc-journee"),
    ("Pokémon - Coffret Collection Illustration Premiers Partenaires Série 3 - 30 Ans", "premiers-partenaires"),
    ("Coffret - Collection Avec Pin's Deluxe / Premiers Partenaires - 30 ans", "premiers-partenaires-pins"),
    ("Coffret 4 Boosters - 30ème Anniversaire", "coffret-ex"),
    ("Pokémon - Lot de 6 boosters ME05.5 : 30e Anniversaire", "bundle"),
    ("30e Anniversaire CEL30 - Lot de 2 Boosters", "duopack"),
    ("Collection Classeur Pokémon 30e Anniversaire – 5 Boosters – Français", "classeur"),
    ("Coffret Dresseur d'Élite Pokémon 30e Anniversaire – Français + Protection Phoenix Shield", "etb"),
    ("Pokémon - Collection K.O ME05.5 - 30e Anniversaire - Évoli", "collection-ko"),
    # Faux positifs vus en vrai
    ("Figurine Shrek 30Th Anniv - Donkey Pop 10cm", None),
    ("Tomb Raider POP! Games Vinyl figurine Lara Croft (30th Anniversary) 9 cm", None),
    ("Pokémon Battle Figure figurine Noctali (30th Anniversary Glitter) 8 cm", None),
    ("Peluches Pokémon Pastel 30th Anniversary 20 cm (Lot de 6)", None),
    ("Disney Le Roi Lion 30ème Anniversaire - Boîte de 10 Boosters de 4 Cartes", None),
    ("Funko Pop ! Casper – Ghostly Trio (30th Anniversary 3-Pack)", None),
    ('LAMBORGHINI REVUELTO 2024 VIOLET "VIOLA 30TH MATTE" (BLISTER EDITION) (LHD)', None),
    ("SNK Metal Slug 4-in-1 Coffret Collector 30th Anniversary", None),
    ("Pokemon 30th Anniversary Metal Charm Alola, Galar, Paldea Collection 4", None),
    ("Mewtwo ex SAR - 30th Celebration - M6a", None),
    ("Mew G/RGB – 30e Anniversaire", None),
    ("Deck Box - 30th Pikachu, Mew & Mewtwo", None),
    ("Sac - 30th Pikachu, Mew & Mewtwo", None),
    ("Héros Transcendants - Collection pin’s Deluxe Premiers Partenaires", None),
    ("V:TES - 30ème Anniversaire VF", None),
]


class TestClassement(unittest.TestCase):
    def test_cas_reels(self):
        for titre, attendu in CAS_REELS:
            with self.subTest(titre=titre):
                c = COLLECTION.classer(titre)
                self.assertEqual(c.item.id if c else None, attendu)

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
