"""Outils de texte : normalisation, texte visible d'une page, prix."""

from __future__ import annotations

import html
import re
import unicodedata

_RE_ESPACES = re.compile(r"\s+")
_RE_PONCTUATION = re.compile(r"[^a-z0-9]+")
_RE_SCRIPT_STYLE = re.compile(r"<(script|style|noscript|template)\b.*?</\1\s*>", re.IGNORECASE | re.DOTALL)
_RE_COMMENTAIRE = re.compile(r"<!--.*?-->", re.DOTALL)
_RE_BALISE = re.compile(r"<[^>]+>")


def sans_accents(texte: str) -> str:
    # NFKD décompose aussi les exposants : « 30ᵉ » devient « 30e ».
    texte = unicodedata.normalize("NFKD", texte)
    return "".join(c for c in texte if not unicodedata.combining(c))


def normaliser(texte: str) -> str:
    """Minuscules, sans accents, espaces compactés — pour comparer sans surprise."""
    return _RE_ESPACES.sub(" ", sans_accents(texte).lower()).strip()


def mots(texte: str) -> str:
    """Comme normaliser, mais toute ponctuation devient une espace.

    « Coffret Dresseur d'Élite » → « coffret dresseur d elite », « K.O. » → « k o ».
    Sert à classer les produits par mots-clés, indépendamment de la typographie.
    """
    return _RE_PONCTUATION.sub(" ", sans_accents(html.unescape(texte)).lower()).strip()


def texte_visible(page_html: str) -> str:
    """Retire scripts, styles, commentaires et balises : on ne garde que le texte lisible.

    Évite les faux positifs quand le thème contient « Sold out » dans son JS.
    """
    sans_scripts = _RE_SCRIPT_STYLE.sub(" ", page_html)
    sans_commentaires = _RE_COMMENTAIRE.sub(" ", sans_scripts)
    sans_balises = _RE_BALISE.sub(" ", sans_commentaires)
    return normaliser(html.unescape(sans_balises))


def lire_prix(brut: object, centimes: bool = False) -> float | None:
    """Convertit 69.9, "69,90", "69.90 €" ou 6990 (centimes=True) en euros. 0 = inconnu."""
    if isinstance(brut, bool) or brut is None:
        return None
    if isinstance(brut, (int, float)):
        valeur = float(brut)
    else:
        texte = str(brut).replace(" ", "").replace(" ", "")
        m = re.search(r"\d+(?:[.,]\d+)*", texte)
        if not m:
            return None
        nombre = m.group(0)
        # « 1.299,90 » ou « 1,299.90 » : le dernier séparateur est la décimale.
        if "," in nombre and "." in nombre:
            if nombre.rfind(",") > nombre.rfind("."):
                nombre = nombre.replace(".", "").replace(",", ".")
            else:
                nombre = nombre.replace(",", "")
        else:
            nombre = nombre.replace(",", ".")
        try:
            valeur = float(nombre)
        except ValueError:
            return None
    if centimes:
        valeur /= 100
    return round(valeur, 2) if valeur > 0 else None


def formater_prix(prix: float | None) -> str:
    if prix is None:
        return ""
    texte = f"{prix:,.2f}".replace(",", " ").replace(".", ",")
    return f"{texte} €"
