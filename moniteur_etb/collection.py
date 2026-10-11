"""Gamme surveillée (collection.json) : reconnaître un produit 30 ans et le classer.

Un titre de fiche (« Coffret Dresseur d'Élite Pokémon 30ᵉ Anniversaire FR ») est
ramené à des mots simples (« coffret dresseur d elite pokemon 30e anniversaire fr »)
puis comparé aux règles :

- `marqueurs` : le titre appartient à la gamme (30e anniversaire, 30 ans, ME05.5…) ;
- `exclusions` : autres jeux, cartes à l'unité, accessoires… → ignoré ;
- `items` : le premier item dont un des motifs correspond donne la catégorie
  (ETB, UPC, Bundle…), son nom affiché, son prix plafond anti-spéculateurs et
  son prix plancher (une « protection acrylique ETB » à 15 € n'est pas un ETB).

Un motif est une suite de mots ; « a + b » exige les deux, dans n'importe quel ordre.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from .texte import mots

LANGUES_CONNUES = ("fr", "en", "jp", "kr", "cn")

# Repérage de la langue des cartes dans le titre (déjà passé par texte.mots).
_RE_LANGUES = {
    "jp": re.compile(r"\b(japonais|japonaise|japanese|japan|japon|jap|jpn|jp)\b"),
    "kr": re.compile(r"\b(coreen|coreenne|korean|kor|kr)\b"),
    "cn": re.compile(r"\b(chinois|chinoise|chinese|s chinese|t chinese|simplified|traditional|cn)\b"),
    "en": re.compile(r"\b(anglais|anglaise|english|eng|version en|en version|vo|uk|us)\b|\ben$"),
    "fr": re.compile(r"\b(francais|francaise|french|fra|vf|fr)\b"),
}
# Numéro de carte (« 025/196 ») : c'est une carte à l'unité, pas un produit scellé.
_RE_NUMERO_CARTE = re.compile(r"\b\d{1,3}\s*/\s*\d{2,3}\b")


def _compiler_motif(motif: str) -> list[re.Pattern[str]]:
    morceaux = [mots(m) for m in str(motif).split("+")]
    return [re.compile(rf"(?<![a-z0-9]){re.escape(m)}(?![a-z0-9])") for m in morceaux if m]


def _correspond(motifs: list[list[re.Pattern[str]]], texte: str) -> bool:
    return any(motif and all(p.search(texte) for p in motif) for motif in motifs)


@dataclass
class Item:
    id: str
    nom: str
    emoji: str = "📦"
    prix_max: float | None = None
    prix_min: float | None = None  # en dessous, ce n'est pas ce produit (protection, carte seule…)
    motifs: list[list[re.Pattern[str]]] = field(default_factory=list)
    exclure: list[list[re.Pattern[str]]] = field(default_factory=list)

    def correspond(self, texte: str) -> bool:
        return _correspond(self.motifs, texte) and not _correspond(self.exclure, texte)

    def prix_plausible(self, prix: float | None) -> bool:
        return prix is None or self.prix_min is None or prix >= self.prix_min


@dataclass
class Classement:
    item: Item
    langue: str  # fr, en, jp… ; "?" si le titre ne le dit pas


@dataclass
class Collection:
    nom: str = "Pokémon 30e Anniversaire"
    recherches: list[str] = field(default_factory=lambda: ["30e anniversaire", "30 ans"])
    marqueurs: list[re.Pattern[str]] = field(default_factory=list)
    exclusions: list[list[re.Pattern[str]]] = field(default_factory=list)
    items: list[Item] = field(default_factory=list)
    item_defaut: Item = field(default_factory=lambda: Item(id="autre", nom="Produit 30 ans", emoji="✨"))

    @classmethod
    def depuis_dict(cls, brut: dict[str, Any]) -> "Collection":
        items: list[Item] = []
        for i, b in enumerate(brut.get("items") or []):
            if not isinstance(b, dict) or not b.get("id") or not b.get("motifs"):
                raise ValueError(f"item n°{i + 1} : 'id' et 'motifs' sont obligatoires")
            items.append(Item(
                id=str(b["id"]),
                nom=str(b.get("nom") or b["id"]),
                emoji=str(b.get("emoji") or "📦"),
                prix_max=float(b["prix_max"]) if b.get("prix_max") is not None else None,
                prix_min=float(b["prix_min"]) if b.get("prix_min") is not None else None,
                motifs=[_compiler_motif(m) for m in b["motifs"]],
                exclure=[_compiler_motif(m) for m in b.get("exclure") or []],
            ))
        defaut = brut.get("item_defaut") or {}
        return cls(
            nom=str(brut.get("nom") or cls.nom),
            recherches=[str(r) for r in brut.get("recherches") or ["30e anniversaire", "30 ans"]],
            marqueurs=[re.compile(str(m)) for m in brut.get("marqueurs") or []],
            exclusions=[_compiler_motif(m) for m in brut.get("exclusions") or []],
            items=items,
            item_defaut=Item(
                id="autre",
                nom=str(defaut.get("nom") or "Produit 30 ans"),
                emoji=str(defaut.get("emoji") or "✨"),
                prix_max=float(defaut["prix_max"]) if defaut.get("prix_max") is not None else None,
            ),
        )

    @classmethod
    def charger(cls, chemin: str) -> "Collection":
        with open(chemin, encoding="utf-8") as f:
            return cls.depuis_dict(json.load(f))

    def item(self, id_item: str | None) -> Item | None:
        return next((i for i in self.items if i.id == id_item), None)

    def fait_partie(self, titre: str) -> bool:
        """Le titre mentionne-t-il la gamme (30e anniversaire, 30 ans, ME05.5…) ?"""
        texte = mots(titre)
        return any(m.search(texte) for m in self.marqueurs)

    def classer(self, titre: str, exiger_marqueur: bool = True) -> Classement | None:
        """Classe un titre de fiche, ou None s'il ne s'agit pas d'un produit scellé de la gamme.

        `exiger_marqueur=False` pour une fiche venant d'une catégorie « 30 ans »
        de la boutique : le titre n'a alors pas besoin de répéter « 30 ans ».
        """
        texte = mots(titre)
        if exiger_marqueur and not any(m.search(texte) for m in self.marqueurs):
            return None
        if _correspond(self.exclusions, texte) or _RE_NUMERO_CARTE.search(titre):
            return None
        item = next((i for i in self.items if i.correspond(texte)), None)
        if item is None:
            return None  # ni coffret, ni booster, ni collection : carte à l'unité, goodies…
        return Classement(item=item, langue=langue(texte))


def langue(texte_mots: str) -> str:
    """Langue des cartes d'après le titre ; les langues asiatiques priment (« ETB JP »)."""
    for code in ("jp", "kr", "cn", "en", "fr"):
        if _RE_LANGUES[code].search(texte_mots):
            if code == "en" and _RE_LANGUES["fr"].search(texte_mots):
                return "fr"  # « Elite Trainer Box version française » : FR
            return code
    return "?"


def langue_acceptee(code: str, langues: frozenset[str]) -> bool:
    """Une fiche sans langue indiquée est supposée française (boutiques françaises)."""
    return (code if code != "?" else "fr") in langues
