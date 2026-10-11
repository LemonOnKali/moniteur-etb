"""Surveillance d'une boutique entière (boutiques.json).

Au lieu d'une URL par produit, on interroge le catalogue de la boutique et on
garde toutes les fiches de la gamme 30 ans, quelles qu'elles soient : ETB, UPC,
bundle, mini tins… y compris celles mises en ligne après le lancement.

Deux temps :

- **découverte** (au démarrage puis toutes les DECOUVERTE_MINUTES) : catégories
  « 30 ans » de la boutique + recherche de chaque terme de collection.json ;
- **vérification** (à chaque cycle) : la requête groupée la moins chère qui
  couvre toutes les fiches trouvées (une catégorie Shopify, la liste d'ids
  WooCommerce, une ou deux recherches PrestaShop…).

Chaque plateforme renvoie la disponibilité directement dans ces réponses
groupées : une boutique coûte en général 1 à 3 requêtes par cycle.
"""

from __future__ import annotations

import html
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import quote, urlsplit, urlunsplit

from .collection import Classement, Collection, langue, langue_acceptee
from .http import ACCEPT_HTML, ErreurHTTP, ErreurVerification, en_pause, telecharger, telecharger_json
from .modeles import Fiche, Offre, cle_url
from .pages import (
    Produit,
    verifier_texte,
    api_woocommerce,
    lire_produit_prestashop,
    lire_produit_woocommerce,
    url_absolue,
    verifier_prestashop,
)
from .texte import lire_prix, mots

PLATEFORMES = {"shopify", "woocommerce", "prestashop", "auto"}
MAX_FICHES_PAGE = 20  # PrestaShop sans recherche JSON : fiches lues une à une, au plus
# Délai entre deux recherches d'une même boutique pendant la découverte :
# la recherche Shopify (search/suggest.json) répond 429 au-delà de ~5 requêtes en rafale.
ESPACEMENT_S = {"shopify": 2.5, "woocommerce": 0.5, "prestashop": 0.5}
_attendre = time.sleep  # remplacé dans les tests
RECHERCHES_AVEC_CATEGORIE = 3  # Shopify : la catégorie couvre l'essentiel, peu de recherches en plus
# Catégories Shopify à ignorer même si elles parlent de 30 ans (pas des produits scellés).
_RE_CATEGORIE_HORS_SUJET = re.compile(r"\b(l?unites?|singles?|gradees?|graded|psa|cartes rares|slab)\b")


@dataclass
class Boutique:
    nom: str
    url: str
    plateforme: str = "auto"
    categories: list[str] = field(default_factory=list)  # handles Shopify imposés
    recherches: list[str] | None = None  # termes ; None = ceux de collection.json
    prix_max: float | None = None
    actif: bool = True

    # État d'exécution (non configurable)
    detectee: str | None = None
    sources: dict[str, set[str]] = field(default_factory=dict)  # source → clés des fiches 30 ans
    refs: dict[str, str] = field(default_factory=dict)  # clé → handle / id WooCommerce / URL de fiche
    categories_trouvees: list[str] = field(default_factory=list)
    api: str | None = None  # gabarit d'URL d'API qui a fonctionné ({p} = paramètres, {q} = terme)
    presta_html: bool = False  # PrestaShop sans recherche JSON : fiches lues une à une
    note: str = ""  # remarque de détection affichée par --diagnostic
    derniere_decouverte: float | None = None
    derniere_erreur: str = ""

    @classmethod
    def depuis_dict(cls, brut: dict[str, Any], index: int) -> "Boutique":
        if not isinstance(brut, dict):
            raise ValueError(f"boutique n°{index + 1} : doit être un objet JSON")
        nom = str(brut.get("nom", "")).strip()
        url = str(brut.get("url", "")).strip().rstrip("/")
        if not nom:
            raise ValueError(f"boutique n°{index + 1} : champ 'nom' manquant")
        if not url.startswith(("http://", "https://")):
            raise ValueError(f"boutique '{nom}' : champ 'url' invalide ({url!r})")
        plateforme = str(brut.get("plateforme", "auto")).strip().lower() or "auto"
        if plateforme not in PLATEFORMES:
            raise ValueError(f"boutique '{nom}' : plateforme {plateforme!r} inconnue ({', '.join(sorted(PLATEFORMES))})")
        categories = brut.get("categories") or []
        recherches = brut.get("recherches")
        if not isinstance(categories, list) or (recherches is not None and not isinstance(recherches, list)):
            raise ValueError(f"boutique '{nom}' : 'categories' et 'recherches' doivent être des listes")
        prix_max = brut.get("prix_max")
        try:
            prix_max = float(prix_max) if prix_max is not None else None
        except (TypeError, ValueError):
            raise ValueError(f"boutique '{nom}' : 'prix_max' doit être un nombre") from None
        return cls(
            nom=nom,
            url=url,
            plateforme=plateforme,
            categories=[str(c).strip() for c in categories if str(c).strip()],
            recherches=[str(r) for r in recherches] if recherches is not None else None,
            prix_max=prix_max,
            actif=bool(brut.get("actif", True)),
        )

    @property
    def racine(self) -> str:
        parts = urlsplit(self.url)
        return urlunsplit((parts.scheme, parts.netloc, "", "", ""))

    def decouverte_due(self, intervalle_s: float) -> bool:
        return self.derniere_decouverte is None or time.monotonic() - self.derniere_decouverte >= intervalle_s


# --------------------------------------------------------------------------- #
# Lecture des réponses de chaque plateforme
# --------------------------------------------------------------------------- #

FiltreVariante = Callable[[str], bool]


def _tout(_titre: str) -> bool:
    return True


def _resumer_variantes(
    variantes: list[tuple[str, bool, float | None]], filtre: FiltreVariante
) -> tuple[bool, float | None, str]:
    """(dispo, prix, détail) à partir de (titre, disponible, prix), sans les langues refusées."""
    gardees = [v for v in variantes if v[0] in ("", "Default Title") or filtre(v[0])]
    dispos = [v for v in gardees if v[1]]
    prix = [v[2] for v in (dispos or gardees) if v[2]]
    titres = [v[0] for v in dispos if v[0] not in ("", "Default Title")]
    detail = "variante(s) : " + ", ".join(titres[:5]) if titres and len(gardees) > 1 else ""
    return bool(dispos), (min(prix) if prix else None), detail


def fiche_shopify(produit: dict[str, Any], racine: str, filtre: FiltreVariante = _tout,
                  dans_categorie: bool = False) -> Fiche | None:
    """Produit Shopify de /products.json, d'une catégorie ou de /search/suggest.json (prix décimaux)."""
    handle = produit.get("handle")
    titre = str(produit.get("title") or "")
    if not handle or not titre:
        return None
    variantes = [
        (str(v.get("title") or ""), bool(v.get("available")), lire_prix(v.get("price")))
        for v in produit.get("variants") or [] if isinstance(v, dict)
    ]
    if variantes:
        dispo, prix, detail = _resumer_variantes(variantes, filtre)
    else:
        dispo, prix, detail = bool(produit.get("available")), lire_prix(produit.get("price")), ""
    image: Any = produit.get("image")
    if isinstance(image, dict):
        image = image.get("src") or image.get("url")
    if not image and produit.get("images"):
        premiere = produit["images"][0]
        image = premiere.get("src") if isinstance(premiere, dict) else premiere
    if not image and isinstance(produit.get("featured_image"), dict):
        image = produit["featured_image"].get("url")
    url = f"{racine}/products/{handle}"
    return Fiche(
        cle=cle_url(url), url=url, titre=html.unescape(titre), dispo=dispo, prix=prix,
        image=url_absolue(image, racine) if isinstance(image, str) else None,
        detail=detail, ref=str(handle), dans_categorie=dans_categorie,
    )


def fiche_woocommerce(produit: dict[str, Any]) -> Fiche | None:
    url = produit.get("permalink")
    if not url or produit.get("id") is None:
        return None
    try:
        r = lire_produit_woocommerce(produit)
    except ErreurVerification:
        return None
    return Fiche(
        cle=cle_url(url), url=url, titre=r.titre or "", dispo=bool(r.dispo), prix=r.prix,
        image=r.image, quantite=r.quantite, detail=r.detail, ref=str(produit["id"]),
    )


def fiche_prestashop(produit: dict[str, Any], racine: str) -> Fiche | None:
    url = url_absolue(produit.get("url") or produit.get("link") or produit.get("canonical_url"), racine)
    if not url:
        return None
    try:
        r = lire_produit_prestashop(produit)
    except ErreurVerification:
        return None
    return Fiche(
        cle=cle_url(url), url=url, titre=html.unescape(r.titre or ""), dispo=bool(r.dispo),
        prix=r.prix, image=r.image, quantite=r.quantite, detail=r.detail, ref=url,
    )


# --------------------------------------------------------------------------- #
# Shopify
# --------------------------------------------------------------------------- #


def _shopify_categories(b: Boutique, collection: Collection, langues: frozenset[str]) -> list[str]:
    """Catégories (collections) Shopify dont le titre ou le handle évoque la gamme.

    Sont écartées celles de cartes à l'unité, de cartes gradées ou d'une langue
    refusée (« 30-ans-pokemon-japonais »).
    """
    trouvees: list[str] = []
    for page in range(1, 5):
        donnees = telecharger_json(f"{b.racine}/collections.json?limit=250&page={page}")
        cols = donnees.get("collections") if isinstance(donnees, dict) else None
        if not isinstance(cols, list):
            raise ErreurVerification("collections.json illisible")
        for c in cols:
            handle = str(c.get("handle") or "")
            texte = mots(f"{handle} {c.get('title') or ''}")
            if not handle or not collection.fait_partie(texte):
                continue
            if _RE_CATEGORIE_HORS_SUJET.search(texte) or not langue_acceptee(langue(texte), langues):
                continue
            trouvees.append(handle)
        if len(cols) < 250:
            break
    return trouvees


def _shopify_source(b: Boutique, source: str, filtre: FiltreVariante) -> list[Fiche]:
    genre, _, valeur = source.partition(":")
    if genre == "categorie":
        donnees = telecharger_json(f"{b.racine}/collections/{quote(valeur)}/products.json?limit=250")
        produits = donnees.get("products") if isinstance(donnees, dict) else None
        if not isinstance(produits, list):
            raise ErreurVerification(f"catégorie Shopify « {valeur} » illisible")
        return [f for p in produits if isinstance(p, dict) and (f := fiche_shopify(p, b.racine, filtre, True))]
    # Limite propre à la recherche : un 429 ici ne doit pas mettre toute la boutique en pause.
    donnees = telecharger_json(
        f"{b.racine}/search/suggest.json?q={quote(valeur)}&resources[type]=product"
        "&resources[limit]=10&resources[options][unavailable_products]=show",
        pause=False,
    )
    try:
        produits = donnees["resources"]["results"]["products"]
    except (KeyError, TypeError):
        raise ErreurVerification("recherche Shopify (search/suggest.json) illisible") from None
    return [f for p in produits or [] if isinstance(p, dict) and (f := fiche_shopify(p, b.racine, filtre))]


# --------------------------------------------------------------------------- #
# WooCommerce
# --------------------------------------------------------------------------- #


def _woo_requete(b: Boutique, parametres: str) -> list[Fiche]:
    gabarits = [b.api] if b.api else api_woocommerce(b.racine, "{p}")
    erreurs = []
    for gabarit in gabarits:
        try:
            donnees = telecharger_json(gabarit.replace("{p}", parametres))
        except ErreurVerification as err:
            if en_pause(gabarit):
                raise
            erreurs.append(str(err))
            continue
        if isinstance(donnees, list):
            b.api = gabarit
            return [f for p in donnees if isinstance(p, dict) and (f := fiche_woocommerce(p))]
        erreurs.append("réponse inattendue")
    raise ErreurVerification("API Store WooCommerce : " + " | ".join(dict.fromkeys(erreurs)))


# --------------------------------------------------------------------------- #
# PrestaShop
# --------------------------------------------------------------------------- #

_RE_LIEN = re.compile(r"<a\b([^>]*)>(.*?)</a>", re.IGNORECASE | re.DOTALL)
_RE_HREF = re.compile(r'href\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)
_RE_TITLE = re.compile(r'title\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)
_RE_URL_FICHE_PRESTA = re.compile(r"/\d+-[^/?#]+\.html(?:[?#]|$)")  # …/12617-nom-du-produit.html


def _presta_gabarits(b: Boutique) -> list[str]:
    suffixe = "controller=search&s={q}&search_query={q}&resultsPerPage=100&n=100"
    return [f"{b.url}/index.php?{suffixe}", f"{b.url}/recherche?{suffixe}", f"{b.url}/search?{suffixe}"]


def _presta_recherche(b: Boutique, terme: str) -> list[Fiche]:
    """Recherche PrestaShop 1.7+ en JSON (comme le fait la page en AJAX), sinon page HTML."""
    q = quote(terme)
    if b.presta_html and b.api:
        return _presta_html(b, b.api.replace("{q}", q))
    gabarits = [b.api] if b.api else _presta_gabarits(b)
    erreurs: list[str] = []
    for gabarit in gabarits:
        try:
            donnees = telecharger_json(gabarit.replace("{q}", q) + "&ajax=1&from-xhr=1", ajax=True)
        except ErreurVerification as err:
            if en_pause(gabarit):
                raise
            erreurs.append(f"{gabarit.split('?')[0]} : {err}")
            continue
        if isinstance(donnees, dict) and isinstance(donnees.get("products"), list):
            b.api = gabarit
            return [f for p in donnees["products"] if isinstance(p, dict) and (f := fiche_prestashop(p, b.racine))]
        erreurs.append(f"{gabarit.split('?')[0]} : pas de liste « products »")
    for gabarit in gabarits:
        try:
            fiches = _presta_html(b, gabarit.replace("{q}", q))
        except ErreurVerification as err:
            if en_pause(gabarit):
                raise
            erreurs.append(str(err))
            continue
        b.api, b.presta_html = gabarit, True
        b.note = "recherche JSON indisponible (" + " | ".join(dict.fromkeys(erreurs)) + ")"
        return fiches
    raise ErreurVerification("recherche PrestaShop : " + " | ".join(dict.fromkeys(erreurs)))


def _presta_html(b: Boutique, url: str) -> list[Fiche]:
    """Page de résultats HTML : liens des fiches seulement, disponibilité lue ensuite sur chaque fiche.

    Tout lien du site vers une adresse de fiche PrestaShop (« /123-nom.html ») est
    retenu, avec son texte le plus long (lien image + lien titre) : marche avec
    tous les thèmes. Les liens du menu ou des meilleures ventes sont écartés
    ensuite par le classement.
    """
    page = telecharger(url, accept=ACCEPT_HTML).texte()
    if "prestashop" not in page.lower():
        raise ErreurVerification("page de recherche non PrestaShop")
    hote = urlsplit(b.racine).hostname
    titres: dict[str, str] = {}
    for attributs, contenu in _RE_LIEN.findall(page):
        href = _RE_HREF.search(attributs)
        if not href:
            continue
        lien = url_absolue(html.unescape(href.group(1)), b.racine)
        if not lien or urlsplit(lien).hostname != hote or not _RE_URL_FICHE_PRESTA.search(lien):
            continue
        lien = lien.split("#")[0].split("?")[0]
        texte = html.unescape(re.sub(r"<[^>]+>", " ", contenu))
        title = _RE_TITLE.search(attributs)
        texte = " ".join((texte if texte.strip() else html.unescape(title.group(1)) if title else "").split())
        if len(texte) > len(titres.get(lien, "")):
            titres[lien] = texte
    return [
        Fiche(cle=cle_url(lien), url=lien, titre=titre, dispo=False, ref=lien, detail="à vérifier")
        for lien, titre in titres.items()
    ]


def _presta_fiche_page(url: str, titre: str) -> Fiche:
    produit = Produit(nom=titre or url, url=url, type="prestashop")
    try:
        r = verifier_prestashop(produit)
    except ErreurVerification:
        if en_pause(url):
            raise
        r = verifier_texte(produit)  # thème sans données produit : schema.org, mots de rupture…
    return Fiche(
        cle=cle_url(url), url=url, titre=r.titre or titre, dispo=bool(r.dispo), prix=r.prix,
        image=r.image, quantite=r.quantite, detail=r.detail, ref=url,
    )


# --------------------------------------------------------------------------- #
# Détection, découverte et vérification
# --------------------------------------------------------------------------- #


def detecter_plateforme(b: Boutique) -> str:
    """Shopify (products.json), WooCommerce (API Store) ou PrestaShop (recherche)."""
    try:
        donnees = telecharger_json(f"{b.racine}/products.json?limit=1")
        if isinstance(donnees, dict) and isinstance(donnees.get("products"), list):
            return "shopify"
    except ErreurVerification:
        pass
    for essai, nom in ((lambda: _woo_requete(b, "per_page=1"), "woocommerce"), (lambda: _presta_recherche(b, "pokemon"), "prestashop")):
        if en_pause(b.url):
            raise ErreurVerification("site injoignable ou bloqué : plateforme non détectée (nouvel essai plus tard)")
        try:
            essai()
            return nom
        except ErreurVerification:
            b.api, b.presta_html = None, False
    raise ErreurVerification("plateforme non reconnue (ni Shopify, ni WooCommerce, ni PrestaShop) : à mettre dans produits.json")


def couverture(sources: dict[str, set[str]]) -> list[str]:
    """Plus petit ensemble (glouton) de sources couvrant toutes les fiches, catégories d'abord."""
    restant = set().union(*sources.values()) if sources else set()
    choisies: list[str] = []
    while restant:
        meilleure = max(sources, key=lambda s: (len(sources[s] & restant), s.startswith("categorie:"), -len(s)))
        if not sources[meilleure] & restant:
            break
        choisies.append(meilleure)
        restant -= sources[meilleure]
    return choisies


@dataclass
class Analyse:
    offres: list[Offre]
    autres: list[Fiche]  # fiches lues mais hors gamme (affichées par --decouvrir)
    requetes: int = 0
    decouverte: bool = False
    erreurs: list[str] = field(default_factory=list)


def analyser(b: Boutique, collection: Collection, langues: frozenset[str], decouvrir: bool) -> Analyse:
    """Découverte complète ou vérification légère d'une boutique. Ne lève jamais."""
    analyse = Analyse(offres=[], autres=[])
    fiches: dict[str, Fiche] = {}
    trouvees: dict[str, set[str]] = {}  # source → clés lues
    en_echec: set[str] = set()

    def filtre_variante(titre: str) -> bool:
        code = langue(mots(titre))
        return code == "?" or code in langues

    def lire(source: str) -> list[Fiche]:
        genre, _, valeur = source.partition(":")
        if b.detectee == "shopify":
            return _shopify_source(b, source, filtre_variante)
        if b.detectee == "woocommerce":
            return _woo_requete(b, f"search={quote(valeur)}&per_page=100")
        return _presta_recherche(b, valeur)

    def ajouter(f: Fiche) -> None:
        deja = fiches.get(f.cle)
        if deja is None or (f.dans_categorie and not deja.dans_categorie):
            fiches[f.cle] = f

    if b.detectee is None and not decouvrir and b.derniere_decouverte is not None:
        # Plateforme non reconnue au dernier essai : on réessaie à la prochaine découverte.
        analyse.erreurs.append(b.derniere_erreur or "plateforme non reconnue")
        return analyse
    decouvrir = decouvrir or b.derniere_decouverte is None
    analyse.decouverte = decouvrir
    try:
        if b.detectee is None:
            analyse.requetes += 1
            try:
                b.detectee = b.plateforme if b.plateforme != "auto" else detecter_plateforme(b)
            except ErreurVerification:
                b.derniere_decouverte = time.monotonic()
                raise

        sources: list[str] = []
        if decouvrir:
            if b.detectee == "shopify":
                handles = list(b.categories)
                if not handles:
                    analyse.requetes += 1
                    try:
                        handles = _shopify_categories(b, collection, langues)
                    except ErreurVerification as err:
                        analyse.erreurs.append(f"catégories : {err}")
                        handles = b.categories_trouvees
                b.categories_trouvees = handles
                sources += [f"categorie:{h}" for h in handles]
            termes = b.recherches if b.recherches is not None else collection.recherches
            if b.detectee == "shopify" and sources and b.recherches is None:
                termes = termes[:RECHERCHES_AVEC_CATEGORIE]
            sources += [f"recherche:{t}" for t in termes]
        elif b.detectee in ("shopify", "prestashop") and not b.presta_html:
            sources = couverture(b.sources)

        for i, source in enumerate(sources):
            if decouvrir and i and source.startswith("recherche:"):
                _attendre(ESPACEMENT_S.get(b.detectee or "", 0.5))
            analyse.requetes += 1
            try:
                for f in lire(source):
                    ajouter(f)
                    trouvees.setdefault(source, set()).add(f.cle)
            except ErreurVerification as err:
                en_echec.add(source)
                if isinstance(err, ErreurHTTP) and err.code == 429 and source.startswith("recherche:"):
                    # La boutique limite ses recherches : on garde les fiches déjà connues
                    # et on reprendra à la prochaine découverte, sans bloquer la boutique.
                    en_echec.update(sources[i + 1:])
                    b.note = f"recherche limitée par la boutique (429) : {len(sources) - i} recherche(s) reportée(s)"
                    break
                analyse.erreurs.append(f"{source.partition(':')[2]} : {err}")
                if en_pause(b.url) and sources[i + 1:]:
                    en_echec.update(sources[i + 1:])
                    analyse.erreurs.append(f"{len(sources) - i - 1} autre(s) requête(s) reportée(s)")
                    break

        if not decouvrir and b.detectee == "woocommerce" and b.refs:
            ids = sorted(set(b.refs.values()))
            for i in range(0, len(ids), 100):
                analyse.requetes += 1
                try:
                    for f in _woo_requete(b, f"include={','.join(ids[i:i + 100])}&per_page=100"):
                        ajouter(f)
                except ErreurVerification as err:
                    analyse.erreurs.append(str(err))
    except ErreurVerification as err:
        analyse.erreurs.append(str(err))
    except Exception as err:  # garde-fou : un bug sur une boutique ne stoppe pas les autres
        analyse.erreurs.append(f"erreur inattendue {type(err).__name__} : {err}")

    # PrestaShop sans recherche JSON : la disponibilité se lit sur chaque fiche.
    if b.presta_html:
        a_lire = {f.cle: f for f in fiches.values() if f.detail == "à vérifier"}
        if not decouvrir:
            a_lire.update({cle: Fiche(cle=cle, url=url, titre="", dispo=False, ref=url) for cle, url in b.refs.items()})
        for cle, f in list(a_lire.items())[:MAX_FICHES_PAGE]:
            if decouvrir and collection.classer(f.titre, exiger_marqueur=True) is None:
                fiches.pop(cle, None)
                analyse.autres.append(f)
                continue
            analyse.requetes += 1
            try:
                lue = _presta_fiche_page(f.url, f.titre)
            except ErreurVerification as err:
                analyse.erreurs.append(f"{f.url} : {err}")
                fiches.pop(cle, None)
                continue
            lue.dans_categorie = not decouvrir  # déjà retenue lors de la découverte
            fiches[cle] = lue

    gardees: set[str] = set()
    for f in fiches.values():
        classement = collection.classer(f.titre, exiger_marqueur=not f.dans_categorie)
        if (
            classement is None
            or not langue_acceptee(classement.langue, langues)
            or not classement.item.prix_plausible(f.prix)
        ):
            analyse.autres.append(f)
            continue
        gardees.add(f.cle)
        b.refs[f.cle] = f.ref
        analyse.offres.append(_offre(b, f, classement))

    if decouvrir and (trouvees or not en_echec):
        nouvelles = {s: cles & gardees for s, cles in trouvees.items() if cles & gardees}
        # Une recherche en échec garde ses fiches de la fois précédente : pas de trou
        # de surveillance sur une erreur passagère.
        for s in en_echec & b.sources.keys():
            nouvelles[s] = b.sources[s]
        b.sources = nouvelles
        b.derniere_decouverte = time.monotonic()

    b.derniere_erreur = " | ".join(analyse.erreurs)
    return analyse


def _offre(b: Boutique, f: Fiche, classement: Classement) -> Offre:
    return Offre(
        cle=f.cle,
        boutique=b.nom,
        titre=f.titre,
        url=f.url,
        item=classement.item,
        langue=classement.langue,
        dispo=f.dispo,
        prix=f.prix,
        prix_max=b.prix_max if b.prix_max is not None else classement.item.prix_max,
        image=f.image,
        quantite=f.quantite,
        detail=f.detail,
        source=b.detectee or b.plateforme,
    )
