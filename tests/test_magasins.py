"""Stock en magasin (magasins.json) : réponses Micromania calquées sur le vrai service."""

import json
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

from faux_web import FauxWeb

from moniteur_etb.collection import Collection
from moniteur_etb.discord import embed_offre, resume_alertes
from moniteur_etb.http import ErreurHTTP
from moniteur_etb.magasins import Enseigne, Zone, analyser_magasins, charger_enseignes
from moniteur_etb.reglages import Reglages
from moniteur_etb.surveillance import Surveillance

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COLLECTION = Collection.charger(os.path.join(RACINE, "collection.json"))
MARSEILLE = Zone(nom="Marseille", latitude=43.2965, longitude=5.3698, rayon_km=20, code_postal="13001")

PAGE_30_ANS = """
<a href="/p/coffret-pokemon-amphinobi-ex-30-ans-162657.html">Coffret Pokémon Amphinobi-ex 30 ans</a>
<a href="/p/pokemon-collection-ultra-premium-30-ans-mentali-163001.html">Pokémon Collection Ultra-Premium 30 ans Mentali</a>
<a href="/p/manette-ps5-dualsense-106098.html">Manette PS5 DualSense</a>
"""


def magasin(id_, nom, lat, lon, cp="13002", **stock):
    return {"ID": id_, "name": nom, "address1": "Centre commercial", "address2": "1 rue", "city": "MARSEILLE",
            "postalCode": cp, "latitude": lat, "longitude": lon, **stock}


TERRASSES = magasin("HI", "MARSEILLE TERRASSES DU PORT", 43.3064632, 5.3652026)
VALENTINE = magasin("MV", "LA VALENTINE", 43.2926681, 5.48006599, "13011")
AVIGNON = magasin("AV", "AVIGNON", 43.9493, 4.8055, "84000")  # hors zone : 85 km


def enseigne():
    return charger_enseignes({
        "zone": {"nom": "Marseille", "latitude": 43.2965, "longitude": 5.3698, "rayon_km": 20, "code_postal": "13001"},
        "enseignes": [{"nom": "Micromania", "type": "micromania", "pages": ["https://www.micromania.fr/c/carte-pokemon-30-ans"]}],
    })[0]


def routes(stock_upc):
    """Liste complète des magasins sans isCC ; avec isCC, seulement ceux qui ont du stock."""
    return {
        "products=163001%3A1&radius=30&postalCode=13001&isCC=true": {"stores": stock_upc},
        "products=162657%3A1&radius=30&postalCode=13001&isCC=true": {"stores": []},
        "Stores-InventorySearch": {"stores": [TERRASSES, VALENTINE, AVIGNON]},
        "carte-pokemon-30-ans": PAGE_30_ANS,
    }


def actif(web):
    return mock.patch.multiple("moniteur_etb.magasins", telecharger_json=web.telecharger_json, telecharger=web.telecharger)


class TestNoms(unittest.TestCase):
    def test_joli_nom(self):
        from moniteur_etb.magasins import joli_nom

        self.assertEqual(joli_nom("MARSEILLE TERRASSES DU PORT"), "Marseille Terrasses du Port")
        self.assertEqual(joli_nom("AIX-EN-PROVENCE"), "Aix-en-Provence")
        self.assertEqual(joli_nom("LA VALENTINE"), "La Valentine")


class TestZone(unittest.TestCase):
    def test_distances(self):
        self.assertLess(MARSEILLE.distance_km(43.3064632, 5.3652026), 2)  # Terrasses du Port
        self.assertAlmostEqual(MARSEILLE.distance_km(43.2926681, 5.48006599), 8.9, delta=0.3)  # La Valentine
        self.assertGreater(MARSEILLE.distance_km(43.9493, 4.8055), 80)  # Avignon


class TestMicromania(unittest.TestCase):
    def test_decouverte_et_stock_par_magasin(self):
        e = enseigne()
        en_stock = [dict(VALENTINE, availableInStore=True, preferredStoreStock=4, preferredStoreResource="En stock magasin")]
        web = FauxWeb(routes(en_stock))
        with actif(web):
            a = analyser_magasins(e, COLLECTION, frozenset({"fr"}), decouvrir=True)
        self.assertEqual(a.erreurs, [])
        self.assertEqual(sorted(e.fiches), ["162657", "163001"])  # la manette est écartée
        self.assertEqual(sorted(e.magasins), ["HI", "MV"])  # Avignon hors zone
        self.assertEqual(len(a.offres), 4)  # 2 produits × 2 magasins
        dispo = [o for o in a.offres if o.dispo]
        self.assertEqual(len(dispo), 1)
        o = dispo[0]
        self.assertEqual(o.boutique, "Micromania La Valentine")
        self.assertEqual(o.item.id, "upc-journee")
        self.assertEqual(o.quantite, 4)
        self.assertEqual(o.cle, "magasin:micromania:mv:163001")
        self.assertIn("8,9 km", o.detail)

    def test_seulement_etb_et_upc(self):
        e = charger_enseignes({
            "zone": {"nom": "Marseille", "latitude": 43.2965, "longitude": 5.3698, "rayon_km": 20, "code_postal": "13001"},
            "items": ["etb", "upc-journee", "upc-soiree", "upc"],
            "enseignes": [{"nom": "Micromania", "type": "micromania", "pages": ["https://www.micromania.fr/c/carte-pokemon-30-ans"]}],
        })[0]
        with actif(FauxWeb(routes([]))):
            a = analyser_magasins(e, COLLECTION, frozenset({"fr"}), decouvrir=True)
        self.assertEqual(sorted(e.fiches), ["163001"])  # l'UPC ; le coffret Amphinobi n'est pas suivi
        self.assertEqual({o.item.id for o in a.offres}, {"upc-journee"})
        with self.assertRaises(ValueError):
            charger_enseignes({"zone": {"latitude": 1, "longitude": 2}, "items": "etb", "enseignes": []})

    def test_quantite_nulle_ou_indisponible_ignoree(self):
        e = enseigne()
        en_stock = [dict(VALENTINE, availableInStore=False, preferredStoreStock=0), dict(TERRASSES, preferredStoreStock=0)]
        with actif(FauxWeb(routes(en_stock))):
            a = analyser_magasins(e, COLLECTION, frozenset({"fr"}), decouvrir=True)
        self.assertFalse(any(o.dispo for o in a.offres))

    def test_erreur_sur_un_produit_sans_planter(self):
        e = enseigne()
        r = {"isCC=true&isPDP=true": ErreurHTTP(410, "Gone"),
             "Stores-InventorySearch": {"stores": [TERRASSES]}, "carte-pokemon-30-ans": PAGE_30_ANS}
        with actif(FauxWeb(r)):
            a = analyser_magasins(e, COLLECTION, frozenset({"fr"}), decouvrir=True)
        self.assertEqual(len(a.erreurs), 2)  # un message par produit, pas d'exception
        self.assertEqual(a.offres, [])

    def test_page_anti_robot_met_le_site_en_pause(self):
        from moniteur_etb import http

        http.PAUSES.vider()
        e = enseigne()
        with actif(FauxWeb({"carte-pokemon-30-ans": "<html>Accès refusé</html>"})):
            a = analyser_magasins(e, COLLECTION, frozenset({"fr"}), decouvrir=True)
        self.assertEqual(len(a.erreurs), 1)
        self.assertGreater(http.PAUSES.restant("www.micromania.fr"), 0)
        http.PAUSES.vider()

    def test_reponse_html_au_lieu_du_json(self):
        from moniteur_etb import http, magasins

        http.PAUSES.vider()
        with mock.patch.object(magasins, "telecharger_json", side_effect=http.ErreurVerification("réponse non JSON (…)")):
            with self.assertRaises(http.ErreurVerification) as ctx:
                magasins.Micromania().magasins(enseigne(), "162657", en_stock=True)
        self.assertIn("anti-robot", str(ctx.exception))
        self.assertGreater(http.PAUSES.restant("www.micromania.fr"), 0)
        http.PAUSES.vider()

    def test_configuration_invalide(self):
        with self.assertRaises(ValueError):
            charger_enseignes({"zone": {"nom": "X"}, "enseignes": []})
        with self.assertRaises(ValueError):
            Enseigne.depuis_dict({"nom": "X", "type": "inconnu", "pages": ["https://x"]}, MARSEILLE, 0)

    def test_fichier_du_depot_valide(self):
        with open(os.path.join(RACINE, "magasins.json"), encoding="utf-8") as f:
            enseignes = charger_enseignes(json.load(f))
        self.assertTrue(enseignes)
        self.assertTrue(all(e.zone.rayon_km == 20 for e in enseignes))
        self.assertTrue(all(e.items == {"etb", "upc-journee", "upc-soiree", "upc"} for e in enseignes))


PDV = {"count": 1, "list": [{"code": "13", "name": "Bouches-du-Rhône", "stores": [
    {"signCode": "0313", "activityCode": "101", "name": "SORMIOU", "distance": 7484.1,
     "address": {"city": "MARSEILLE", "zipCode": "13009", "lines": "ZAC BAOU DE SORMIOU"}},
    {"signCode": "0313", "activityCode": "078", "name": "Espace Culturel", "distance": 7484.1,
     "address": {"city": "MARSEILLE", "zipCode": "13009", "lines": "ZAC BAOU DE SORMIOU"}},
    {"signCode": "2213", "activityCode": "101", "name": "CABRIES", "distance": 13772.7,
     "address": {"city": "CABRIES", "zipCode": "13480", "lines": "QUARTIER PLAN DE CAMPAGNE"}},
    {"signCode": "1613", "activityCode": "101", "name": "SALON", "distance": 42022.0,
     "address": {"city": "SALON", "zipCode": "13300", "lines": "LES VIOUGUES"}},
]}]}


def pickup(sign, nom, distance):
    return {"shopId": int(sign + "1011"), "signCode": sign, "shopName": nom, "distance": distance,
            "address": {"city": nom, "postalCode": "13000", "lines": "CENTRE"}}


class TestLeclerc(unittest.TestCase):
    def enseigne(self):
        return charger_enseignes({
            "zone": {"nom": "Marseille", "latitude": 43.2965, "longitude": 5.3698, "rayon_km": 20},
            "enseignes": [{"nom": "E.Leclerc", "type": "leclerc", "produits": [
                {"ref": "0196214155336", "nom": "Collection Ultra-Premium Journée (Mentali) 30 ans", "item": "upc-journee",
                 "url": "https://www.e.leclerc/fp/pokemon-30a-collection-ultra-premium-journee-mentali-0196214155336"},
                {"ref": "0196214146907", "nom": "Pokébox 30 ans"},
            ]}],
        })[0]

    def test_retrait_magasin_dans_la_zone(self):
        e = self.enseigne()
        web = FauxWeb({
            "locator/pdv": PDV,
            "cnc-offer-pickups-by-ean/0196214155336": {"ean": "0196214155336", "offersCount": 2, "departments": [
                {"code": "13", "pickups": [pickup("2213", "CABRIES", 13.77), pickup("1613", "SALON", 42.02)]}]},
            "cnc-offer-pickups-by-ean/0196214146907": {"ean": "0196214146907", "offersCount": 0, "departments": []},
        })
        with actif(web):
            a = analyser_magasins(e, COLLECTION, frozenset({"fr"}), decouvrir=True)
        self.assertEqual(a.erreurs, [])
        self.assertEqual(sorted(e.magasins), ["0313", "2213"])  # hypermarchés à moins de 20 km
        dispo = [o for o in a.offres if o.dispo]
        self.assertEqual([(o.boutique, o.item.id) for o in dispo], [("E.Leclerc Cabries", "upc-journee")])
        self.assertIsNone(dispo[0].quantite)
        self.assertEqual(len(a.offres), 4)  # 2 produits × 2 magasins
        self.assertIn("13,8 km", dispo[0].detail)
        # Pas de quantité chez Leclerc : l'alerte dit « en stock » sans nombre.
        champs = {c["name"]: c["value"] for c in embed_offre(dispo[0], nouvelle=False)["fields"]}
        self.assertEqual(champs["📦 Stock"], "en stock")


class FauxDiscord:
    webhook = "https://discord.test/webhook"

    def __init__(self):
        self.messages = []

    def embeds(self, contenu, embeds, mention=False):
        self.messages.append((contenu, embeds, mention))
        return [True] * len(embeds)

    def texte(self, contenu, mention=False):
        return True


class TestAlerteEnMagasin(unittest.TestCase):
    def test_alerte_quand_le_stock_arrive_dans_un_magasin(self):
        e = enseigne()
        discord = FauxDiscord()
        s = Surveillance(Reglages(), COLLECTION, [], [], discord, {"autre": {"dispo": False}}, [e])
        stock = []
        web = FauxWeb(routes(stock))
        with actif(web), ThreadPoolExecutor(max_workers=2) as ex:
            s.cycle(ex)  # rien en stock : pas d'alerte
            self.assertEqual(discord.messages, [])
            stock.append(dict(TERRASSES, availableInStore=True, preferredStoreStock=2))
            e.derniere_verification = None
            s.cycle(ex)
        self.assertEqual(len(discord.messages), 1)
        contenu, embeds, _ = discord.messages[0]
        self.assertIn("en magasin", contenu)
        self.assertIn("Micromania Marseille Terrasses du Port", contenu)
        self.assertIn("(2 pièce(s))", contenu)
        champs = {c["name"]: c["value"] for c in embeds[0]["fields"]}
        self.assertEqual(champs["📦 Stock"], "2 en magasin")
        self.assertIn("km", champs["🚗 Distance"])

    def test_embed_et_resume(self):
        e = enseigne()
        with actif(FauxWeb(routes([dict(VALENTINE, availableInStore=True, preferredStoreStock=7)]))):
            a = analyser_magasins(e, COLLECTION, frozenset({"fr"}), decouvrir=True)
        o = next(o for o in a.offres if o.dispo)
        embed = embed_offre(o, nouvelle=True)
        self.assertTrue(embed["title"].startswith("🏬"))
        self.assertIn("7 pièce(s)", resume_alertes([o]))


if __name__ == "__main__":
    unittest.main()
