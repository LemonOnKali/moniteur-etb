import os
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

from moniteur_etb.boutiques import Analyse, Boutique
from moniteur_etb.collection import Collection
from moniteur_etb.modeles import Offre
from moniteur_etb.reglages import Reglages
from moniteur_etb.surveillance import Surveillance

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COLLECTION = Collection.charger(os.path.join(RACINE, "collection.json"))


class FauxDiscord:
    def __init__(self, ok=True):
        self.webhook = "https://discord.test/webhook"
        self.ok = ok
        self.messages = []

    def embeds(self, contenu, embeds, mention=False):
        self.messages.append((contenu, embeds, mention))
        return [self.ok] * len(embeds)

    def texte(self, contenu, mention=False):
        self.messages.append((contenu, [], mention))
        return self.ok


def offre(item="etb", dispo=True, prix=69.9, url="https://shop.fr/products/etb"):
    return Offre(cle=url.removeprefix("https://"), boutique="Shop", titre="ETB 30 ans", url=url,
                 item=COLLECTION.item(item), dispo=dispo, prix=prix, prix_max=COLLECTION.item(item).prix_max)


class TestCycle(unittest.TestCase):
    def setUp(self):
        self.discord = FauxDiscord()
        self.boutique = Boutique(nom="Shop", url="https://shop.fr")
        self.surv = Surveillance(Reglages(anti_spam_minutes=0), COLLECTION, [], [self.boutique], self.discord, {})
        self.executeur = ThreadPoolExecutor(max_workers=2)
        self.reponses = []

    def tearDown(self):
        self.executeur.shutdown()

    def cycle(self, *offres):
        with mock.patch("moniteur_etb.surveillance.analyser", return_value=Analyse(offres=list(offres), autres=[])):
            return self.surv.cycle(self.executeur)

    def test_alerte_seulement_au_passage_en_stock(self):
        self.cycle(offre(dispo=True))
        self.assertEqual(len(self.discord.messages), 1)
        contenu, embeds, mention = self.discord.messages[0]
        self.assertTrue(mention)
        self.assertIn("Coffret Dresseur d'Élite", contenu)
        self.assertEqual(embeds[0]["url"], "https://shop.fr/products/etb")
        self.cycle(offre(dispo=True))
        self.assertEqual(len(self.discord.messages), 1)  # toujours en stock : pas de doublon
        self.cycle(offre(dispo=False))
        self.cycle(offre(dispo=True))
        self.assertEqual(len(self.discord.messages), 2)  # retour en stock

    def test_trop_cher(self):
        self.cycle(offre(dispo=True, prix=229.9))
        self.assertEqual(self.discord.messages, [])
        self.assertFalse(self.surv.etat["shop.fr/products/etb"]["dispo"])
        self.cycle(offre(dispo=True, prix=79.9))  # baisse de prix sous le plafond
        self.assertEqual(len(self.discord.messages), 1)

    def test_alertes_groupees(self):
        self.cycle(*[offre(url=f"https://shop.fr/products/{i}") for i in range(12)])
        self.assertEqual(len(self.discord.messages), 1)
        self.assertEqual(len(self.discord.messages[0][1]), 12)  # le découpage par 10 est fait par Discord.embeds

    def test_echec_discord_reessaye(self):
        self.discord.ok = False
        self.cycle(offre(dispo=True))
        self.discord.ok = True
        self.cycle(offre(dispo=True))
        self.assertEqual(len(self.discord.messages), 2)

    def test_erreur_ne_change_pas_l_etat(self):
        self.cycle(offre(dispo=True))
        erreur = offre(dispo=None)
        erreur.erreur = "HTTP 503"
        self.cycle(erreur)
        self.assertTrue(self.surv.etat["shop.fr/products/etb"]["dispo"])
        self.cycle(offre(dispo=True))
        self.assertEqual(len(self.discord.messages), 1)

    def test_anti_spam(self):
        self.surv.reglages.anti_spam_minutes = 10
        self.cycle(offre(dispo=True))
        self.cycle(offre(dispo=False))
        self.cycle(offre(dispo=True))  # oscillation de cache : pas de 2e alerte tout de suite
        self.assertEqual(len(self.discord.messages), 1)


class TestRythme(unittest.TestCase):
    def test_boutique_lue_fiche_par_fiche_menagee(self):
        b = Boutique(nom="Presta", url="https://p.fr", presta_html=True)
        self.assertTrue(b.verification_due())
        b.derniere_verification = time.monotonic()
        self.assertFalse(b.verification_due())
        b.intervalle = 0
        self.assertTrue(b.verification_due())


class TestCadence(unittest.TestCase):
    def test_file_commune_et_ralentissement(self):
        from moniteur_etb.http import Cadence

        c = Cadence(intervalle=1.5, minimum=1.0, maximum=4.0)
        c.ralentir()
        self.assertEqual(c.intervalle, 2.25)
        for _ in range(3):
            c.ralentir()
        self.assertEqual(c.intervalle, 4.0)  # plafonné
        c.intervalle = 1.0
        c.accelerer()
        self.assertEqual(c.intervalle, 1.0)  # jamais sous le minimum
        c._prochain = 0.0
        with mock.patch("moniteur_etb.http.time.sleep") as dormir:
            c.attendre()
            c.attendre()
        dormir.assert_called_once()  # la 2e requête attend son tour


class TestDecouvertesEtalees(unittest.TestCase):
    def test_trois_par_cycle(self):
        from moniteur_etb import surveillance as surv

        boutiques = [Boutique(nom=f"B{i}", url=f"https://b{i}.fr", derniere_decouverte=1.0) for i in range(7)]
        s = Surveillance(Reglages(), COLLECTION, [], boutiques, FauxDiscord(), {})
        appels = []

        def faux_analyser(b, collection, langues, decouvrir):
            appels.append(decouvrir)
            return Analyse(offres=[], autres=[])

        with mock.patch.object(surv, "analyser", faux_analyser), ThreadPoolExecutor(max_workers=2) as ex:
            s.verifier_tout(ex)
        self.assertEqual(sum(appels), surv.MAX_DECOUVERTES_PAR_CYCLE)
        self.assertEqual(len(appels), 7)


class TestDiscordPaquets(unittest.TestCase):
    def test_paquets_de_dix(self):
        from moniteur_etb.discord import Discord

        d = Discord("https://discord.test/webhook", mention="@everyone")
        envoyes = []
        with mock.patch.object(Discord, "poster", side_effect=lambda charge: envoyes.append(charge) or True):
            resultats = d.embeds("🚨 test", [{"title": f"e{i}"} for i in range(23)], mention=True)
        self.assertEqual([len(c["embeds"]) for c in envoyes], [10, 10, 3])
        self.assertEqual(envoyes[0]["content"], "@everyone 🚨 test")
        self.assertNotIn("content", envoyes[1])
        self.assertEqual(resultats, [True] * 23)


class TestDiscordImageRefusee(unittest.TestCase):
    def test_renvoi_sans_image(self):
        from moniteur_etb.discord import Discord

        d = Discord("https://discord.test/webhook")
        envoyes = []

        def poster(charge):
            envoyes.append(charge)
            d.dernier_code = 400 if any("thumbnail" in e for e in charge["embeds"]) else 204
            return d.dernier_code == 204

        with mock.patch.object(Discord, "poster", side_effect=poster):
            resultats = d.embeds("", [{"title": "ETB", "thumbnail": {"url": "https://x/y.jpg"}}])
        self.assertEqual(resultats, [True])
        self.assertEqual(len(envoyes), 2)
        self.assertNotIn("thumbnail", envoyes[1]["embeds"][0])


if __name__ == "__main__":
    unittest.main()
