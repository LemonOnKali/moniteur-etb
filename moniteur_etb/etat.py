"""État persistant (etat.json) : dernière dispo / prix / alerte de chaque offre.

Conservé entre deux exécutions par le cache GitHub Actions : une alerte ne part
qu'au passage en stock, jamais deux fois pour la même offre.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

OUBLI_JOURS = 14  # une offre plus vue depuis ce délai sort du fichier


def charger(chemin: str) -> dict[str, dict[str, Any]]:
    try:
        with open(chemin, encoding="utf-8") as f:
            donnees = json.load(f)
        if isinstance(donnees, dict):
            return {k: v for k, v in donnees.items() if isinstance(v, dict)}
    except FileNotFoundError:
        pass
    except (OSError, json.JSONDecodeError) as err:
        print(f"État précédent illisible ({err}), on repart de zéro", flush=True)
    return {}


def sauvegarder(chemin: str, etat: dict[str, dict[str, Any]]) -> None:
    """Écriture atomique (fichier temporaire puis renommage)."""
    limite = datetime.now(timezone.utc) - timedelta(days=OUBLI_JOURS)
    garde = {}
    for cle, valeur in etat.items():
        try:
            vu = datetime.fromisoformat(str(valeur.get("maj") or valeur.get("vu")))
        except ValueError:
            vu = None
        if vu is None or vu >= limite:
            garde[cle] = valeur
    temporaire = chemin + ".tmp"
    try:
        with open(temporaire, "w", encoding="utf-8") as f:
            json.dump(garde, f, ensure_ascii=False, indent=1, sort_keys=True)
        os.replace(temporaire, chemin)
    except OSError as err:
        print(f"Impossible d'écrire {chemin} : {err}", flush=True)
