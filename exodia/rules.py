"""EXODIA-4B :: Right Leg (peca 4/5) - acoes legais.

Enumera o que da para fazer no estado atual. O agente NUNCA inventa uma
jogada: ele escolhe um indice desta lista.

Isso resolve tres problemas de uma vez:
  - elimina alucinacao de jogada impossivel;
  - torna a validacao trivial (0 <= id < len(acoes));
  - reduz muito os tokens de saida, o que em CPU vale segundos por turno.

REGRA DE OURO (Notes/01): aqui so entram regras MECANICAS. Nada de ordenar por
qualidade, sugerir a melhor jogada ou marcar uma acao como recomendada - o
agente tem que descobrir isso sozinho.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import cards
from .state import GameState

# Zonas de monstro do campo em Forbidden Memories.
MAX_FIELD_MONSTERS = 5


@dataclass(frozen=True)
class Action:
    kind: str                      # summon | attack | attack_direct | end_turn
    label: str                     # texto mostrado ao agente
    card_id: int | None = None     # carta nossa envolvida
    target_index: int | None = None  # indice do registro alvo
    target_card_id: int | None = None  # carta alvo (para mirar o cursor)
    guardian_star: str = "a"

    def __str__(self) -> str:
        return self.label


def legal_actions(state: GameState) -> list[Action]:
    acoes: list[Action] = []

    # --- invocar monstros da mao -------------------------------------------
    # Magias e armadilhas ficam de fora por enquanto: o fluxo de ativacao
    # ainda nao foi mapeado, e oferecer uma acao que o atuador nao sabe
    # executar so gera loop.
    # O campo tem 5 zonas de monstro. Com ele cheio a invocacao e recusada pelo
    # jogo, entao nem entra na lista - oferecer uma acao que sempre falha so
    # ensina o agente a bater a cabeca.
    campo_cheio = len(state.field) >= MAX_FIELD_MONSTERS
    for r in ([] if campo_cheio else state.hand):
        c = cards.get(r.card_id)
        if not c or not c.is_monster:
            continue
        for estrela, idx in (("a", c.guardian_a), ("b", c.guardian_b)):
            acoes.append(Action(
                kind="summon",
                card_id=r.card_id,
                guardian_star=estrela,
                label=(f"Invocar {c.name} ({c.attack}/{c.defense}) "
                       f"com guardian star {cards.guardian_star_label(idx)}"),
            ))

    # --- atacar ------------------------------------------------------------
    # O bit 0x4000 indica monstro que ainda pode agir, mas ele so aparece em
    # certos momentos do nosso turno. Enquanto o fluxo de ataque nao esta
    # confirmado, oferecem-se todos os monstros do campo e deixa-se o atuador
    # medir se o ataque aconteceu de fato.
    # Carta virada para baixo nao ataca, entao nem entra como atacante.
    de_frente = [r for r in state.field if not r.face_down]
    atacantes = [r for r in de_frente if r.can_act] or de_frente
    inimigos = state.opponent_field
    for a in atacantes:
        ca = cards.get(a.card_id)
        nome_a = ca.name if ca else f"id {a.card_id}"
        if inimigos:
            for alvo in inimigos:
                ct = cards.get(alvo.card_id)
                nome_t = (f"{ct.name} ({ct.attack}/{ct.defense})" if ct
                          else f"id {alvo.card_id}")
                acoes.append(Action(
                    kind="attack",
                    card_id=a.card_id,
                    target_index=alvo.index,
                    target_card_id=alvo.card_id,
                    label=f"Atacar {nome_t} com {nome_a} ({a.attack} ATK)",
                ))
        else:
            acoes.append(Action(
                kind="attack_direct",
                card_id=a.card_id,
                label=f"Atacar diretamente com {nome_a} ({a.attack} ATK)",
            ))

    # --- sempre possivel ----------------------------------------------------
    acoes.append(Action(kind="end_turn", label="Passar o turno"))
    return acoes


def render_actions(acoes: list[Action]) -> str:
    """Lista numerada, do jeito que vai para o prompt."""
    return "\n".join(f"{i}: {a.label}" for i, a in enumerate(acoes))
