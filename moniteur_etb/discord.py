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


# Salons du serveur : chaque type d'alerte peut avoir son webhook (DISCORD_WEBHOOK_UPC…).
# Un salon sans webhook retombe sur DISCORD_WEBHOOK.
SALONS = {
    "upc": "UPC (Ultra-Premium) en ligne",
    "etb": "ETB (Coffret Dresseur d'Élite) en ligne",
    "magasins": "stock en magasin autour de la zone",
    "autres": "reste de la gamme 30 ans en ligne",
    "journal": "lancement du moniteur, résumé, sources en erreur",
}


def salon_offre(offre: Offre) -> str:
    """Salon d'une alerte : magasins, upc, etb ou autres."""
    if offre.source == "magasin":
        return "magasins"
    if offre.item.id.startswith("upc"):
        return "upc"
    if offre.item.id.startswith("etb"):
        return "etb"
    return "autres"


def _log(message: str) -> None:
    print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {message}", flush=True)


class Discord:
    def __init__(self, webhook: str, mention: str = "", timeout: float = 15.0, salons: dict[str, str] | None = None):
        self.defaut = webhook
        self.salons = {k: v for k, v in (salons or {}).items() if v}  # salon → webhook propre
        self.mention = mention
        self.timeout = timeout
        self.dernier_code = 0  # code HTTP de la dernière réponse de Discord

    @property
    def webhook(self) -> str:
        """Un webhook est configuré (salon par défaut ou au moins un salon dédié)."""
        return self.defaut or next(iter(self.salons.values()), "")

    def url(self, salon: str = "") -> str:
        return self.salons.get(salon) or self.defaut

    def poster(self, charge: dict[str, Any], salon: str = "") -> bool:
        """Envoie une charge JSON au webhook du salon. Gère le rate-limit Discord (429).

        Webhook du salon supprimé ou invalide (401/404) : le message part dans le
        salon par défaut plutôt que d'être perdu.
        """
        url = self.url(salon)
        ok = self._poster(url, charge)
        if not ok and url != self.defaut and self.defaut and self.dernier_code in (401, 404):
            _log(f"Discord : webhook du salon « {salon} » invalide, message envoyé dans le salon par défaut")
            ok = self._poster(self.defaut, charge)
        return ok

    def _poster(self, url: str, charge: dict[str, Any]) -> bool:
        if not url:
            _log(f"(DISCORD_WEBHOOK absent, message non envoyé) {charge.get('content', '')!r}")
            return False
        corps = json.dumps(charge).encode("utf-8")
        entetes = {"Content-Type": "application/json", "User-Agent": UA_DISCORD}
        for tentative in range(1, 5):
            try:
                requete = Request(url, data=corps, headers=entetes, method="POST")
                with urlopen(requete, timeout=self.timeout) as reponse:
                    self.dernier_code = reponse.status
                    if 200 <= reponse.status < 300:
                        return True
                    _log(f"Discord : réponse inattendue HTTP {reponse.status}")
            except HTTPError as err:
                self.dernier_code = err.code
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

    def texte(self, contenu: str, mention: bool = False, salon: str = "") -> bool:
        if mention and self.mention:
            contenu = f"{self.mention} {contenu}"
        return self.poster({"content": contenu[:2000], "allowed_mentions": {"parse": ["everyone", "roles", "users"]}}, salon)

    def embeds(self, contenu: str, embeds: list[dict[str, Any]], mention: bool = False, salon: str = "") -> list[bool]:
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
            ok = self.poster(charge, salon)
            if not ok and self.dernier_code == 400:
                # Discord refuse le message (image ou lien invalide) : on renvoie sans image
                # plutôt que de perdre l'alerte.
                charge["embeds"] = [{k: v for k, v in e.items() if k not in ("thumbnail", "image")} for e in paquet]
                ok = self.poster(charge, salon)
            resultats += [ok] * len(paquet)
        return resultats


def _taille(embed: dict[str, Any]) -> int:
    total = len(embed.get("title", "")) + len(embed.get("description", ""))
    total += len((embed.get("footer") or {}).get("text", "")) + len((embed.get("author") or {}).get("name", ""))
    total += sum(len(f.get("name", "")) + len(f.get("value", "")) for f in embed.get("fields") or [])
    return total


def _horodatage() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def embed_magasin(offre: Offre) -> dict[str, Any]:
    """Carte Discord d'un produit qui arrive en stock dans un magasin de la zone."""
    x = offre.extras
    champs = [
        {"name": "🏬 Magasin", "value": f"{x.get('enseigne', '')} {x.get('magasin', '')}".strip()[:100], "inline": True},
        {"name": "📦 Stock", "value": f"{offre.quantite} en magasin" if offre.quantite else "en stock", "inline": True},
        {"name": "🚗 Distance", "value": x.get("distance", "?"), "inline": True},
        {"name": "📍 Adresse", "value": (x.get("adresse") or "?")[:200], "inline": False},
    ]
    return {
        "title": f"🏬 {offre.item.emoji} {offre.item.nom} en magasin"[:256],
        "url": offre.url,
        "description": f"**[{offre.titre[:200]}]({offre.url})**\nDisponible en retrait magasin : réserve en ligne ou passe en boutique.",
        "color": VERT,
        "fields": champs,
        "footer": {"text": f"stock magasin indiqué par l'enseigne · moniteur 30 ans v{VERSION}"},
        "timestamp": _horodatage(),
    }


def embed_offre(offre: Offre, nouvelle: bool) -> dict[str, Any]:
    """Carte Discord d'une offre qui vient de passer en stock."""
    if offre.source == "magasin":
        return embed_magasin(offre)
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
    if offre.image and offre.image.startswith(("https://", "http://")) and len(offre.image) < 1500:
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
    if premiere.source == "magasin":
        quantite = f" ({premiere.quantite} pièce(s))" if premiere.quantite else ""
        texte = f"🚨 **{premiere.item.nom}** en stock **en magasin** chez **{premiere.boutique}**{quantite}"
    else:
        texte = f"🚨 **{premiere.item.nom}** en stock chez **{premiere.boutique}**" + (f" à {prix}" if prix else "")
    if len(alertes) > 1:
        autres = ", ".join(f"{o.item.nom} ({o.boutique})" for o in alertes[1:4])
        texte += f" — et aussi : {autres}" + (" …" if len(alertes) > 4 else "")
    return texte
