"""EXODIA-4B :: Right Leg (parte da peca 4/5) - base de cartas.

Traduz card ID -> nome / ATK / DEF / tipo / guardian stars.

Fonte: Solumin/YGO-FM-FusionCalc (data/Cards.json), 722 cartas.
Validado contra a RAM do jogo: o ID lido da memoria e IGUAL ao campo `Id` do
banco (1-based, sem offset). Conferido 5/5 no primeiro duelo.

REGRA DE OURO (Notes/01): este modulo existe para o HARNESS traduzir dados.
O campo `Fusions` NAO pode ser exposto ao prompt do agente - ele so pode
conhecer fusoes que ele mesmo executou com sucesso.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data" / "raw" / "Cards.json"

# Tipos de carta do FM. Os >= 20 nao sao monstros.
TYPE_NAMES = {
    0: "Dragao", 1: "Mago", 2: "Fera", 3: "GuerreiroFera", 4: "Inseto",
    5: "Dinossauro", 6: "Peixe", 7: "FeraAlada", 8: "Planta", 9: "Maquina",
    10: "Serpente", 11: "Raio", 12: "Aqua", 13: "Fogo", 14: "Terra",
    15: "Vento", 16: "Trevas", 17: "Luz", 18: "Guerreiro", 19: "Zumbi",
    20: "Magia", 21: "Armadilha", 22: "Ritual", 23: "Equipamento",
}

GUARDIAN_STARS = {
    0: "-", 1: "Mercurio", 2: "Sol", 3: "Lua", 4: "Venus", 5: "Marte",
    6: "Jupiter", 7: "Saturno", 8: "Urano", 9: "Netuno", 10: "Plutao",
}


@dataclass(frozen=True)
class Card:
    id: int
    name: str
    attack: int
    defense: int
    type: int
    level: int
    guardian_a: int
    guardian_b: int
    attribute: int

    @property
    def is_monster(self) -> bool:
        return self.type < 20

    @property
    def type_name(self) -> str:
        return TYPE_NAMES.get(self.type, f"tipo{self.type}")

    def short(self) -> str:
        if self.is_monster:
            return (f"{self.name} ({self.attack}/{self.defense}, "
                    f"{self.type_name})")
        return f"{self.name} ({self.type_name})"


@lru_cache(maxsize=1)
def _db() -> dict[int, Card]:
    if not DATA.exists():
        raise FileNotFoundError(
            f"base de cartas nao encontrada em {DATA}.\n"
            "Baixe com: curl -sL -o data/raw/Cards.json "
            "https://raw.githubusercontent.com/Solumin/YGO-FM-FusionCalc/"
            "master/data/Cards.json"
        )
    raw = json.loads(DATA.read_text(encoding="utf-8"))
    out: dict[int, Card] = {}
    for c in raw:
        out[c["Id"]] = Card(
            id=c["Id"],
            name=c["Name"].strip(),
            attack=c["Attack"] or 0,
            defense=c["Defense"] or 0,
            type=c["Type"],
            level=c.get("Level") or 0,
            guardian_a=c.get("GuardianStarA") or 0,
            guardian_b=c.get("GuardianStarB") or 0,
            attribute=c.get("Attribute") or 0,
        )
    return out


def get(card_id: int) -> Card | None:
    return _db().get(card_id)


def name(card_id: int) -> str:
    c = get(card_id)
    return c.name if c else f"<id {card_id} desconhecido>"


def count() -> int:
    return len(_db())
