#!/usr/bin/env python3
"""
Moniteur de stock — GitHub Actions + Discord.

- Bibliothèque standard uniquement (aucune dépendance à installer).
- Lit `produits.json`, vérifie chaque produit en parallèle toutes les
  INTERVALLE_SECONDES pendant DUREE_MINUTES, et envoie une alerte Discord
  uniquement lorsqu'un produit PASSE en stock.
- L'état (dispo / prix) est conservé dans `etat.json` entre deux cycles et,
  via le cache GitHub Actions, entre deux exécutions : pas de doublons.

Types de produit supportés (champ "type" dans produits.json) :
  shopify      -> interroge <url>.js (JSON officiel Shopify, très fiable)
  woocommerce  -> interroge l'API Store WooCommerce (/wp-json/wc/store/v1/products?slug=...)
  prestashop   -> lit le JSON data-product de la page (PrestaShop 1.7+)
  texte        -> lit les données schema.org de la page, sinon cherche des mots de rupture / de stock
  auto         -> essaie shopify, woocommerce, prestashop, puis texte

Variables d'environnement :
  DISCORD_WEBHOOK       URL du webhook Discord (jamais dans le code !)
  DISCORD_MENTION       optionnel, ex. "@everyone" ou "<@&ID_DU_ROLE>"
  PRIX_MAX              optionnel, ne pas alerter au-dessus de ce prix en euros (anti-spéculateurs)
  GITHUB_EVENT_NAME     fourni par GitHub Actions ("workflow_dispatch" = lancement manuel)
  DUREE_MINUTES         durée totale d'une exécution (défaut 20)
  INTERVALLE_SECONDES   délai entre deux cycles (défaut 60)
  TIMEOUT_SECONDES      délai max d'une requête HTTP (défaut 15)
  ALERTE_RUPTURE        "1" pour être prévenu aussi quand un produit repasse en rupture
  FICHIER_PRODUITS      défaut produits.json
  FICHIER_ETAT          défaut etat.json
"""

from __future__ import annotations

import argparse
import gzip
import html
import json
import math
import os
import re
import signal
import sys
import time
import unicodedata
import zlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

VERSION = "1.0.0"

DUREE_MINUTES = float(os.environ.get("DUREE_MINUTES", "20"))
INTERVALLE_SECONDES = float(os.environ.get("INTERVALLE_SECONDES", "60"))
TIMEOUT_SECONDES = float(os.environ.get("TIMEOUT_SECONDES", "15"))
FICHIER_PRODUITS = os.environ.get("FICHIER_PRODUITS", "produits.json")
FICHIER_ETAT = os.environ.get("FICHIER_ETAT", "etat.json")
ALERTE_RUPTURE = os.environ.get("ALERTE_RUPTURE", "0").strip() in {"1", "true", "oui", "yes"}
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK", "").strip()
DISCORD_MENTION = os.environ.get("DISCORD_MENTION", "").strip()
GITHUB_EVENT_NAME = os.environ.get("GITHUB_EVENT_NAME", "")

MAX_WORKERS = 16  # nombre de produits vérifiés en parallèle
TENTATIVES_HTTP = 2  # nouvel essai sur erreur réseau (pas sur 404)

# Discord refuse le User-Agent par défaut de urllib ; les boutiques préfèrent
# un navigateur classique.
UA_NAVIGATEUR = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
UA_DISCORD = f"MoniteurStock/{VERSION} (+https://github.com/lemononkali/moniteur-etb)"

MOTS_RUPTURE_DEFAUT = ["rupture", "épuisé", "indisponible", "sold out", "plus disponible", "me prévenir"]

# Au-delà de ce prix (en euros), un produit en stock n'est pas signalé (revendeurs
# spéculateurs). Vide = pas de limite. Surchargeable par produit avec "prix_max".
PRIX_MAX = float(os.environ.get("PRIX_MAX") or 0) or None

# Signes d'une page anti-robot (captcha, blocage) : on préfère une erreur claire
# à une fausse détection.
MOTS_ANTI_ROBOT = ["captcha", "automated access", "are you a human", "access denied", "êtes-vous un robot", "verify you are human"]

# Mots autour desquels le mode --diagnostic affiche des extraits de page,
# pour choisir les bons mots_rupture / mots_stock d'une nouvelle boutique.
MOTS_DIAGNOSTIC = [
    "en stock", "rupture", "epuis", "indisponible", "sold out", "panier",
    "precommande", "prevenir", "bientot", "reapprovisionn", "disponible", "commander",
]

TYPES_VALIDES = {"shopify", "woocommerce", "prestashop", "texte", "auto"}

# --------------------------------------------------------------------------- #
# Journalisation
# --------------------------------------------------------------------------- #


def log(message: str) -> None:
    horodatage = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{horodatage}] {message}", flush=True)


# --------------------------------------------------------------------------- #
# Modèles
# --------------------------------------------------------------------------- #


@dataclass
class Produit:
    nom: str
    url: str
    type: str = "auto"
    mots_rupture: list[str] = field(default_factory=lambda: list(MOTS_RUPTURE_DEFAUT))
    mots_stock: list[str] = field(default_factory=list)
    regex_stock: str | None = None  # expression régulière sur le HTML brut → en stock si elle matche
    regex_rupture: str | None = None  # expression régulière sur le HTML brut → rupture si elle matche
    variante: str | None = None  # ne considérer que les variantes dont le titre contient ce texte
    prix_max: float | None = None  # au-delà, on ne signale pas (surcharge PRIX_MAX)
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
        variante = brut.get("variante")
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
        return cls(
            nom=nom,
            url=url,
            type=type_,
            mots_rupture=[str(m) for m in mots_rupture],
            mots_stock=[str(m) for m in mots_stock],
            variante=str(variante).strip() if variante else None,
            prix_max=prix_max,
            regex_stock=str(regex_stock) if regex_stock else None,
            regex_rupture=str(regex_rupture) if regex_rupture else None,
            mots_explicites=bool(brut.get("mots_rupture") or brut.get("mots_stock")),
            actif=bool(brut.get("actif", True)),
        )


@dataclass
class Resultat:
    """Résultat d'une vérification. `dispo` vaut None en cas d'erreur."""

    dispo: bool | None
    prix: float | None = None  # en euros
    detail: str = ""  # variante disponible, message d'erreur, etc.
    source: str = ""  # type effectivement utilisé (shopify / woocommerce / texte)


class ErreurVerification(Exception):
    """Erreur propre à un produit : ne doit jamais faire planter le moniteur."""


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #


def _decompresser(donnees: bytes, encodage: str) -> bytes:
    encodage = (encodage or "").lower()
    if "gzip" in encodage:
        return gzip.decompress(donnees)
    if "deflate" in encodage:
        try:
            return zlib.decompress(donnees)
        except zlib.error:
            return zlib.decompress(donnees, -zlib.MAX_WBITS)
    return donnees


def telecharger(url: str, accept: str = "*/*") -> tuple[int, bytes, str]:
    """Télécharge `url` et renvoie (code HTTP, corps décompressé, charset).

    Réessaie une fois sur erreur réseau ou erreur 5xx / 429. Lève
    ErreurVerification avec un message lisible sinon.
    """
    entetes = {
        "User-Agent": UA_NAVIGATEUR,
        "Accept": accept,
        "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.7",
        "Accept-Encoding": "gzip, deflate",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    derniere_erreur: Exception | None = None
    for tentative in range(1, TENTATIVES_HTTP + 1):
        try:
            requete = Request(url, headers=entetes)
            with urlopen(requete, timeout=TIMEOUT_SECONDES) as reponse:
                corps = _decompresser(reponse.read(), reponse.headers.get("Content-Encoding", ""))
                charset = reponse.headers.get_content_charset() or "utf-8"
                return reponse.status, corps, charset
        except HTTPError as err:
            if err.code in (429, 500, 502, 503, 504) and tentative < TENTATIVES_HTTP:
                derniere_erreur = err
                time.sleep(2.0 * tentative)
                continue
            raise ErreurVerification(f"HTTP {err.code} ({err.reason})") from err
        except (URLError, TimeoutError, OSError) as err:  # réseau, DNS, timeout, TLS…
            derniere_erreur = err
            if tentative < TENTATIVES_HTTP:
                time.sleep(1.5 * tentative)
                continue
    raison = getattr(derniere_erreur, "reason", None) or derniere_erreur
    raise ErreurVerification(f"réseau : {raison}")


def telecharger_json(url: str) -> Any:
    _, corps, charset = telecharger(url, accept="application/json,text/javascript;q=0.9,*/*;q=0.1")
    try:
        return json.loads(corps.decode(charset, errors="replace"))
    except json.JSONDecodeError as err:
        raise ErreurVerification("réponse non JSON (boutique protégée par mot de passe ou URL incorrecte ?)") from err


def telecharger_texte(url: str) -> str:
    _, corps, charset = telecharger(url, accept="text/html,application/xhtml+xml,*/*;q=0.8")
    try:
        return corps.decode(charset, errors="replace")
    except LookupError:
        return corps.decode("utf-8", errors="replace")


# --------------------------------------------------------------------------- #
# Vérificateurs
# --------------------------------------------------------------------------- #


def _sans_query(url: str) -> tuple[str, str, str]:
    """Renvoie (scheme, netloc, path) sans query ni fragment, path sans slash final."""
    parts = urlsplit(url)
    return parts.scheme, parts.netloc, parts.path.rstrip("/")


def url_shopify_js(url: str) -> str:
    scheme, netloc, path = _sans_query(url)
    if path.endswith(".js"):
        pass
    elif path.endswith(".json"):
        path = path[:-5] + ".js"
    else:
        path = path + ".js"
    return urlunsplit((scheme, netloc, path, "", ""))


def verifier_shopify(produit: Produit) -> Resultat:
    donnees = telecharger_json(url_shopify_js(produit.url))
    if not isinstance(donnees, dict) or "variants" not in donnees:
        raise ErreurVerification("format Shopify inattendu (pas de champ 'variants')")

    variantes = donnees.get("variants") or []
    if produit.variante:
        filtre = normaliser(produit.variante)
        variantes = [v for v in variantes if filtre in normaliser(str(v.get("title", "")))]
        if not variantes:
            raise ErreurVerification(f"aucune variante ne contient « {produit.variante} »")

    dispos = [v for v in variantes if v.get("available")]
    if produit.variante:
        dispo = bool(dispos)
    else:
        dispo = bool(dispos) or bool(donnees.get("available"))

    prix_centimes: int | None = None
    candidats = dispos if dispos else variantes
    prix_liste = [v.get("price") for v in candidats if isinstance(v.get("price"), (int, float))]
    if prix_liste:
        prix_centimes = int(min(prix_liste))
    elif isinstance(donnees.get("price"), (int, float)):
        prix_centimes = int(donnees["price"])

    detail = ""
    if dispos and len(variantes) > 1:
        titres = [str(v.get("title", "")) for v in dispos if v.get("title") not in (None, "", "Default Title")]
        if titres:
            detail = "variante(s) : " + ", ".join(titres[:5])

    return Resultat(
        dispo=dispo,
        prix=prix_centimes / 100 if prix_centimes is not None else None,
        detail=detail,
        source="shopify",
    )


def verifier_woocommerce(produit: Produit) -> Resultat:
    scheme, netloc, path = _sans_query(produit.url)
    slug = path.rsplit("/", 1)[-1]
    if not slug:
        raise ErreurVerification("impossible de déduire le slug WooCommerce depuis l'URL")
    api = urlunsplit((scheme, netloc, "/wp-json/wc/store/v1/products", f"slug={slug}", ""))
    donnees = telecharger_json(api)
    if not isinstance(donnees, list) or not donnees:
        raise ErreurVerification("produit introuvable via l'API Store WooCommerce")
    fiche = donnees[0]
    if not isinstance(fiche, dict) or "is_in_stock" not in fiche:
        raise ErreurVerification("format WooCommerce inattendu (pas de champ 'is_in_stock')")

    dispo = bool(fiche.get("is_in_stock")) and bool(fiche.get("is_purchasable", True))
    prix: float | None = None
    prix_info = fiche.get("prices") or {}
    try:
        brut = prix_info.get("price")
        unite = int(prix_info.get("currency_minor_unit", 2))
        if brut not in (None, ""):
            prix = int(brut) / (10**unite)
    except (TypeError, ValueError):
        prix = None
    return Resultat(dispo=dispo, prix=prix, source="woocommerce")


def verifier_prestashop(produit: Produit) -> Resultat:
    page = telecharger_texte(produit.url)
    m = _RE_PRESTASHOP.search(page)
    if not m:
        raise ErreurVerification("pas de données produit PrestaShop (data-product) dans la page")
    try:
        donnees = json.loads(html.unescape(m.group(1)))
    except json.JSONDecodeError as err:
        raise ErreurVerification("données PrestaShop illisibles") from err
    if not isinstance(donnees, dict):
        raise ErreurVerification("données PrestaShop inattendues")

    disponibilite = str(donnees.get("availability") or "")
    quantite = donnees.get("quantity")
    if disponibilite:
        dispo = disponibilite != "unavailable"
    elif isinstance(quantite, (int, float)):
        dispo = quantite > 0 or bool(donnees.get("allow_oosp"))
    else:
        raise ErreurVerification("données PrestaShop sans disponibilité")

    prix: float | None = None
    brut = donnees.get("price_amount", donnees.get("price"))
    if isinstance(brut, (int, float)):
        prix = float(brut)
    elif isinstance(brut, str):
        m_prix = re.search(r"\d+(?:[.,]\d+)?", brut.replace("\u00a0", ""))
        if m_prix:
            prix = float(m_prix.group(0).replace(",", "."))
    detail = f"availability={disponibilite!r} quantity={quantite!r}"
    if "add_to_cart_url" in donnees:
        detail += f" panier={'oui' if donnees.get('add_to_cart_url') else 'non'}"
    message = donnees.get("availability_message")
    if message:
        detail += f" ({message})"
    return Resultat(dispo=dispo, prix=prix if prix and prix > 0 else None, detail=detail, source="prestashop")


_RE_SCRIPT_STYLE = re.compile(r"<(script|style|noscript|template)\b.*?</\1\s*>", re.IGNORECASE | re.DOTALL)
_RE_COMMENTAIRE = re.compile(r"<!--.*?-->", re.DOTALL)
_RE_BALISE = re.compile(r"<[^>]+>")
_RE_ESPACES = re.compile(r"\s+")
_RE_PRIX_JSONLD = re.compile(r'"price"\s*:\s*"?(\d+(?:[.,]\d+)?)"?')
_RE_SCHEMA_DISPO = re.compile(
    r'(?:schema\.org/|"availability"\s*:\s*")(InStock|OutOfStock|SoldOut|PreOrder|BackOrder|PreSale|'
    r'LimitedAvailability|OnlineOnly|InStoreOnly|Discontinued)\b'
)
_RE_PRESTASHOP = re.compile(r'data-product\s*=\s*"(\{[^"]*)"')  # objet JSON échappé (&quot;)
_RE_BRUT_DIAG = re.compile(r'.{0,70}(?:availability|in_?stock|outofstock|"stock|quantity"|indisponible|[ée]puis[ée]|rupture|dispo(?!nibilit)).{0,70}', re.IGNORECASE)
_RE_PRIX_META = re.compile(
    r"""(?:property|itemprop|name)\s*=\s*["'](?:product:price:amount|og:price:amount|price)["'][^>]*?content\s*=\s*["']([\d.,]+)["']"""
    r"""|content\s*=\s*["']([\d.,]+)["'][^>]*?(?:property|itemprop|name)\s*=\s*["'](?:product:price:amount|og:price:amount|price)["']""",
    re.IGNORECASE,
)


def normaliser(texte: str) -> str:
    """Minuscules, sans accents, espaces compactés — pour comparer sans surprise."""
    texte = unicodedata.normalize("NFKD", texte)
    texte = "".join(c for c in texte if not unicodedata.combining(c))
    return _RE_ESPACES.sub(" ", texte.lower()).strip()


def texte_visible(page_html: str) -> str:
    """Retire scripts, styles, commentaires et balises : on ne garde que le texte lisible.

    Évite les faux positifs quand le thème contient « Sold out » dans son JS.
    """
    sans_scripts = _RE_SCRIPT_STYLE.sub(" ", page_html)
    sans_commentaires = _RE_COMMENTAIRE.sub(" ", sans_scripts)
    sans_balises = _RE_BALISE.sub(" ", sans_commentaires)
    return normaliser(html.unescape(sans_balises))


def extraire_prix(page_html: str) -> float | None:
    m = _RE_PRIX_META.search(page_html)
    brut = (m.group(1) or m.group(2) or "") if m else ""
    if not brut:
        m2 = _RE_PRIX_JSONLD.search(page_html)
        brut = m2.group(1) if m2 else ""
    try:
        prix = float(brut.replace(",", "."))
    except ValueError:
        return None
    return prix if prix > 0 else None


def disponibilite_schema(page_html: str) -> str | None:
    """Première disponibilité schema.org trouvée (InStock, OutOfStock, PreOrder…)."""
    m = _RE_SCHEMA_DISPO.search(page_html)
    return m.group(1) if m else None


SCHEMA_EN_STOCK = {"InStock", "LimitedAvailability", "OnlineOnly", "InStoreOnly", "PreOrder", "PreSale", "BackOrder"}


def page_anti_robot(page_html: str, texte: str) -> str | None:
    """Renvoie une raison si la page ressemble à un blocage anti-robot, sinon None."""
    bas = page_html.lower()
    for mot in MOTS_ANTI_ROBOT:
        if normaliser(mot) in normaliser(bas[:20000]):
            return f"page anti-robot (« {mot} »)"
    if len(texte) < 300:
        return f"page presque vide ({len(texte)} caractères visibles) : blocage ou page 100 % JavaScript"
    return None


def verifier_texte(produit: Produit) -> Resultat:
    page = telecharger_texte(produit.url)
    if not page.strip():
        raise ErreurVerification("page vide")
    texte = texte_visible(page)
    raison = page_anti_robot(page, texte)
    if raison:
        raise ErreurVerification(raison)
    prix = extraire_prix(page)

    # Expressions régulières sur le HTML brut (pages JavaScript, marqueurs CSS…).
    if produit.regex_stock:
        if re.search(produit.regex_stock, page, re.IGNORECASE | re.DOTALL):
            return Resultat(dispo=True, prix=prix, detail="regex_stock trouvée", source="texte")
        if not produit.regex_rupture:
            return Resultat(dispo=False, prix=prix, detail="regex_stock absente", source="texte")
    if produit.regex_rupture:
        if re.search(produit.regex_rupture, page, re.IGNORECASE | re.DOTALL):
            return Resultat(dispo=False, prix=prix, detail="regex_rupture trouvée", source="texte")
        return Resultat(dispo=True, prix=prix, detail="regex_rupture absente", source="texte")

    # Données structurées (schema.org) : plus fiables que les mots, sauf si
    # produits.json fournit explicitement ses propres mots.
    schema = disponibilite_schema(page)
    if schema and not produit.mots_explicites:
        dispo = schema in SCHEMA_EN_STOCK
        return Resultat(dispo=dispo, prix=prix, detail=f"schema.org : {schema}", source="texte")

    if produit.mots_stock:
        trouves = [m for m in produit.mots_stock if normaliser(m) in texte]
        if trouves:
            return Resultat(dispo=True, prix=prix, detail=f"mot de stock : « {trouves[0]} »", source="texte")
        return Resultat(dispo=False, prix=prix, detail="aucun mot de stock trouvé", source="texte")

    trouves = [m for m in produit.mots_rupture if normaliser(m) in texte]
    if trouves:
        return Resultat(dispo=False, prix=prix, detail=f"mot de rupture : « {trouves[0]} »", source="texte")
    return Resultat(dispo=True, prix=prix, detail="aucun mot de rupture", source="texte")


def verifier_auto(produit: Produit) -> Resultat:
    """Détecte le type de boutique une fois, puis le réutilise pour les cycles suivants."""
    ordre = ["shopify", "woocommerce", "prestashop", "texte"]
    if produit.type_detecte:
        ordre = [produit.type_detecte]
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


def extraits(texte: str, mots: list[str], marge: int = 45, maximum: int = 14, par_mot: int = 2) -> list[str]:
    """Petits extraits du texte visible autour de chaque mot-clé (pour --diagnostic)."""
    resultats: list[str] = []
    deja: set[int] = set()
    for mot in mots:
        debut = 0
        trouves = 0
        while len(resultats) < maximum and trouves < par_mot:
            pos = texte.find(normaliser(mot), debut)
            if pos < 0:
                break
            if all(abs(pos - d) > marge for d in deja):
                deja.add(pos)
                trouves += 1
                resultats.append("…" + texte[max(0, pos - marge): pos + len(mot) + marge] + "…")
            debut = pos + 1
    return resultats


def diagnostiquer(produit: Produit) -> Resultat:
    """Vérifie un produit et affiche de quoi comprendre la page (mode --diagnostic)."""
    resultat = verifier(produit)
    source = produit.type_detecte or resultat.source or produit.type
    etat = "ERREUR" if resultat.dispo is None else ("EN STOCK" if resultat.dispo else "rupture")
    lignes = [
        f"=== {produit.nom} [{produit.type} → {source}] {etat}  {formater_prix(resultat.prix)}",
        f"    {produit.url}",
    ]
    if resultat.detail:
        lignes.append(f"    détail : {resultat.detail}")
    if source in ("texte", "auto") or resultat.dispo is None:
        try:
            page = telecharger_texte(produit.url)
        except ErreurVerification as err:
            lignes.append(f"    page : {err}")
            page = ""
        if page:
            texte = texte_visible(page)
            lignes.append(f"    page : {len(page)} caractères, texte visible {len(texte)} caractères")
            schema = disponibilite_schema(page)
            if schema:
                lignes.append(f"    schema.org : {schema}")
            if _RE_PRESTASHOP.search(page):
                lignes.append('    indice : données PrestaShop présentes → type "prestashop"')
            raison = page_anti_robot(page, texte)
            if raison:
                lignes.append(f"    ⚠️  {raison}")
            if len(texte) < 1500:
                lignes.append(f"    texte visible : {texte[:600]!r}")
            for ident in sorted(set(re.findall(r"\d{4,}", urlsplit(produit.url).path)), key=len, reverse=True)[:2]:
                for k, m in enumerate(re.finditer(re.escape(ident), page)):
                    if k >= 3:
                        break
                    ctx = " ".join(page[max(0, m.start() - 220): m.end() + 220].split())
                    lignes.append(f"    #{ident} : {ctx}")
            bruts = []
            for m in _RE_BRUT_DIAG.finditer(page):
                extrait = " ".join(m.group(0).split())
                if extrait not in bruts:
                    bruts.append(extrait)
                if len(bruts) >= 10:
                    break
            for extrait in bruts:
                lignes.append(f"    ~ {extrait}")
            if "shopify" in page.lower():
                lignes.append('    indice : la page mentionne Shopify → essaie type "shopify"')
            if "woocommerce" in page.lower() or "wp-content" in page.lower():
                lignes.append('    indice : la page mentionne WooCommerce/WordPress → essaie type "woocommerce"')
            for extrait in extraits(texte, MOTS_DIAGNOSTIC):
                lignes.append(f"    · {extrait}")
    print("\n".join(lignes) + "\n", flush=True)  # un seul print : pas d'entrelacement entre threads
    return resultat


# --------------------------------------------------------------------------- #
# Discord
# --------------------------------------------------------------------------- #


def formater_prix(prix: float | None) -> str:
    if prix is None:
        return ""
    texte = f"{prix:,.2f}".replace(",", " ").replace(".", ",")
    return f"{texte} €"


def envoyer_discord(contenu: str, mention: bool = False) -> bool:
    """Envoie un message via le webhook. Gère le rate-limit Discord (429)."""
    if not DISCORD_WEBHOOK:
        log(f"(DISCORD_WEBHOOK absent, message non envoyé) {contenu!r}")
        return False
    if mention and DISCORD_MENTION:
        contenu = f"{DISCORD_MENTION} {contenu}"
    charge = {
        "content": contenu[:2000],
        "allowed_mentions": {"parse": ["everyone", "roles", "users"]},
    }
    corps = json.dumps(charge).encode("utf-8")
    entetes = {"Content-Type": "application/json", "User-Agent": UA_DISCORD}
    for tentative in range(1, 4):
        try:
            requete = Request(DISCORD_WEBHOOK, data=corps, headers=entetes, method="POST")
            with urlopen(requete, timeout=TIMEOUT_SECONDES) as reponse:
                if 200 <= reponse.status < 300:
                    return True
                log(f"Discord : réponse inattendue HTTP {reponse.status}")
        except HTTPError as err:
            if err.code == 429:
                attente = 2.0
                try:
                    attente = float(json.loads(err.read().decode("utf-8", "replace")).get("retry_after", attente))
                except Exception:
                    attente = float(err.headers.get("Retry-After", attente) or attente)
                log(f"Discord : rate-limit, nouvel essai dans {attente:.1f} s")
                time.sleep(min(attente, 10.0) + 0.2)
                continue
            log(f"Discord : erreur HTTP {err.code} ({err.reason})")
            if 400 <= err.code < 500:
                return False
        except (URLError, TimeoutError, OSError) as err:
            log(f"Discord : erreur réseau {getattr(err, 'reason', err)}")
        time.sleep(1.5 * tentative)
    return False


def message_en_stock(produit: Produit, resultat: Resultat) -> str:
    prix = formater_prix(resultat.prix)
    ligne = f"🚨 EN STOCK : {produit.nom}" + (f" à {prix}" if prix else "")
    if resultat.detail and resultat.detail.startswith("variante"):
        ligne += f" ({resultat.detail})"
    return f"{ligne}\n{produit.url}"


def message_rupture(produit: Produit) -> str:
    return f"⛔ Rupture : {produit.nom}\n{produit.url}"


# --------------------------------------------------------------------------- #
# État persistant
# --------------------------------------------------------------------------- #


def charger_etat() -> dict[str, dict[str, Any]]:
    try:
        with open(FICHIER_ETAT, encoding="utf-8") as f:
            donnees = json.load(f)
        if isinstance(donnees, dict):
            return donnees
    except FileNotFoundError:
        pass
    except (OSError, json.JSONDecodeError) as err:
        log(f"État précédent illisible ({err}), on repart de zéro")
    return {}


def sauvegarder_etat(etat: dict[str, dict[str, Any]]) -> None:
    temporaire = FICHIER_ETAT + ".tmp"
    try:
        with open(temporaire, "w", encoding="utf-8") as f:
            json.dump(etat, f, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(temporaire, FICHIER_ETAT)
    except OSError as err:
        log(f"Impossible d'écrire {FICHIER_ETAT} : {err}")


# --------------------------------------------------------------------------- #
# Boucle principale
# --------------------------------------------------------------------------- #


def charger_produits() -> list[Produit]:
    try:
        with open(FICHIER_PRODUITS, encoding="utf-8") as f:
            brut = json.load(f)
    except FileNotFoundError:
        sys.exit(f"Fichier {FICHIER_PRODUITS} introuvable.")
    except json.JSONDecodeError as err:
        sys.exit(f"{FICHIER_PRODUITS} n'est pas un JSON valide : {err}")
    if isinstance(brut, dict) and "produits" in brut:
        brut = brut["produits"]
    if not isinstance(brut, list):
        sys.exit(f"{FICHIER_PRODUITS} doit contenir une liste de produits.")

    produits: list[Produit] = []
    urls_vues: set[str] = set()
    for index, element in enumerate(brut):
        try:
            produit = Produit.depuis_dict(element, index)
        except ValueError as err:
            log(f"⚠️  Produit ignoré — {err}")
            continue
        if not produit.actif:
            log(f"⏸  {produit.nom} : désactivé (actif = false)")
            continue
        if produit.url in urls_vues:
            log(f"⚠️  Produit ignoré — URL en double : {produit.url}")
            continue
        urls_vues.add(produit.url)
        produits.append(produit)
    return produits


def executer_cycle(
    produits: list[Produit],
    etat: dict[str, dict[str, Any]],
    executeur: ThreadPoolExecutor,
) -> tuple[int, int, int]:
    """Vérifie tous les produits en parallèle. Renvoie (dispo, rupture, erreurs)."""
    nb_dispo = nb_rupture = nb_erreur = 0
    futurs = {executeur.submit(verifier, p): p for p in produits}
    for futur in as_completed(futurs):
        produit = futurs[futur]
        resultat = futur.result()
        precedent = etat.get(produit.url, {})
        dispo_avant = precedent.get("dispo")  # True / False / None (inconnu)
        maintenant = datetime.now(timezone.utc).isoformat(timespec="seconds")

        if resultat.dispo is None:
            nb_erreur += 1
            log(f"⚠️  {produit.nom} : {resultat.detail}")
            etat.setdefault(produit.url, {})["derniere_erreur"] = f"{maintenant} {resultat.detail}"
            continue

        prix = formater_prix(resultat.prix)
        limite = produit.prix_max if produit.prix_max is not None else PRIX_MAX
        if resultat.dispo and limite is not None and resultat.prix is not None and resultat.prix > limite:
            log(f"💸 trop cher    {produit.nom}  {prix} > {formater_prix(limite)} (pas d'alerte)")
            resultat.dispo = False  # mémorisé comme « pas dispo à un prix acceptable »
            resultat.detail = f"trop cher (> {formater_prix(limite)})"

        if resultat.dispo:
            nb_dispo += 1
            log(f"✅ EN STOCK   {produit.nom}" + (f"  {prix}" if prix else "") + (f"  [{resultat.detail}]" if resultat.detail else ""))
            if dispo_avant is not True:
                if envoyer_discord(message_en_stock(produit, resultat), mention=True):
                    log(f"🔔 Alerte Discord envoyée pour {produit.nom}")
        else:
            nb_rupture += 1
            log(f"⛔ rupture     {produit.nom}" + (f"  {prix}" if prix else "") + (f"  [{resultat.detail}]" if resultat.detail else ""))
            if ALERTE_RUPTURE and dispo_avant is True:
                envoyer_discord(message_rupture(produit))

        etat[produit.url] = {
            "nom": produit.nom,
            "dispo": resultat.dispo,
            "prix": resultat.prix,
            "source": resultat.source if produit.type != "auto" else (produit.type_detecte or "auto"),
            "vu": maintenant,
        }
    return nb_dispo, nb_rupture, nb_erreur


def main(argv: list[str] | None = None) -> int:
    parseur = argparse.ArgumentParser(description="Moniteur de stock avec alertes Discord.")
    parseur.add_argument("--une-fois", action="store_true", help="un seul cycle puis sortie")
    parseur.add_argument("--test-discord", action="store_true", help="envoie un message de test et quitte")
    parseur.add_argument(
        "--diagnostic",
        action="store_true",
        help="un seul cycle sans Discord, avec des extraits de page pour régler chaque boutique",
    )
    args = parseur.parse_args(argv)

    if args.test_discord:
        ok = envoyer_discord("🧪 Test du moniteur : le webhook fonctionne.")
        return 0 if ok else 1

    produits = charger_produits()
    if not produits:
        log("Aucun produit à surveiller : vérifie produits.json.")
        return 1

    if args.diagnostic:
        with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(produits))) as executeur:
            resultats = list(executeur.map(diagnostiquer, produits))
        nb_err = sum(1 for r in resultats if r.dispo is None)
        print(f"\n{len(produits)} produit(s) : {sum(1 for r in resultats if r.dispo)} en stock, "
              f"{sum(1 for r in resultats if r.dispo is False)} en rupture, {nb_err} erreur(s)")
        return 0

    duree = 0 if args.une_fois else DUREE_MINUTES * 60
    intervalle = max(5.0, INTERVALLE_SECONDES)
    nb_cycles_prevus = 1 if args.une_fois else max(1, math.ceil(duree / intervalle))

    log(f"Moniteur v{VERSION} — {len(produits)} produit(s), toutes les {intervalle:.0f} s pendant {duree / 60:.0f} min")
    for p in produits:
        log(f"   • {p.nom} [{p.type}] {p.url}")
    if not DISCORD_WEBHOOK:
        log("⚠️  DISCORD_WEBHOOK n'est pas défini : les alertes seront seulement affichées ici.")

    if GITHUB_EVENT_NAME == "workflow_dispatch":
        envoyer_discord(
            f"✅ Moniteur lancé — {len(produits)} produit(s) surveillé(s), "
            f"vérification toutes les {intervalle:.0f} s pendant {duree / 60:.0f} min."
        )

    etat = charger_etat()
    arret = {"demande": False}

    def demander_arret(signum: int, _frame: Any) -> None:
        log(f"Signal {signum} reçu, arrêt propre après ce cycle.")
        arret["demande"] = True

    signal.signal(signal.SIGTERM, demander_arret)
    signal.signal(signal.SIGINT, demander_arret)

    debut = time.monotonic()
    fin = debut + duree
    cycle = 0
    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(produits))) as executeur:
        while True:
            cycle += 1
            top = time.monotonic()
            nb_dispo, nb_rupture, nb_erreur = executer_cycle(produits, etat, executeur)
            sauvegarder_etat(etat)
            duree_cycle = time.monotonic() - top
            log(
                f"— cycle {cycle}/{nb_cycles_prevus} en {duree_cycle:.1f} s : "
                f"{nb_dispo} en stock, {nb_rupture} en rupture, {nb_erreur} erreur(s)"
            )

            if args.une_fois or arret["demande"]:
                break
            prochain = top + intervalle
            if prochain + 1.0 >= fin:  # le prochain cycle dépasserait la durée prévue
                break
            time.sleep(max(0.0, prochain - time.monotonic()))

    log(f"Terminé après {cycle} cycle(s) et {(time.monotonic() - debut) / 60:.1f} min.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
