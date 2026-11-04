"""Sonde temporaire : affiche ce qu'une page expose sur le stock en magasin.

python outils/sonde.py URL [URL...]  (une URL « json: » affiche la réponse JSON brute)
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from moniteur_etb import http  # noqa: E402

MOTS = re.compile(r"magasin|store|inventory|pickup|retrait|click|stock|availability|drive", re.I)
URLS = re.compile(r"""(?:https?://[^\s"'<>\\]+|/[A-Za-z0-9_\-./]*(?:demandware\.store|/api/|Stores?-|magasin|store|stock|inventory|pickup)[^\s"'<>\\]*)""", re.I)


def sonder(url: str) -> None:
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
            import json
            donnees = json.loads(texte)

            def nettoyer(x):
                if isinstance(x, dict):
                    return {k: nettoyer(v) for k, v in x.items() if k not in {"storeHours", "lunchHours", "csrf", "storeSpecialDays"}}
                if isinstance(x, list):
                    return [nettoyer(v) for v in x]
                if isinstance(x, str) and len(x) > 1500:
                    return x[:1500] + "…"
                return x
            print(json.dumps(nettoyer(donnees), ensure_ascii=False)[:15000])
        except ValueError:
            print(texte[:6000])
        return
    if "javascript" in rep.type or url.endswith(".js"):
        for ligne in texte.splitlines():
            if re.search(r"url|ajax|Action|http|REST|stock|store", ligne, re.I):
                print("   ", ligne.strip()[:240])
        return
    pids = sorted(set(re.findall(r'data-pid="([^"]+)"', texte)))
    if pids:
        print(f"-- data-pid : {pids[:80]}")
    for cle in ("availableinstore",):
        i = texte.find(f'"id":"{cle}"')
        if i >= 0:
            print(f"-- bloc {cle} :", texte[i:i + 12000])
    urls = sorted({u for u in URLS.findall(texte) if MOTS.search(u) and not u.endswith((".png", ".jpg", ".svg", ".webp", ".css", ".woff2"))})
    print(f"-- {len(urls)} URL(s) liées au stock/magasin :")
    for u in urls[:120]:
        print("   ", u[:220])
    print("-- extraits « magasin » :")
    vus = 0
    for m in re.finditer(r"magasin|en stock|retrait|storeId|store_id|inventory", texte, re.I):
        extrait = re.sub(r"\s+", " ", texte[max(0, m.start() - 160): m.end() + 160])
        print("   …", extrait, "…")
        vus += 1
        if vus >= 25:
            break


if __name__ == "__main__":
    for u in sys.argv[1:]:
        sonder(u)
