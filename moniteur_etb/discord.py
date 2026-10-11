"""Envoi Discord par webhook : messages enrichis (embeds) groupés par 10.

Le texte du message (`content`) reprend l'essentiel pour que la notification
du téléphone soit lisible sans ouvrir Discord.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from . import VERSION
from .modeles import Offre
from .texte import formater_prix

UA_DISCORD = f"MoniteurStock/{VERSION} (+https://github.com/lemononkali/moniteur-etb)"
VERT, ROUGE, BLEU, ORANGE = 0x2ECC71, 0xE74C3C, 0x3498DB, 0xF39C12
DRAPEAUX = {"fr": "🇫🇷 FR", "en": "🇬🇧 EN", "jp": "🇯🇵 JP", "kr": "🇰🇷 KR", "cn": "🇨🇳 CN"}
MAX_EMBEDS = 10  # limite Discord par message
MAX_CARACTERES_EMBEDS = 5800  # limite Discord : 6000 pour l'ensemble des embeds d'un message


def _log(message: str) -> None:
    print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {message}", flush=True)


class Discord:
    def __init__(self, webhook: str, mention: str = "", timeout: float = 15.0):
        self.webhook = webhook
        self.mention = mention
        self.timeout = timeout

    def poster(self, charge: dict[str, Any]) -> bool:
        """Envoie une charge JSON au webhook. Gère le rate-limit Discord (429)."""
        if not self.webhook:
            _log(f"(DISCORD_WEBHOOK absent, message non envoyé) {charge.get('content', '')!r}")
            return False
        corps = json.dumps(charge).encode("utf-8")
        entetes = {"Content-Type": "application/json", "User-Agent": UA_DISCORD}
        for tentative in range(1, 5):
            try:
                requete = Request(self.webhook, data=corps, headers=entetes, method="POST")
                with urlopen(requete, timeout=self.timeout) as reponse:
                    if 200 <= reponse.status < 300:
                        return True
                    _log(f"Discord : réponse inattendue HTTP {reponse.status}")
            except HTTPError as err:
                if err.code == 429:
                    attente = 2.0
                    try:
                        attente = float(json.loads(err.read().decode("utf-8", "replace")).get("retry_after", attente))
                    except Exception:
                        attente = float(err.headers.get("Retry-After", attente) or attente)
                    _log(f"Discord : rate-limit, nouvel essai dans {attente:.1f} s")
                    time.sleep(min(attente, 30.0) + 0.25)
                    continue
                detail = ""
                try:
                    detail = err.read().decode("utf-8", "replace")[:300]
                except Exception:
                    pass
                _log(f"Discord : erreur HTTP {err.code} ({err.reason}) {detail}")
                if 400 <= err.code < 500:
                    return False
            except (URLError, TimeoutError, OSError) as err:
                _log(f"Discord : erreur réseau {getattr(err, 'reason', err)}")
            time.sleep(1.5 * tentative)
        return False

    def texte(self, contenu: str, mention: bool = False) -> bool:
        if mention and self.mention:
            contenu = f"{self.mention} {contenu}"
        return self.poster({"content": contenu[:2000], "allowed_mentions": {"parse": ["everyone", "roles", "users"]}})

    def embeds(self, contenu: str, embeds: list[dict[str, Any]], mention: bool = False) -> list[bool]:
        """Envoie des embeds par paquets (10 par message, 6000 caractères au plus).

        Renvoie, pour chaque embed, si son message est bien parti.
        """
        paquets: list[list[dict[str, Any]]] = [[]]
        taille = 0
        for e in embeds:
            t = _taille(e)
            if paquets[-1] and (len(paquets[-1]) >= MAX_EMBEDS or taille + t > MAX_CARACTERES_EMBEDS):
                paquets.append([])
                taille = 0
            paquets[-1].append(e)
            taille += t
        resultats: list[bool] = []
        for i, paquet in enumerate(paquets):
            texte = contenu if i == 0 else ""
            if mention and self.mention and i == 0:
                texte = f"{self.mention} {texte}".strip()
            charge: dict[str, Any] = {
                "embeds": paquet,
                "allowed_mentions": {"parse": ["everyone", "roles", "users"] if mention else []},
            }
            if texte:
                charge["content"] = texte[:2000]
            resultats += [self.poster(charge)] * len(paquet)
        return resultats


def _taille(embed: dict[str, Any]) -> int:
    total = len(embed.get("title", "")) + len(embed.get("description", ""))
    total += len((embed.get("footer") or {}).get("text", "")) + len((embed.get("author") or {}).get("name", ""))
    total += sum(len(f.get("name", "")) + len(f.get("value", "")) for f in embed.get("fields") or [])
    return total


def _horodatage() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def embed_offre(offre: Offre, nouvelle: bool) -> dict[str, Any]:
    """Carte Discord d'une offre qui vient de passer en stock."""
    prix = formater_prix(offre.prix) or "prix non lu"
    champs = [
        {"name": "💶 Prix", "value": prix, "inline": True},
        {"name": "🏪 Boutique", "value": offre.boutique[:100], "inline": True},
    ]
    if offre.langue in DRAPEAUX:
        champs.append({"name": "🌐 Langue", "value": DRAPEAUX[offre.langue], "inline": True})
    if offre.quantite:
        champs.append({"name": "📊 Stock", "value": f"{offre.quantite} restant(s)", "inline": True})
    if offre.detail.startswith("variante"):
        champs.append({"name": "🎯 Variantes", "value": offre.detail.removeprefix("variante(s) : ")[:200], "inline": False})
    embed: dict[str, Any] = {
        "title": f"{offre.item.emoji} {offre.item.nom}"[:256],
        "url": offre.url,
        "description": f"**[{offre.titre[:200]}]({offre.url})**\n{'🆕 Nouvelle fiche' if nouvelle else '🔁 Retour en stock'}",
        "color": VERT,
        "fields": champs,
        "footer": {"text": f"{offre.source} · moniteur 30 ans v{VERSION}"},
        "timestamp": _horodatage(),
    }
    if offre.image:
        embed["thumbnail"] = {"url": offre.image}
    return embed


def embed_rupture(offre: Offre) -> dict[str, Any]:
    return {
        "title": f"⛔ Rupture : {offre.item.nom}"[:256],
        "url": offre.url,
        "description": f"{offre.boutique} — {offre.titre[:200]}",
        "color": ROUGE,
        "timestamp": _horodatage(),
    }


def resume_alertes(alertes: list[Offre]) -> str:
    """Texte court de la notification : « 🚨 ETB 30 ans — LorenZone 69,90 € (+2 autres) »."""
    premiere = alertes[0]
    prix = formater_prix(premiere.prix)
    texte = f"🚨 **{premiere.item.nom}** en stock chez **{premiere.boutique}**" + (f" à {prix}" if prix else "")
    if len(alertes) > 1:
        autres = ", ".join(f"{o.item.nom} ({o.boutique})" for o in alertes[1:4])
        texte += f" — et aussi : {autres}" + (" …" if len(alertes) > 4 else "")
    return texte
