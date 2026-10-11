"""Vérification d'une fiche produit précise (produits.json).

Types : shopify, woocommerce, prestashop, texte, auto (essaie les quatre).
Sert aux enseignes sans catalogue exploitable (Amazon, JouéClub, Carrefour…)
et aux fiches qu'on veut forcer à la main.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .http import ErreurVerification, telecharger_json, telecharger_page
from .modeles import Resultat
from .texte import lire_prix, normaliser, texte_visible

MOTS_RUPTURE_DEFAUT = ["rupture", "épuisé", "indisponible", "sold out", "plus disponible", "me prévenir"]
TYPES_VALIDES = {"shopify", "woocommerce", "prestashop", "texte", "auto"}

# Signes d'une page anti-robot (captcha, blocage) : on préfère une erreur claire
# à une fausse détection.
MOTS_ANTI_ROBOT = [
    "captcha", "automated access", "are you a human", "access denied", "êtes-vous un robot",
    "verify you are human", "pardon our interruption", "think you were a bot", "just a moment",
]


@dataclass
class Produit:
    nom: str
    url: str
    type: str = "auto"
    boutique: str = ""
    item: str | None = None  # id d'item de collection.json ; sinon déduit du nom
    mots_rupture: list[str] = field(default_factory=lambda: list(MOTS_RUPTURE_DEFAUT))
    mots_stock: list[str] = field(default_factory=list)
    regex_stock: str | None = None  # expression régulière sur le HTML brut → en stock si elle matche
    regex_rupture: str | None = None  # expression régulière sur le HTML brut → rupture si elle matche
    variante: str | None = None  # ne considérer que les variantes dont le titre contient ce texte
    prix_max: float | None = None  # au-delà, on ne signale pas (surcharge l'item et PRIX_MAX)
    mots_explicites: bool = False  # mots_rupture / mots_stock fournis dans produits.json
    actif: bool = True
    type_detecte: str | None = None  # renseigné en mode "auto"

    @classmethod
    def depuis_dict(cls, brut: dict[str, Any], index: int) -> "Produit":
        if not isinstance(brut, dict):
            raise ValueError(f"produit n°{index + 1} : doit être un objet JSON")
        nom = str(brut.get("nom", "")).strip()
        url = str(brut.get("url", "")).strip()
        if not nom:
            raise ValueError(f"produit n°{index + 1} : champ 'nom' manquant")
        if not url.startswith(("http://", "https://")):
            raise ValueError(f"produit '{nom}' : champ 'url' invalide ({url!r})")
        type_ = str(brut.get("type", "auto")).strip().lower() or "auto"
        if type_ not in TYPES_VALIDES:
            raise ValueError(
                f"produit '{nom}' : type {type_!r} inconnu (attendu : {', '.join(sorted(TYPES_VALIDES))})"
            )
        mots_rupture = brut.get("mots_rupture") or MOTS_RUPTURE_DEFAUT
        mots_stock = brut.get("mots_stock") or []
        if not isinstance(mots_rupture, list) or not isinstance(mots_stock, list):
            raise ValueError(f"produit '{nom}' : 'mots_rupture' et 'mots_stock' doivent être des listes")
        regex_stock = brut.get("regex_stock") or None
        regex_rupture = brut.get("regex_rupture") or None
        for nom_champ, motif in (("regex_stock", regex_stock), ("regex_rupture", regex_rupture)):
            if motif is not None:
                try:
                    re.compile(str(motif), re.IGNORECASE | re.DOTALL)
                except re.error as err:
                    raise ValueError(f"produit '{nom}' : '{nom_champ}' invalide ({err})")
        prix_max = brut.get("prix_max")
        if prix_max is not None:
            try:
                prix_max = float(prix_max)
            except (TypeError, ValueError):
                raise ValueError(f"produit '{nom}' : 'prix_max' doit être un nombre")
        variante = brut.get("variante")
        return cls(
            nom=nom,
            url=url,
            type=type_,
            boutique=str(brut.get("boutique") or "").strip() or domaine(url),
            item=str(brut["item"]).strip() if brut.get("item") else None,
            mots_rupture=[str(m) for m in mots_rupture],
            mots_stock=[str(m) for m in mots_stock],
            variante=str(variante).strip() if variante else None,
            prix_max=prix_max,
            regex_stock=str(regex_stock) if regex_stock else None,
            regex_rupture=str(regex_rupture) if regex_rupture else None,
            mots_explicites=bool(brut.get("mots_rupture") or brut.get("mots_stock")),
            actif=bool(brut.get("actif", True)),
        )


def domaine(url: str) -> str:
    return (urlsplit(url).hostname or url).removeprefix("www.")


def _sans_query(url: str) -> tuple[str, str, str]:
    parts = urlsplit(url)
    return parts.scheme, parts.netloc, parts.path.rstrip("/")


def url_absolue(lien: str | None, base: str) -> str | None:
    if not lien:
        return None
    lien = str(lien).strip()
    if lien.startswith("//"):
        return "https:" + lien
    if lien.startswith("/"):
        parts = urlsplit(base)
        return urlunsplit((parts.scheme, parts.netloc, lien, "", ""))
    return lien if lien.startswith("http") else None


# --------------------------------------------------------------------------- #
# Shopify / WooCommerce / PrestaShop
# --------------------------------------------------------------------------- #


def url_shopify_js(url: str) -> str:
    scheme, netloc, path = _sans_query(url)
    if path.endswith(".json"):
        path = path[:-5]
    if not path.endswith(".js"):
        path += ".js"
    return urlunsplit((scheme, netloc, path, "", ""))


def lire_produit_shopify_js(donnees: Any, variante: str | None = None) -> Resultat:
    """Interprète la réponse de /products/<handle>.js (prix en centimes)."""
    if not isinstance(donnees, dict) or "variants" not in donnees:
        raise ErreurVerification("format Shopify inattendu (pas de champ 'variants')")
    variantes = donnees.get("variants") or []
    if variante:
        filtre = normaliser(variante)
        variantes = [v for v in variantes if filtre in normaliser(str(v.get("title", "")))]
        if not variantes:
            raise ErreurVerification(f"aucune variante ne contient « {variante} »")
    dispos = [v for v in variantes if v.get("available")]
    dispo = bool(dispos) if variante else (bool(dispos) or bool(donnees.get("available")))
    candidats = dispos or variantes
    prix_liste = [p for p in (lire_prix(v.get("price"), centimes=True) for v in candidats) if p]
    prix = min(prix_liste) if prix_liste else lire_prix(donnees.get("price"), centimes=True)
    detail = ""
    if dispos and len(variantes) > 1:
        titres = [str(v.get("title", "")) for v in dispos if v.get("title") not in (None, "", "Default Title")]
        if titres:
            detail = "variante(s) : " + ", ".join(titres[:5])
    image = donnees.get("featured_image") or next(iter(donnees.get("images") or []), None)
    return Resultat(
        dispo=dispo,
        prix=prix,
        detail=detail,
        source="shopify",
        image=url_absolue(image, "https://cdn.shopify.com") if isinstance(image, str) else None,
        titre=str(donnees.get("title") or "") or None,
    )


def verifier_shopify(produit: Produit) -> Resultat:
    return lire_produit_shopify_js(telecharger_json(url_shopify_js(produit.url)), produit.variante)


def lire_produit_woocommerce(fiche: Any) -> Resultat:
    """Interprète un produit de l'API Store WooCommerce (/wp-json/wc/store/v1/products)."""
    if not isinstance(fiche, dict) or "is_in_stock" not in fiche:
        raise ErreurVerification("format WooCommerce inattendu (pas de champ 'is_in_stock')")
    dispo = bool(fiche.get("is_in_stock")) and bool(fiche.get("is_purchasable", True))
    prix_info = fiche.get("prices") or {}
    prix = None
    try:
        brut = prix_info.get("price")
        unite = int(prix_info.get("currency_minor_unit", 2))
        if brut not in (None, ""):
            prix = lire_prix(int(brut) / (10**unite))
    except (TypeError, ValueError):
        prix = None
    images = fiche.get("images") or []
    image = None
    if images and isinstance(images[0], dict):
        image = images[0].get("thumbnail") or images[0].get("src")
    restant = fiche.get("low_stock_remaining")
    stock = fiche.get("stock_availability")
    stock = stock.get("text") if isinstance(stock, dict) else None
    return Resultat(
        dispo=dispo,
        prix=prix,
        detail=html.unescape(re.sub(r"<[^>]+>", "", str(stock))) if stock else "",
        source="woocommerce",
        image=image,
        quantite=int(restant) if isinstance(restant, int) else None,
        titre=html.unescape(str(fiche.get("name") or "")) or None,
    )


def api_woocommerce(base: str, parametres: str) -> list[str]:
    """URLs candidates de l'API Store (permaliens normaux, ancienne version, sans réécriture)."""
    scheme, netloc, _ = _sans_query(base)
    racine = urlunsplit((scheme, netloc, "", "", ""))
    return [
        f"{racine}/wp-json/wc/store/v1/products?{parametres}",
        f"{racine}/wp-json/wc/store/products?{parametres}",
        f"{racine}/?rest_route=/wc/store/v1/products&{parametres}",
    ]


def verifier_woocommerce(produit: Produit) -> Resultat:
    _, _, path = _sans_query(produit.url)
    slug = path.rsplit("/", 1)[-1]
    if not slug:
        raise ErreurVerification("impossible de déduire le slug WooCommerce depuis l'URL")
    erreurs = []
    for api in api_woocommerce(produit.url, f"slug={slug}"):
        try:
            donnees = telecharger_json(api)
        except ErreurVerification as err:
            erreurs.append(str(err))
            continue
        if isinstance(donnees, list) and donnees:
            return lire_produit_woocommerce(donnees[0])
        erreurs.append("produit introuvable")
    raise ErreurVerification("API Store WooCommerce : " + " | ".join(dict.fromkeys(erreurs)))


_RE_PRESTASHOP = re.compile(r'data-product\s*=\s*"(\{[^"]*)"')  # objet JSON échappé (&quot;)


def lire_produit_prestashop(donnees: Any) -> Resultat:
    """Interprète un produit PrestaShop 1.7+ (data-product d'une fiche ou résultat de recherche)."""
    if not isinstance(donnees, dict):
        raise ErreurVerification("données PrestaShop inattendues")
    disponibilite = str(donnees.get("availability") or "")
    quantite = donnees.get("quantity")
    panier = donnees.get("add_to_cart_url")
    if disponibilite:
        dispo = disponibilite != "unavailable"
    elif isinstance(quantite, (int, float)):
        dispo = quantite > 0 or bool(donnees.get("allow_oosp"))
    elif "add_to_cart_url" in donnees:
        dispo = bool(panier)
    else:
        raise ErreurVerification("données PrestaShop sans disponibilité")
    # NB : en liste de résultats, add_to_cart_url est vide pour tout produit à
    # déclinaisons (Nymphali / Amphinobi…), même disponible : pas un signal de rupture.
    prix = lire_prix(donnees.get("price_amount", donnees.get("price")))
    detail = f"availability={disponibilite!r} quantity={quantite!r}"
    if "add_to_cart_url" in donnees:
        detail += f" panier={'oui' if panier else 'non'}"
    message = donnees.get("availability_message")
    if message:
        detail += f" ({message})"
    return Resultat(
        dispo=dispo,
        prix=prix,
        detail=detail,
        source="prestashop",
        image=_image_prestashop(donnees.get("cover")),
        quantite=int(quantite) if isinstance(quantite, (int, float)) and quantite > 0 else None,
        titre=str(donnees.get("name") or "") or None,
    )


def _image_prestashop(couverture: Any) -> str | None:
    if not isinstance(couverture, dict):
        return None
    tailles = couverture.get("bySize") if isinstance(couverture.get("bySize"), dict) else {}
    for taille in ("home_default", "medium_default", "large_default"):
        if isinstance(tailles.get(taille), dict) and tailles[taille].get("url"):
            return str(tailles[taille]["url"])
    grande = couverture.get("large")
    return str(grande["url"]) if isinstance(grande, dict) and grande.get("url") else None


def _var_js(page: str, nom: str) -> str | None:
    m = re.search(rf"\bvar\s+{nom}\s*=\s*([^;]+);", page)
    return m.group(1).strip().strip("'\"") if m else None


def lire_prestashop_16(page: str) -> Resultat:
    """PrestaShop 1.6 : la fiche expose son stock dans des variables JavaScript."""
    quantite = _var_js(page, "quantityAvailable")
    if quantite is None or not re.fullmatch(r"-?\d+", quantite):
        raise ErreurVerification("pas de données produit PrestaShop (data-product ni quantityAvailable) dans la page")
    commandable = _var_js(page, "productAvailableForOrder") not in ("false", "0")
    hors_stock_ok = _var_js(page, "allowBuyWhenOutOfStock") in ("true", "1")
    q = int(quantite)
    m_titre = _RE_OG_TITRE.search(page)
    return Resultat(
        dispo=commandable and (q > 0 or hors_stock_ok),
        prix=lire_prix(_var_js(page, "productPrice")) or extraire_prix(page),
        detail=f"PrestaShop 1.6 : quantityAvailable={q}" + ("" if commandable else " (non commandable)"),
        source="prestashop",
        image=image_og(page),
        quantite=q if q > 0 else None,
        titre=html.unescape(m_titre.group(1)) if m_titre else None,
    )


def verifier_prestashop(produit: Produit) -> Resultat:
    page = telecharger_page(produit.url)
    m = _RE_PRESTASHOP.search(page)
    if not m:
        return lire_prestashop_16(page)
    try:
        donnees = json.loads(html.unescape(m.group(1)))
    except json.JSONDecodeError as err:
        raise ErreurVerification("données PrestaShop illisibles") from err
    resultat = lire_produit_prestashop(donnees)
    resultat.image = resultat.image or image_og(page)
    return resultat


# --------------------------------------------------------------------------- #
# Page HTML quelconque
# --------------------------------------------------------------------------- #

_RE_PRIX_JSONLD = re.compile(r'"price"\s*:\s*"?(\d+(?:[.,]\d+)?)"?')
_RE_PRIX_AUTRES = re.compile(
    r'"priceAmount"\s*:\s*(\d+(?:\.\d+)?)'  # Amazon
    r'|class="a-offscreen">\s*(\d+(?:[.,]\d{2}))\s*€'  # Amazon
    r'|"priceValue"\s*:\s*"?(\d+(?:[.,]\d+)?)'  # divers
)
_RE_PRIX_META = re.compile(
    r"""(?:property|itemprop|name)\s*=\s*["'](?:product:price:amount|og:price:amount|price)["'][^>]*?content\s*=\s*["']([\d.,]+)["']"""
    r"""|content\s*=\s*["']([\d.,]+)["'][^>]*?(?:property|itemprop|name)\s*=\s*["'](?:product:price:amount|og:price:amount|price)["']""",
    re.IGNORECASE,
)
_RE_SCHEMA_DISPO = re.compile(
    r'(?:schema\.org/|availability["\']?\s*(?:content\s*=|:)\s*["\']?(?:https?://schema\.org/)?)'
    r'(InStock|OutOfStock|SoldOut|PreOrder|BackOrder|PreSale|LimitedAvailability|OnlineOnly|InStoreOnly|Discontinued)\b',
    re.IGNORECASE,
)
_RE_WEBSTORE = re.compile(r'"webStore"\s*:\s*\{\s*"available"\s*:\s*(true|false)', re.IGNORECASE)
_RE_WEBSTORE_TITRE = re.compile(r'"thresholdTitle"\s*:\s*"([^"]{1,60})"')
_RE_TITRE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_RE_OG_TITRE = re.compile(r"""<meta[^>]+property\s*=\s*["']og:title["'][^>]*content\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
_RE_OG_IMAGE = re.compile(
    r"""<meta[^>]+property\s*=\s*["']og:image["'][^>]*content\s*=\s*["']([^"']+)["']"""
    r"""|<meta[^>]+content\s*=\s*["']([^"']+)["'][^>]*property\s*=\s*["']og:image["']""",
    re.IGNORECASE,
)

# InStoreOnly = seulement en magasin physique : pas achetable en ligne.
SCHEMA_EN_STOCK = {"InStock", "LimitedAvailability", "OnlineOnly", "PreOrder", "PreSale", "BackOrder"}
SCHEMA_VALEURS = SCHEMA_EN_STOCK | {"OutOfStock", "SoldOut", "Discontinued", "InStoreOnly"}


def image_og(page_html: str) -> str | None:
    m = _RE_OG_IMAGE.search(page_html)
    if not m:
        return None
    lien = html.unescape(m.group(1) or m.group(2)).strip()
    if lien.startswith("//"):
        return "https:" + lien
    return lien if lien.startswith("http") else None


def extraire_prix(page_html: str) -> float | None:
    for motif in (_RE_PRIX_META, _RE_PRIX_JSONLD, _RE_PRIX_AUTRES):
        m = motif.search(page_html)
        if m:
            prix = lire_prix(next((g for g in m.groups() if g), ""))
            if prix:
                return prix
    return None


def disponibilite_schema(page_html: str) -> str | None:
    """Première disponibilité schema.org trouvée (InStock, OutOfStock, PreOrder…)."""
    m = _RE_SCHEMA_DISPO.search(page_html)
    if not m:
        return None
    valeur = m.group(1)
    return next((v for v in SCHEMA_VALEURS if v.lower() == valeur.lower()), valeur)


def page_anti_robot(page_html: str, texte: str) -> str | None:
    """Renvoie une raison si la page ressemble à un blocage anti-robot, sinon None.

    Une vraie fiche produit contient souvent le mot « captcha » (reCAPTCHA d'un
    formulaire) : on ne conclut au blocage que si la page est petite ou si son
    titre l'annonce.
    """
    m = _RE_TITRE.search(page_html)
    titre = normaliser(html.unescape(m.group(1))) if m else ""
    if re.search(r"captcha|robot|access denied|acces refuse|attention required|blocked|verification|challenge|just a moment", titre):
        return f"page anti-robot (titre : « {titre[:60]} »)"
    if len(page_html) < 30000:
        bas = normaliser(page_html)
        for mot in MOTS_ANTI_ROBOT:
            if normaliser(mot) in bas:
                return f"page anti-robot (« {mot} »)"
    if len(texte) < 300:
        return f"page presque vide ({len(texte)} caractères visibles) : blocage ou page 100 % JavaScript"
    return None


def verifier_texte(produit: Produit) -> Resultat:
    page = telecharger_page(produit.url)
    if not page.strip():
        raise ErreurVerification("page vide")
    texte = texte_visible(page)
    raison = page_anti_robot(page, texte)
    if raison:
        raise ErreurVerification(raison)
    prix = extraire_prix(page)
    image = image_og(page)

    def resultat(dispo: bool, detail: str) -> Resultat:
        return Resultat(dispo=dispo, prix=prix, detail=detail, source="texte", image=image)

    # Expressions régulières sur le HTML brut (pages JavaScript, marqueurs CSS…).
    if produit.regex_stock:
        if re.search(produit.regex_stock, page, re.IGNORECASE | re.DOTALL):
            return resultat(True, "regex_stock trouvée")
        if not produit.regex_rupture:
            return resultat(False, "regex_stock absente")
    if produit.regex_rupture:
        if re.search(produit.regex_rupture, page, re.IGNORECASE | re.DOTALL):
            return resultat(False, "regex_rupture trouvée")
        return resultat(True, "regex_rupture absente")

    # Plateforme Proximis (JouéClub, La Grande Récré…) : disponibilité web en JSON.
    m_web = _RE_WEBSTORE.search(page)
    if m_web and not produit.mots_explicites:
        titre = _RE_WEBSTORE_TITRE.search(page)
        detail = "webStore.available=" + m_web.group(1) + (f" ({titre.group(1)})" if titre else "")
        return resultat(m_web.group(1).lower() == "true", detail)

    # Données structurées (schema.org) : plus fiables que les mots, sauf si
    # produits.json fournit explicitement ses propres mots.
    schema = disponibilite_schema(page)
    if schema and not produit.mots_explicites:
        return resultat(schema in SCHEMA_EN_STOCK, f"schema.org : {schema}")

    if produit.mots_stock:
        trouves = [m for m in produit.mots_stock if normaliser(m) in texte]
        if trouves:
            return resultat(True, f"mot de stock : « {trouves[0]} »")
        return resultat(False, "aucun mot de stock trouvé")

    trouves = [m for m in produit.mots_rupture if normaliser(m) in texte]
    if trouves:
        return resultat(False, f"mot de rupture : « {trouves[0]} »")
    if len(texte) < 1500:
        # Aucun signal positif et presque pas de texte : page rendue en JavaScript.
        # On refuse de conclure « en stock » sur une absence de preuve.
        raise ErreurVerification(
            f"page rendue en JavaScript ({len(texte)} caractères visibles) : impossible de conclure, "
            "utilise regex_stock / mots_stock"
        )
    return resultat(True, "aucun mot de rupture")


def verifier_auto(produit: Produit) -> Resultat:
    """Détecte le type de boutique une fois, puis le réutilise pour les cycles suivants."""
    ordre = [produit.type_detecte] if produit.type_detecte else ["shopify", "woocommerce", "prestashop", "texte"]
    erreurs: list[str] = []
    for candidat in ordre:
        try:
            resultat = VERIFICATEURS[candidat](produit)
            produit.type_detecte = candidat
            return resultat
        except ErreurVerification as err:
            erreurs.append(f"{candidat} : {err}")
    raise ErreurVerification(" | ".join(erreurs))


VERIFICATEURS = {
    "shopify": verifier_shopify,
    "woocommerce": verifier_woocommerce,
    "prestashop": verifier_prestashop,
    "texte": verifier_texte,
    "auto": verifier_auto,
}


def verifier(produit: Produit) -> Resultat:
    """Ne lève jamais : toute erreur devient un Resultat(dispo=None)."""
    try:
        return VERIFICATEURS[produit.type](produit)
    except ErreurVerification as err:
        return Resultat(dispo=None, detail=str(err), source=produit.type)
    except Exception as err:  # garde-fou : un bug sur un produit ne stoppe pas les autres
        return Resultat(dispo=None, detail=f"erreur inattendue {type(err).__name__} : {err}", source=produit.type)
