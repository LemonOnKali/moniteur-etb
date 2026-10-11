"""Réglages lus dans les variables d'environnement (ou variables de dépôt GitHub)."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _nombre(nom: str, defaut: float) -> float:
    brut = (os.environ.get(nom) or "").strip().replace(",", ".")
    try:
        return float(brut) if brut else defaut
    except ValueError:
        return defaut


def _booleen(nom: str) -> bool:
    return (os.environ.get(nom) or "").strip().lower() in {"1", "true", "oui", "yes", "on"}


@dataclass
class Reglages:
    discord_webhook: str = ""
    discord_mention: str = ""
    duree_minutes: float = 20.0
    intervalle_secondes: float = 30.0
    decouverte_minutes: float = 15.0  # nouvelle recherche des fiches 30 ans dans chaque boutique
    timeout_secondes: float = 15.0
    prix_max: float | None = None  # plafond global, si ni le produit ni la catégorie n'en ont
    anti_spam_minutes: float = 10.0
    alerte_rupture: bool = False
    langues: frozenset[str] = frozenset({"fr"})  # langues de cartes acceptées (fr, en, jp…)
    fichier_produits: str = "produits.json"
    fichier_boutiques: str = "boutiques.json"
    fichier_collection: str = "collection.json"
    fichier_etat: str = "etat.json"
    evenement_github: str = ""
    max_workers: int = 16

    @classmethod
    def depuis_env(cls) -> "Reglages":
        langues = {l.strip().lower() for l in (os.environ.get("LANGUES") or "fr").split(",") if l.strip()}
        return cls(
            discord_webhook=(os.environ.get("DISCORD_WEBHOOK") or "").strip(),
            discord_mention=(os.environ.get("DISCORD_MENTION") or "").strip(),
            duree_minutes=_nombre("DUREE_MINUTES", 20.0),
            intervalle_secondes=max(5.0, _nombre("INTERVALLE_SECONDES", 30.0)),
            decouverte_minutes=max(1.0, _nombre("DECOUVERTE_MINUTES", 15.0)),
            timeout_secondes=max(3.0, _nombre("TIMEOUT_SECONDES", 15.0)),
            prix_max=_nombre("PRIX_MAX", 0.0) or None,
            anti_spam_minutes=_nombre("ANTI_SPAM_MINUTES", 10.0),
            alerte_rupture=_booleen("ALERTE_RUPTURE"),
            langues=frozenset(langues or {"fr"}),
            fichier_produits=os.environ.get("FICHIER_PRODUITS", "produits.json"),
            # Variable vide = aucune boutique (ex. runner du PC qui ne surveille que les enseignes).
            fichier_boutiques=os.environ.get("FICHIER_BOUTIQUES", "boutiques.json"),
            fichier_collection=os.environ.get("FICHIER_COLLECTION", "collection.json"),
            fichier_etat=os.environ.get("FICHIER_ETAT", "etat.json"),
            evenement_github=os.environ.get("GITHUB_EVENT_NAME", ""),
            max_workers=int(_nombre("MAX_WORKERS", 16)),
        )
