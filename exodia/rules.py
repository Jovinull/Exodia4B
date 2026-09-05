"""EXODIA-4B :: Right Leg (peca 4/5) - acoes legais.

Enumera o que da para fazer no estado atual. O agente NUNCA inventa uma
jogada: ele escolhe um indice desta lista.

Isso resolve tres problemas de uma vez:
  - elimina alucinacao de jogada impossivel;
  - torna a validacao trivial (0 <= id < len(acoes));
  - reduz muito os tokens de saida, o que em CPU vale segundos por turno.

Cada acao carrega o SLOT das cartas envolvidas, e nao so o id. O id nao
distingue duas copias da mesma carta, nem separa a copia que esta na mao da
que esta no campo - foi o que fez o agente selecionar a carta errada e travar.

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
    card_id: int | None = None     # carta nossa envolvida (para conferencia)
    hand_slot: int | None = None   # posicao na mao, contada da esquerda
    field_slot: int | None = None  # posicao do nosso monstro no campo
    target_slot: int | None = None      # posicao do alvo no campo do oponente
    target_card_id: int | None = None   # so para conferencia
    guardian_star: str = "a"

    def __str__(self) -> str:
        return self.label


def legal_actions(state: GameState,
                  excluir: "set[int] | None" = None) -> list[Action]:
    """Acoes possiveis agora.

    `excluir` recebe os SLOTS de campo cujo ataque ja foi recusado neste turno,
    para o agente nao insistir na mesma jogada.
    """
    acoes: list[Action] = []
    excluidos = excluir or set()

    # --- invocar monstros da mao -------------------------------------------
    # Magias e armadilhas ficam de fora por enquanto: o fluxo de ativacao
    # ainda nao foi mapeado, e oferecer uma acao que o atuador nao sabe
    # executar so gera loop.
    #
    # Com o campo cheio a invocacao e recusada pelo jogo, entao nem entra na
    # lista - acao que sempre falha so ensina o agente a bater a cabeca.
    campo_cheio = len(state.field) >= MAX_FIELD_MONSTERS
    if not campo_cheio:
        for slot, r in enumerate(state.hand):
            c = cards.get(r.card_id)
            if not c or not c.is_monster:
                continue
            for estrela, idx in (("a", c.guardian_a), ("b", c.guardian_b)):
                acoes.append(Action(
                    kind="summon",
                    card_id=r.card_id,
                    hand_slot=slot,
                    guardian_star=estrela,
                    label=(f"Invocar {c.name} ({c.attack}/{c.defense}) "
                           f"com guardian star "
                           f"{cards.guardian_star_label(idx)}"),
                ))

    # --- atacar ------------------------------------------------------------
    # Pode atacar quem esta de frente e ainda NAO atacou neste turno. O bit
    # 0x4000 marca "ja atacou".
    for slot, a in enumerate(state.field):
        if not a.can_attack or slot in excluidos:
            continue
        ca = cards.get(a.card_id)
        nome_a = ca.name if ca else f"id {a.card_id}"
        if state.opponent_field:
            for alvo_slot, alvo in enumerate(state.opponent_field):
                ct = cards.get(alvo.card_id)
                nome_t = (f"{ct.name} ({ct.attack}/{ct.defense})" if ct
                          else f"id {alvo.card_id}")
                acoes.append(Action(
                    kind="attack",
                    card_id=a.card_id,
                    field_slot=slot,
                    target_slot=alvo_slot,
                    target_card_id=alvo.card_id,
                    label=f"Atacar {nome_t} com {nome_a} ({a.attack} ATK)",
                ))
        else:
            acoes.append(Action(
                kind="attack_direct",
                card_id=a.card_id,
                field_slot=slot,
                label=f"Atacar diretamente com {nome_a} ({a.attack} ATK)",
            ))

    # --- sempre possivel ----------------------------------------------------
    acoes.append(Action(kind="end_turn", label="Passar o turno"))
    return acoes


def render_actions(acoes: list[Action]) -> str:
    """Lista numerada, do jeito que vai para o prompt."""
    return "\n".join(f"{i}: {a.label}" for i, a in enumerate(acoes))
