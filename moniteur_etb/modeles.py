"""Structures partagées : une offre = un produit 30 ans dans une boutique."""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlsplit

from .collection import Item


def cle_url(url: str) -> str:
    """Identifiant stable d'une fiche : hôte sans www + chemin, sans paramètres."""
    parts = urlsplit(url.strip())
    hote = (parts.hostname or "").lower().removeprefix("www.")
    return f"{hote}{parts.path.rstrip('/')}".lower()


@dataclass
class Resultat:
    """Résultat brut d'une vérification. `dispo` vaut None en cas d'erreur."""

    dispo: bool | None
    prix: float | None = None  # en euros
    detail: str = ""  # variante disponible, message d'erreur, indice de détection…
    source: str = ""  # méthode effectivement utilisée (shopify, prestashop, texte…)
    image: str | None = None
    quantite: int | None = None
    titre: str | None = None


@dataclass
class Fiche:
    """Une fiche produit trouvée dans le catalogue d'une boutique."""

    cle: str
    url: str
    titre: str
    dispo: bool
    prix: float | None = None
    image: str | None = None
    quantite: int | None = None
    detail: str = ""
    ref: str = ""  # identifiant propre à la plateforme (handle Shopify, id WooCommerce…)
    dans_categorie: bool = False  # vient d'une catégorie « 30 ans » de la boutique


@dataclass
class Offre:
    """Fiche classée dans la gamme, prête pour la décision d'alerte."""

    cle: str
    boutique: str
    titre: str
    url: str
    item: Item
    langue: str = "?"
    dispo: bool | None = None
    prix: float | None = None
    prix_max: float | None = None
    image: str | None = None
    quantite: int | None = None
    detail: str = ""
    source: str = ""
    erreur: str = ""
    extras: dict[str, str] = field(default_factory=dict)

    @property
    def trop_chere(self) -> bool:
        return bool(self.dispo and self.prix_max is not None and self.prix is not None and self.prix > self.prix_max)
