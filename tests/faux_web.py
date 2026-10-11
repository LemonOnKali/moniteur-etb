"""Faux web pour les tests : associe des morceaux d'URL à des réponses JSON."""

from __future__ import annotations

import json
from typing import Any
from unittest import mock

from moniteur_etb.http import ErreurHTTP, Reponse


class FauxWeb:
    def __init__(self, routes: dict[str, Any]):
        self.routes = routes  # sous-chaîne d'URL → objet JSON (ou exception)
        self.appels: list[str] = []

    def _trouver(self, url: str) -> Any:
        self.appels.append(url)
        for morceau, reponse in self.routes.items():
            if morceau in url:
                if isinstance(reponse, Exception):
                    raise reponse
                return reponse
        raise ErreurHTTP(404, "Not Found")

    def telecharger_json(self, url: str, ajax: bool = False, pause: bool = True) -> Any:
        return self._trouver(url)

    def telecharger(self, url: str, accept: str = "*/*", ajax: bool = False, pause: bool = True) -> Reponse:
        corps = self._trouver(url)
        texte = corps if isinstance(corps, str) else json.dumps(corps)
        return Reponse(code=200, corps=texte.encode(), charset="utf-8", url=url, type="text/html")

    def actif(self):
        return mock.patch.multiple(
            "moniteur_etb.boutiques", telecharger_json=self.telecharger_json, telecharger=self.telecharger
        )
