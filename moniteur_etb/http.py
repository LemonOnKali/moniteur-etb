"""Client HTTP minimal (urllib) avec nouvel essai et pause automatique par site.

Quand un site répond 429 / 403 / 503 (limite de débit, anti-robot) ou ne répond
pas, on le laisse tranquille un moment au lieu de le marteler : pause de 2 min,
doublée à chaque nouvel échec, 30 min au plus. Les autres sites continuent.
"""

from __future__ import annotations

import gzip
import json
import re
import threading
import time
import zlib
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

UA_NAVIGATEUR = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
)
ACCEPT_HTML = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
ACCEPT_JSON = "application/json,text/javascript;q=0.9,*/*;q=0.1"

TENTATIVES = 2
CODES_REESSAI = {500, 502, 503, 504}
CODES_PAUSE = {403, 429, 503}
PAUSE_MIN_S = 120.0
PAUSE_MAX_S = 1800.0

TIMEOUT_S = 15.0  # remplacé par Reglages.timeout_secondes au démarrage


class ErreurVerification(Exception):
    """Erreur propre à un produit ou une boutique : ne doit jamais faire planter le moniteur."""


class ErreurHTTP(ErreurVerification):
    def __init__(self, code: int, raison: str):
        super().__init__(f"HTTP {code} ({raison})")
        self.code = code


@dataclass
class Reponse:
    code: int
    corps: bytes
    charset: str
    url: str
    type: str

    def texte(self) -> str:
        try:
            return self.corps.decode(self.charset, errors="replace")
        except LookupError:
            return self.corps.decode("utf-8", errors="replace")

    def json(self) -> Any:
        try:
            return json.loads(self.texte())
        except json.JSONDecodeError as err:
            raise ErreurVerification("réponse non JSON") from err


class _Pauses:
    """Pauses par nom d'hôte, partagées entre les threads."""

    def __init__(self) -> None:
        self._verrou = threading.Lock()
        self._jusqua: dict[str, float] = {}
        self._duree: dict[str, float] = {}

    def restant(self, hote: str) -> float:
        with self._verrou:
            return max(0.0, self._jusqua.get(hote, 0.0) - time.monotonic())

    def echec(self, hote: str) -> float:
        with self._verrou:
            duree = min(PAUSE_MAX_S, self._duree.get(hote, PAUSE_MIN_S / 2) * 2)
            self._duree[hote] = duree
            self._jusqua[hote] = time.monotonic() + duree
            return duree

    def succes(self, hote: str) -> None:
        if hote in self._duree:
            with self._verrou:
                self._duree.pop(hote, None)
                self._jusqua.pop(hote, None)

    def vider(self) -> None:
        with self._verrou:
            self._jusqua.clear()
            self._duree.clear()


PAUSES = _Pauses()


def en_pause(url: str) -> bool:
    """Vrai si l'hôte de `url` est en pause : inutile d'essayer d'autres URL du même site."""
    return PAUSES.restant(urlsplit(url).hostname or "") > 0


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


def _entetes(accept: str, ajax: bool) -> dict[str, str]:
    entetes = {
        "User-Agent": UA_NAVIGATEUR,
        "Accept": accept,
        "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.7",
        "Accept-Encoding": "gzip, deflate",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    if ajax:
        entetes["X-Requested-With"] = "XMLHttpRequest"
        entetes["Sec-Fetch-Mode"] = "cors"
        entetes["Sec-Fetch-Dest"] = "empty"
    else:
        entetes.update({
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Sec-CH-UA": '"Chromium";v="141", "Not?A_Brand";v="8", "Google Chrome";v="141"',
            "Sec-CH-UA-Mobile": "?0",
            "Sec-CH-UA-Platform": '"Windows"',
        })
    return entetes


def telecharger(url: str, accept: str = "*/*", ajax: bool = False) -> Reponse:
    """Télécharge `url`. Réessaie une fois sur erreur réseau ou 5xx.

    Lève ErreurVerification avec un message lisible en cas d'échec, et met
    l'hôte en pause s'il signale une limite de débit ou un blocage.
    """
    hote = urlsplit(url).hostname or ""
    restant = PAUSES.restant(hote)
    if restant > 0:
        raise ErreurVerification(f"site en pause encore {restant / 60:.0f} min (limite de débit ou blocage)")

    derniere: Exception | None = None
    for tentative in range(1, TENTATIVES + 1):
        try:
            requete = Request(url, headers=_entetes(accept, ajax))
            with urlopen(requete, timeout=TIMEOUT_S) as rep:
                corps = _decompresser(rep.read(), rep.headers.get("Content-Encoding", ""))
                PAUSES.succes(hote)
                return Reponse(
                    code=rep.status,
                    corps=corps,
                    charset=rep.headers.get_content_charset() or "utf-8",
                    url=rep.geturl(),
                    type=(rep.headers.get_content_type() or "").lower(),
                )
        except HTTPError as err:
            if err.code in CODES_REESSAI and tentative < TENTATIVES:
                derniere = err
                time.sleep(1.5 * tentative)
                continue
            if err.code in CODES_PAUSE:
                duree = PAUSES.echec(hote)
                raise ErreurHTTP(err.code, f"{err.reason} — pause {duree / 60:.0f} min") from err
            raise ErreurHTTP(err.code, str(err.reason)) from err
        except (URLError, TimeoutError, OSError, EOFError, zlib.error) as err:  # réseau, DNS, TLS…
            derniere = err
            if tentative < TENTATIVES:
                time.sleep(1.0 * tentative)
                continue
    raison = getattr(derniere, "reason", None) or derniere
    # Site injoignable : inutile de le réinterroger à chaque requête du cycle.
    duree = PAUSES.echec(hote)
    raise ErreurVerification(f"réseau : {raison} — pause {duree / 60:.0f} min")


def telecharger_json(url: str, ajax: bool = False) -> Any:
    reponse = telecharger(url, accept=ACCEPT_JSON, ajax=ajax)
    try:
        return reponse.json()
    except ErreurVerification:
        raise ErreurVerification("réponse non JSON (API absente, boutique protégée ou URL incorrecte ?)") from None


def telecharger_page(url: str) -> str:
    """Télécharge une page HTML. Lève une erreur si le site redirige vers une autre
    fiche (produit retiré → page catégorie, par exemple)."""
    reponse = telecharger(url, accept=ACCEPT_HTML)
    if redirection_suspecte(url, reponse.url):
        raise ErreurVerification(f"redirigé vers {reponse.url} (fiche retirée ?)")
    return reponse.texte()


def redirection_suspecte(url_demandee: str, url_finale: str) -> bool:
    """Vrai si la redirection change de page (les identifiants numériques de l'URL
    d'origine ont disparu), et pas seulement de forme (http → https, www, slash)."""
    chemin_avant = urlsplit(url_demandee).path.rstrip("/")
    chemin_apres = urlsplit(url_finale).path.rstrip("/")
    if chemin_avant == chemin_apres:
        return False
    identifiants = re.findall(r"\d{4,}", chemin_avant)
    if identifiants:
        return not all(i in chemin_apres for i in identifiants)
    return not chemin_apres.startswith(chemin_avant) and not chemin_avant.startswith(chemin_apres)
