"""Sonde temporaire : affiche ce qu'une page expose sur le stock en magasin.

Lignes de outils/sonde-urls.txt :
  [json:]URL [|| motif]   page (ou JSON) et, en option, extraits autour d'un motif
  pause N                 attendre N secondes (sites qui limitent le débit)
"""
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from moniteur_etb import http  # noqa: E402

MOTS = re.compile(r"magasin|store|inventory|pickup|retrait|click|stock|availability|drive|ajax|api", re.I)
URLS = re.compile(r"""(?:https?://[^\s"'<>\\]+|/[A-Za-z0-9_\-./]*(?:demandware\.store|/api/|ajax|Stores?-|magasin|store|stock|inventory|pickup)[^\s"'<>\\]*)""", re.I)


def texte_brut(html: str) -> str:
    html = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S | re.I)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def extraits(texte: str, motif: str, n: int = 25, large: int = 200) -> None:
    if motif == "tout":
        print(texte[:9000])
        return
    if motif.startswith("uniq:"):
        trouves = sorted(set(re.findall(motif[5:], texte, re.I)))
        print(f"-- {len(trouves)} correspondance(s) uniques /{motif[5:]}/ :")
        for t in trouves[:150]:
            print("   ", str(t)[:300])
        return
    if motif.startswith("large:"):
        _, large_txt, motif = motif.split(":", 2)
        large = int(large_txt)
    print(f"-- extraits /{motif}/ :")
    for i, m in enumerate(re.finditer(motif, texte, re.I)):
        if i >= n:
            break
        print("   …", re.sub(r"\s+", " ", texte[max(0, m.start() - large): m.end() + large]), "…")


def nettoyer(x):
    if isinstance(x, dict):
        return {k: nettoyer(v) for k, v in x.items() if k not in {"storeHours", "lunchHours", "csrf", "storeSpecialDays", "locations"}}
    if isinstance(x, list):
        return [nettoyer(v) for v in x]
    if isinstance(x, str) and len(x) > 600:
        return x[:600] + "…"
    return x


DERNIERS_PIDS: list[str] = []


def sonder(ligne: str) -> None:
    url, _, motif = (p.strip() for p in ligne.partition("||"))
    if "{pid}" in url:
        for pid in [p for p in DERNIERS_PIDS if p.isdigit()][:3]:
            sonder(ligne.replace("{pid}", pid))
            time.sleep(8)
        return
    brut = url.startswith("json:")
    url = url.removeprefix("json:")
    print(f"\n######## {url}")
    try:
        rep = http.telecharger(url, accept=http.ACCEPT_JSON if brut else http.ACCEPT_HTML, ajax=brut, pause=False)
    except Exception as err:  # noqa: BLE001
        print(f"ERREUR {err}")
        return
    texte = rep.texte()
    print(f"code={rep.code} type={rep.type} final={rep.url} taille={len(texte)}")
    if brut or rep.type.endswith("json"):
        try:
            donnees = json.loads(texte)
        except ValueError:
            print(texte[:4000])
            return
        html = donnees.get("storesResultsHtml") if isinstance(donnees, dict) else None
        print(json.dumps(nettoyer(donnees), ensure_ascii=False)[:8000])
        if html:
            print("-- storesResultsHtml (texte) :", texte_brut(html)[:6000])
            extraits(html, r"stock|dispo|availab|quantit", n=30, large=250)
        if motif:
            extraits(texte, motif)
        return
    if "javascript" in rep.type or url.endswith(".js"):
        extraits(texte, motif or r"https?://|/api/|fetch\(|ajax", n=60, large=150)
        return
    urls = sorted({u for u in URLS.findall(texte) if MOTS.search(u) and not u.endswith((".png", ".jpg", ".svg", ".webp", ".css", ".woff2"))})
    print(f"-- {len(urls)} URL(s) :")
    for u in urls[:150]:
        print("   ", u[:220])
    pids = sorted(set(re.findall(r'data-pid="([^"]+)"', texte)))
    if pids:
        print(f"-- data-pid : {pids[:80]}")
        DERNIERS_PIDS[:] = pids
    if motif:
        extraits(texte, motif)


if __name__ == "__main__":
    fichier = Path(__file__).with_name("sonde-urls.txt")
    for ligne in fichier.read_text(encoding="utf-8").splitlines():
        ligne = ligne.strip()
        if not ligne or ligne.startswith("#"):
            continue
        if ligne.startswith("pause "):
            time.sleep(float(ligne.split()[1]))
            continue
        sonder(ligne)
