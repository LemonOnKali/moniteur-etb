"""Outils de mise au point : --diagnostic, --decouvrir, --liens.

Rien n'est envoyé sur Discord : on affiche de quoi comprendre chaque page ou
boutique et choisir les bons réglages.
"""

from __future__ import annotations

import html
import json
import re
from typing import Callable
from urllib.parse import unquote, urlsplit, urlunsplit

from .boutiques import Analyse, Boutique, analyser
from .collection import Collection
from .http import ErreurVerification, telecharger, telecharger_page
from .modeles import Offre
from .pages import (
    _RE_PRESTASHOP,
    _RE_WEBSTORE,
    Produit,
    disponibilite_schema,
    domaine,
    page_anti_robot,
)
from .texte import formater_prix, normaliser, texte_visible

# Mots autour desquels on affiche des extraits de page, pour choisir les bons
# mots_rupture / mots_stock d'une nouvelle boutique.
MOTS_DIAGNOSTIC = [
    "en stock", "rupture", "epuis", "indisponible", "sold out", "panier",
    "precommande", "prevenir", "bientot", "reapprovisionn", "disponible", "commander",
]
_RE_BRUT_DIAG = re.compile(
    r'.{0,70}(?:availability|in_?stock|outofstock|"stock|quantity"|indisponible|[ée]puis[ée]|rupture|dispo(?!nibilit)).{0,70}',
    re.IGNORECASE,
)


def etat_texte(dispo: bool | None) -> str:
    return "ERREUR" if dispo is None else ("EN STOCK" if dispo else "rupture")


def ligne_offre(o: Offre) -> str:
    drapeau = "" if o.langue in ("?", "fr") else f" [{o.langue.upper()}]"
    cher = f" (> plafond {formater_prix(o.prix_max)})" if o.trop_chere else ""
    return (
        f"    {'✅' if o.dispo else '⛔'} {o.item.nom:<38} {formater_prix(o.prix):>10}{cher}{drapeau}\n"
        f"       {o.titre[:90]}\n       {o.url}"
    )


def extraits(texte: str, mots: list[str], marge: int = 45, maximum: int = 14, par_mot: int = 2) -> list[str]:
    """Petits extraits du texte visible autour de chaque mot-clé."""
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


def diagnostiquer_boutique(b: Boutique, collection: Collection, langues: frozenset[str], details: bool = False) -> Analyse:
    analyse = analyser(b, collection, langues, decouvrir=True)
    dispo = sum(1 for o in analyse.offres if o.dispo and not o.trop_chere)
    lignes = [
        f"=== {b.nom} [{b.plateforme} → {b.detectee or '?'}] {len(analyse.offres)} fiche(s) 30 ans, "
        f"{dispo} en stock — {analyse.requetes} requête(s)",
        f"    {b.url}",
    ]
    if b.categories_trouvees:
        lignes.append(f"    catégories 30 ans : {', '.join(b.categories_trouvees)}")
    if b.presta_html:
        lignes.append("    PrestaShop sans recherche JSON : fiches lues une à une")
    for note in ([b.note] if b.note else []) + analyse.notes:
        lignes.append(f"    note : {note}")
    for erreur in analyse.erreurs:
        lignes.append(f"    ⚠️  {erreur}")
    for o in sorted(analyse.offres, key=lambda o: o.item.nom):
        lignes.append(ligne_offre(o))
    if details and analyse.autres:
        lignes.append(f"    hors gamme ({len(analyse.autres)}) :")
        for f in analyse.autres[:25]:
            lignes.append(f"      · {f.titre[:90]}  {formater_prix(f.prix)}")
    print("\n".join(lignes) + "\n", flush=True)
    return analyse


_RE_URL_FICHE = re.compile(r"\.html?$|/products?/|/produits?/|/p/|/dp/|\d{4,}", re.IGNORECASE)


def est_fiche(url: str) -> bool:
    """Adresse d'une fiche produit (et non d'une boutique entière) ?"""
    return bool(_RE_URL_FICHE.search(urlsplit(url).path))


def decouvrir(urls: list[str], collection: Collection, langues: frozenset[str],
              offre_produit: Callable[[Produit], Offre]) -> int:
    """Teste des boutiques (ou des fiches) inconnues et propose les lignes à copier.

    Adresse de boutique → boutiques.json ; adresse de fiche → produits.json.
    """
    boutiques: list[dict[str, object]] = []
    fiches: list[dict[str, object]] = []
    for url in urls:
        url = url.strip().rstrip("/")
        if not url.startswith("http"):
            url = "https://" + url
        if est_fiche(url):
            slug = re.sub(r"\.html?$|\d{4,}|[-_/]+", " ", urlsplit(url).path.rsplit("/", 1)[-1]).strip()
            produit = Produit(nom=slug or url, url=url, type="auto", boutique=domaine(url))
            offre = offre_produit(produit)
            diagnostiquer_produit(produit, offre)
            if offre.dispo is not None:
                fiches.append({"boutique": produit.boutique, "nom": offre.item.nom, "url": url,
                               "type": produit.type_detecte or offre.source})
            continue
        b = Boutique(nom=domaine(url), url=url)
        analyse = diagnostiquer_boutique(b, collection, langues, details=True)
        if b.detectee:
            entree: dict[str, object] = {"nom": b.nom, "url": b.url, "plateforme": b.detectee}
            if not analyse.offres:
                entree["note"] = "aucune fiche 30 ans trouvée lors du test"
            boutiques.append(entree)
    for fichier, lignes in (("boutiques.json", boutiques), ("produits.json", fiches)):
        if lignes:
            print(f"À ajouter dans {fichier} :")
            print(json.dumps(lignes, ensure_ascii=False, indent=2))
    return 0


def diagnostiquer_produit(produit: Produit, offre: Offre) -> None:
    """Affiche la vérification d'une fiche de produits.json et de quoi régler sa détection."""
    lignes = [
        f"=== {produit.boutique} · {produit.nom} [{produit.type} → {offre.source}] {etat_texte(offre.dispo)}  "
        f"{formater_prix(offre.prix)}  ({offre.item.nom})",
        f"    {produit.url}",
    ]
    if offre.detail:
        lignes.append(f"    détail : {offre.detail}")
    if offre.trop_chere:
        lignes.append(f"    💸 au-dessus du plafond {formater_prix(offre.prix_max)}")
    if offre.source in ("texte", "auto") or offre.dispo is None:
        try:
            page = telecharger_page(produit.url)
        except ErreurVerification as err:
            lignes.append(f"    page : {err}")
            page = ""
        if page:
            lignes += _indices_page(page, produit.url)
    print("\n".join(lignes) + "\n", flush=True)


def _indices_page(page: str, url: str) -> list[str]:
    texte = texte_visible(page)
    lignes = [f"    page : {len(page)} caractères, texte visible {len(texte)} caractères"]
    schema = disponibilite_schema(page)
    if schema:
        lignes.append(f"    schema.org : {schema}")
    if _RE_WEBSTORE.search(page):
        lignes.append("    indice : données Proximis (webStore.available) présentes")
    if _RE_PRESTASHOP.search(page):
        lignes.append('    indice : données PrestaShop présentes → type "prestashop"')
    raison = page_anti_robot(page, texte)
    if raison:
        lignes.append(f"    ⚠️  {raison}")
    if len(texte) < 1500:
        lignes.append(f"    texte visible : {texte[:600]!r}")
    for ident in sorted(set(re.findall(r"\d{4,}", urlsplit(url).path)), key=len, reverse=True)[:2]:
        montres = 0
        for m in re.finditer(re.escape(ident), page):
            ctx = " ".join(page[max(0, m.start() - 250): m.end() + 250].split())
            if not re.search(r"_id|stock|quantit|price|prix|dispo|avail", ctx, re.IGNORECASE):
                continue
            lignes.append(f"    #{ident} : {ctx}")
            montres += 1
            if montres >= 5:
                break
    apis: list[str] = []
    for m in re.finditer(r'["\'](/[^"\'\s<>]*(?:api|graphql)[^"\'\s<>]*|https?://[^"\'\s<>]*(?:api|graphql)[^"\'\s<>]*)["\']', page, re.IGNORECASE):
        if m.group(1) not in apis:
            apis.append(m.group(1))
        if len(apis) >= 8:
            break
    if apis:
        lignes.append("    api : " + " | ".join(apis))
    bruts: list[str] = []
    for m in _RE_BRUT_DIAG.finditer(page):
        extrait = " ".join(m.group(0).split())
        if extrait not in bruts:
            bruts.append(extrait)
        if len(bruts) >= 10:
            break
    lignes += [f"    ~ {e}" for e in bruts]
    if "shopify" in page.lower():
        lignes.append('    indice : la page mentionne Shopify → essaie type "shopify" ou ajoute la boutique dans boutiques.json')
    if "woocommerce" in page.lower() or "wp-content" in page.lower():
        lignes.append('    indice : WooCommerce/WordPress → essaie type "woocommerce" ou ajoute la boutique dans boutiques.json')
    lignes += [f"    · {e}" for e in extraits(texte, MOTS_DIAGNOSTIC)]
    return lignes


ENSEIGNES_CONNUES = [
    "amazon.", "fnac.", "cultura.", "micromania.", "leclerc", "cdiscount.", "carrefour.",
    "auchan.", "joueclub.", "king-jouet.", "smythstoys.", "rakuten.", "boulanger.", "darty.",
    "ldlc.", "lagranderecre.", "picwictoys.", "pokemoncenter.", "philibertnet.", "play-in.",
    "ultrajeux.", "shopify", "/products/", "/produit/", "/product/", ".html",
]


def lister_liens(url: str) -> int:
    """Affiche les liens marchands d'une page (comparateurs, articles « où acheter »)."""
    try:
        page = telecharger_page(url)
    except ErreurVerification as err:
        print(f"Impossible de lire {url} : {err}")
        return 1
    vus: list[str] = []
    redirections: list[str] = []  # liens internes de type /go/, /out/, affiliation…
    raccourcis: list[str] = []  # edcol.fr/xxxx, amzn.to/xxxx, bit.ly/xxxx…
    total = 0
    for m in re.finditer(r'(?:href|data-dest|data-href|data-url|data-link|data-out)\s*=\s*["\']([^"\'#]+)["\']', page, re.IGNORECASE):
        lien = html.unescape(m.group(1)).strip()
        if lien.startswith("/"):
            base = urlsplit(url)
            lien = urlunsplit((base.scheme, base.netloc, lien, "", ""))
        if not lien.startswith("http"):
            continue
        total += 1
        # Lien d'affiliation (awin, tradedoubler…) : la vraie URL est dans un paramètre.
        for param in re.findall(r"[?&](?:ued|url|u|dest|destination|redirect|r|link|to|target)=([^&]+)", lien, re.IGNORECASE):
            decode = unquote(param)
            if decode.startswith("http"):
                lien = decode
                break
        interne = urlsplit(lien).netloc == urlsplit(url).netloc
        if not interne and re.fullmatch(r"/[A-Za-z0-9_-]{3,12}/?", urlsplit(lien).path) and not any(e in lien.lower() for e in ENSEIGNES_CONNUES):
            if lien not in raccourcis:
                raccourcis.append(lien)
            continue
        if interne:
            if re.search(r"/(go|out|redirect|redir|aff|lien|link|track|click|deal|offre|buy|acheter)[/?-]", lien, re.IGNORECASE):
                if lien not in redirections:
                    redirections.append(lien)
            continue
        if any(e in lien.lower() for e in ENSEIGNES_CONNUES) and lien not in vus:
            vus.append(lien)
    # Suit les redirections internes (liens affiliés) et les raccourcisseurs.
    for lien in (redirections + raccourcis)[:40]:
        try:
            finale = telecharger(lien).url
        except ErreurVerification as err:
            finale = f"(échec : {err})"
        if finale.startswith("http") and urlsplit(finale).netloc != urlsplit(url).netloc:
            vus.append(f"{finale}   ← via {lien}")
    print(f"{total} lien(s) sur la page, {len(vus)} lien(s) marchand(s) trouvé(s) sur {url} :")
    for lien in vus:
        # Nettoie les paramètres de suivi pour obtenir une URL de fiche propre.
        print("  " + re.sub(r"[?&](utm_[a-z]+|tag|ref|affiliate|aff|awc|pid|cid|xtor|Origin)=[^&\s]*", "", lien))
    if not vus:
        hotes = sorted({urlsplit(html.unescape(m.group(1))).netloc for m in re.finditer(r'href\s*=\s*["\'](https?://[^"\'#]+)', page, re.IGNORECASE)})
        print("  aucun. Domaines liés depuis la page : " + ", ".join(hotes[:40]))
    return 0
