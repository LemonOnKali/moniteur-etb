import os
import unittest
from unittest import mock

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


class TestFicheAVenir(unittest.TestCase):
    def test_404_attendu(self):
        from unittest import mock

        from moniteur_etb.http import ErreurHTTP
        from moniteur_etb.pages import Produit, verifier

        p = Produit(nom="UPC Journée 30 ans", url="https://www.e.leclerc/fp/upc-0196214155336", type="texte", a_venir=True)
        with mock.patch("moniteur_etb.pages.telecharger_page", side_effect=ErreurHTTP(404, "Not Found")):
            r = verifier(p)
            self.assertEqual((r.dispo, r.detail), (False, "fiche pas encore en ligne"))
            p.a_venir = False
            self.assertIsNone(verifier(p).dispo)  # sans a_venir, un 404 reste une erreur


class TestPasDePreuvePasDAlerte(unittest.TestCase):
    def test_page_sans_donnees(self):
        from moniteur_etb.http import ErreurVerification
        from moniteur_etb.pages import Produit, lire_page_texte

        page = "<html><title>Coffret</title>" + "<p>Un très beau coffret Pokémon.</p>" * 200 + "</html>"
        with self.assertRaises(ErreurVerification):
            lire_page_texte(Produit(nom="Coffret 30 ans", url="https://e.fr/fp/x-0196214147102"), page)
        # Avec des mots de rupture choisis pour l'enseigne, l'absence de rupture vaut « en stock ».
        p = Produit.depuis_dict({"nom": "Coffret", "url": "https://u.fr/p/1", "mots_rupture": ["bientôt disponible"]}, 0)
        self.assertTrue(lire_page_texte(p, page).dispo)

    def test_redirection_vers_le_nom_canonique(self):
        from moniteur_etb.http import redirection_suspecte

        self.assertFalse(redirection_suspecte(
            "https://www.e.leclerc/fp/pokemon-coffret-journee-pokemon-2026-0196214139718",
            "https://www.e.leclerc/fp/pokemon-coffret-pokemon-day-26-3b-carte-exclu-0196214139718"))
        self.assertTrue(redirection_suspecte(
            "https://www.joueclub.fr/pokemon/coffret-0196214144835.html", "https://www.joueclub.fr/nos-heros/pokemon.html"))


class TestFichiersPC(unittest.TestCase):
    def test_salons_avec_bom_du_bloc_notes(self):
        """Bloc-notes Windows : fichier enregistré avec BOM, lignes CRLF, espaces."""
        import tempfile
        from pathlib import Path

        from moniteur_etb import cli

        with tempfile.TemporaryDirectory() as d, mock.patch.object(cli, "RACINE", Path(d)), \
                mock.patch.dict(os.environ, {}, clear=False), mock.patch("os.chdir"):
            for cle in [k for k in os.environ if k.startswith("DISCORD_") or k.startswith("FICHIER_")]:
                os.environ.pop(cle)
            Path(d, "discord-webhook.txt").write_text("https://discord.com/api/webhooks/1/defaut\n", encoding="utf-8")
            Path(d, "discord-salons.txt").write_bytes(
                "\ufeffupc = https://discord.com/api/webhooks/2/upc\r\n# commentaire\r\njournal=https://discord.com/api/webhooks/3/j\r\n"
                .encode("utf-8"))
            cli.preparer_pc(tout=False)
            self.assertEqual(os.environ["DISCORD_WEBHOOK_UPC"], "https://discord.com/api/webhooks/2/upc")
            self.assertEqual(os.environ["DISCORD_WEBHOOK_JOURNAL"], "https://discord.com/api/webhooks/3/j")
            self.assertEqual(os.environ["DISCORD_WEBHOOK"], "https://discord.com/api/webhooks/1/defaut")


class TestLancementPC(unittest.TestCase):
    def test_preparer_pc(self):
        import io
        import os
        import tempfile
        from pathlib import Path
        from unittest import mock

        from moniteur_etb import cli

        with tempfile.TemporaryDirectory() as dossier, mock.patch.object(cli, "RACINE", Path(dossier)), \
                mock.patch.dict(os.environ, {}, clear=True), mock.patch("sys.stdin", io.StringIO("")):
            Path(dossier, "discord-webhook.txt").write_text("https://discord.com/api/webhooks/1/abc\n", encoding="utf-8")
            Path(dossier, "discord-mention.txt").write_text("@everyone\n", encoding="utf-8")
            cli.preparer_pc(tout=False)
            self.assertEqual(os.environ["FICHIER_PRODUITS"], "produits-pc.json")
            self.assertEqual(os.environ["FICHIER_BOUTIQUES"], "boutiques-pc.json")
            self.assertEqual(os.environ["DISCORD_WEBHOOK"], "https://discord.com/api/webhooks/1/abc")
            self.assertEqual(os.environ["DISCORD_MENTION"], "@everyone")
            self.assertEqual(os.environ["GITHUB_EVENT_NAME"], "workflow_dispatch")
            os.environ.clear()
            cli.preparer_pc(tout=True)
            self.assertEqual(os.environ["FICHIER_PRODUITS"], "produits.json,produits-pc.json")
            os.chdir(cli.Path(__file__).resolve().parent.parent)

    def test_plusieurs_fichiers(self):
        import os

        from moniteur_etb.surveillance import charger_boutiques, charger_produits

        racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        seuls = len(charger_produits(os.path.join(racine, "produits-pc.json")))
        tous = charger_produits(",".join(os.path.join(racine, f) for f in ("produits.json", "produits-pc.json")))
        self.assertGreater(len(tous), seuls)
        self.assertTrue(charger_boutiques(os.path.join(racine, "boutiques-pc.json")))


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
