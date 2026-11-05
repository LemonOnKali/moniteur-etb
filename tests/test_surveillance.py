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
        self.salons = []

    def embeds(self, contenu, embeds, mention=False, salon=""):
        self.messages.append((contenu, embeds, mention))
        self.salons.append(salon)
        return [self.ok] * len(embeds)

    def texte(self, contenu, mention=False, salon=""):
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
        b = Boutique(nom="Presta", url="https://p.fr", fiche_par_fiche=True)
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


class TestFileParSite(unittest.TestCase):
    def test_une_file_par_hote(self):
        from moniteur_etb import http

        a, b = http._file("hote", "www.e.leclerc"), http._file("hote", "www.auchan.fr")
        self.assertIs(a, http._file("hote", "www.e.leclerc"))
        self.assertIsNot(a, b)
        self.assertIs(http._file("shopify", "x.fr"), http.CADENCES["shopify"])
        self.assertIsNone(http._file(None, "x.fr"))


class TestFileEtPause(unittest.TestCase):
    def test_requete_en_file_abandonne_si_le_site_bloque(self):
        from moniteur_etb import http

        http.PAUSES.vider()
        http.regler_ecart("bloque.test", 0.01)
        http.PAUSES.echec("bloque.test")
        with mock.patch("moniteur_etb.http.urlopen") as ouvrir, self.assertRaises(http.ErreurVerification):
            http.telecharger("https://bloque.test/page", cadence="hote")
        ouvrir.assert_not_called()
        http.PAUSES.vider()

    def test_site_injoignable_mis_en_pause_des_le_premier_echec(self):
        """Une enseigne à file propre qui ne répond pas est mise en pause tout de
        suite : pas de 2e essai qui repasserait derrière les requêtes en attente."""
        from urllib.error import URLError

        from moniteur_etb import http

        http.PAUSES.vider()
        http.regler_ecart("injoignable.test", 0.01)
        with mock.patch("moniteur_etb.http.urlopen", side_effect=URLError("refusé")) as ouvrir:
            with self.assertRaises(http.ErreurVerification):
                http.telecharger("https://injoignable.test/a", cadence="hote")
            self.assertEqual(ouvrir.call_count, 1)
            self.assertGreater(http.PAUSES.restant("injoignable.test"), 0)
        http.PAUSES.vider()

    def test_attente_interrompue_quand_le_site_passe_en_pause(self):
        import threading

        from moniteur_etb import http

        http.PAUSES.vider()
        c = http.Cadence(intervalle=30.0, minimum=30.0, maximum=30.0)
        self.assertTrue(c.attendre("lent.test"))  # 1re requête : tout de suite
        threading.Timer(0.2, lambda: http.PAUSES.echec("lent.test")).start()
        debut = time.monotonic()
        self.assertFalse(c.attendre("lent.test"))  # la 2e aurait attendu 30 s
        self.assertLess(time.monotonic() - debut, 2.0)
        http.PAUSES.vider()


class TestDecouvertesEtalees(unittest.TestCase):
    def test_trois_par_cycle(self):
        from moniteur_etb import surveillance as surv

        # Découvertes faites il y a une heure : toutes dues (horloge monotone, indépendante de l'uptime).
        il_y_a_une_heure = time.monotonic() - 3600
        boutiques = [Boutique(nom=f"B{i}", url=f"https://b{i}.fr", derniere_decouverte=il_y_a_une_heure) for i in range(7)]
        s = Surveillance(Reglages(), COLLECTION, [], boutiques, FauxDiscord(), {})
        appels = []

        def faux_analyser(b, collection, langues, decouvrir):
            appels.append(decouvrir)
            return Analyse(offres=[], autres=[])

        with mock.patch.object(surv, "analyser", faux_analyser), ThreadPoolExecutor(max_workers=2) as ex:
            s.verifier_tout(ex)
        self.assertEqual(sum(appels), surv.MAX_DECOUVERTES_PAR_CYCLE)
        self.assertEqual(len(appels), 7)


class TestCycleNonBloquant(unittest.TestCase):
    def test_verification_lente_recoltee_plus_tard(self):
        import threading

        from moniteur_etb import surveillance as surv

        lente, rapide = Boutique(nom="Lente", url="https://lente.fr"), Boutique(nom="Rapide", url="https://rapide.fr")
        s = Surveillance(Reglages(), COLLECTION, [], [lente, rapide], FauxDiscord(), {})
        feu = threading.Event()

        def faux_analyser(b, collection, langues, decouvrir):
            if b is lente:
                feu.wait(5)
            return Analyse(offres=[offre(url=f"{b.url}/products/etb")], autres=[])

        with mock.patch.object(surv, "analyser", faux_analyser), ThreadPoolExecutor(max_workers=4) as ex:
            offres, _ = s.verifier_tout(ex, attente=0.5)
            self.assertEqual([o.url for o in offres], ["https://rapide.fr/products/etb"])
            self.assertEqual(len(s._en_cours), 1)  # la lente continue en arrière-plan
            feu.set()
            offres, _ = s.verifier_tout(ex, attente=5)
        self.assertIn("https://lente.fr/products/etb", [o.url for o in offres])
        self.assertEqual(s._en_cours, {})
        self.assertTrue(s.tour_complet)

    def test_premier_cycle_borne_et_fiche_tardive_pas_nouvelle(self):
        import threading

        from moniteur_etb import surveillance as surv

        lente, rapide = Boutique(nom="Lente", url="https://lente.fr"), Boutique(nom="Rapide", url="https://rapide.fr")
        discord = FauxDiscord()
        s = Surveillance(Reglages(), COLLECTION, [], [lente, rapide], discord, {})
        feu = threading.Event()

        def faux_analyser(b, collection, langues, decouvrir):
            if b is lente:
                feu.wait(5)
            return Analyse(offres=[offre(url=f"{b.url}/products/etb", dispo=True)], autres=[])

        with mock.patch.object(surv, "analyser", faux_analyser), \
                mock.patch.object(surv, "PREMIER_CYCLE_MAX_S", 0.3), ThreadPoolExecutor(max_workers=4) as ex:
            debut = time.monotonic()
            s.cycle(ex)
            self.assertLess(time.monotonic() - debut, 3)  # n'attend pas la boutique lente
            self.assertFalse(s.tour_complet)
            feu.set()
            time.sleep(0.1)
            s.cycle(ex)
        self.assertTrue(s.tour_complet)
        self.assertEqual(len(discord.messages), 2)
        # La fiche de la boutique lente, récoltée au 2e cycle d'un premier lancement,
        # n'est pas annoncée comme « nouvelle fiche ».
        self.assertIn("Retour en stock", str(discord.messages[-1]))
        self.assertNotIn("Nouvelle", str(discord.messages[-1]))


class TestFicheMenagee(unittest.TestCase):
    def test_intervalle_produit(self):
        from moniteur_etb.pages import Produit

        p = Produit.depuis_dict({"nom": "UPC 30 ans", "url": "https://www.e.leclerc/fp/x-0196214155336",
                                 "intervalle_secondes": 120}, 0)
        self.assertTrue(p.verification_due())
        p.derniere_verification = time.monotonic()
        self.assertFalse(p.verification_due())
        p.derniere_verification -= 120
        self.assertTrue(p.verification_due())


class TestDiscordPaquets(unittest.TestCase):
    def test_paquets_de_dix(self):
        from moniteur_etb.discord import Discord

        d = Discord("https://discord.test/webhook", mention="@everyone")
        envoyes = []
        with mock.patch.object(Discord, "poster", side_effect=lambda charge, salon="": envoyes.append(charge) or True):
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

        def poster(charge, salon=""):
            envoyes.append(charge)
            d.dernier_code = 400 if any("thumbnail" in e for e in charge["embeds"]) else 204
            return d.dernier_code == 204

        with mock.patch.object(Discord, "poster", side_effect=poster):
            resultats = d.embeds("", [{"title": "ETB", "thumbnail": {"url": "https://x/y.jpg"}}])
        self.assertEqual(resultats, [True])
        self.assertEqual(len(envoyes), 2)
        self.assertNotIn("thumbnail", envoyes[1]["embeds"][0])



class TestSalonsDiscord(unittest.TestCase):
    def test_un_salon_par_type_d_alerte(self):
        from moniteur_etb.discord import salon_offre

        self.assertEqual(salon_offre(offre("upc-journee")), "upc")
        self.assertEqual(salon_offre(offre("etb")), "etb")
        self.assertEqual(salon_offre(offre("bundle")), "autres")
        en_magasin = offre("upc-soiree")
        en_magasin.source = "magasin"
        self.assertEqual(salon_offre(en_magasin), "magasins")

    def test_alertes_reparties_par_salon(self):
        etb = offre("etb", url="https://shop.fr/products/etb")
        upc = offre("upc-journee", url="https://shop.fr/products/upc")
        discord = FauxDiscord()
        s = Surveillance(Reglages(), COLLECTION, [], [], discord, {})
        s.etat = {etb.cle: {}, upc.cle: {}}
        s._envoyer_alertes([(etb, False), (upc, False)], "2026-11-05T10:00:00+00:00")
        self.assertEqual(discord.salons, ["upc", "etb"])
        self.assertIn("Ultra-Premium", discord.messages[0][0])

    def test_webhook_de_salon_absent_ou_invalide(self):
        from moniteur_etb.discord import Discord

        d = Discord("https://discord.test/defaut", salons={"upc": "https://discord.test/upc", "etb": ""})
        self.assertEqual(d.url("upc"), "https://discord.test/upc")
        self.assertEqual(d.url("etb"), "https://discord.test/defaut")  # pas de webhook propre
        self.assertEqual(d.url("journal"), "https://discord.test/defaut")
        appels = []

        def faux_poster(url, charge):
            appels.append(url)
            d.dernier_code = 404 if url.endswith("/upc") else 204
            return d.dernier_code == 204

        with mock.patch.object(d, "_poster", side_effect=faux_poster):
            self.assertTrue(d.texte("UPC !", salon="upc"))  # webhook supprimé : repli sur le salon par défaut
        self.assertEqual(appels, ["https://discord.test/upc", "https://discord.test/defaut"])

    def test_reglages_salons(self):
        with mock.patch.dict(os.environ, {"DISCORD_WEBHOOK_UPC": " https://discord.test/upc ", "DISCORD_WEBHOOK_ETB": ""}):
            r = Reglages.depuis_env()
        self.assertEqual(r.discord_salons, {"upc": "https://discord.test/upc"})


if __name__ == "__main__":
    unittest.main()
