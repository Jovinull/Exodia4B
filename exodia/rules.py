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
                  excluir: "set[int] | None" = None,
                  ja_invocou: bool = False) -> list[Action]:
    """Acoes possiveis agora.

    `excluir` recebe os SLOTS de campo cujo ataque ja foi recusado neste turno,
    para o agente nao insistir na mesma jogada.

    `ja_invocou` diz que uma carta ja foi colocada neste turno. Em Forbidden
    Memories so se joga UMA carta por turno - regra confirmada com o atuador
    ja funcionando: a primeira invocacao entra, a segunda no mesmo turno e
    recusada com o campo intacto, e a do turno seguinte entra de novo.
    (Esta regra ja tinha sido concluida e depois RETIRADA, quando se descobriu
    que as recusas vinham de um summon dessincronizado. Agora ela volta com
    medicao limpa - ver Notes/16.)
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
    # Oferecer invocacao depois de ja ter invocado nao e so inutil: cada acao
    # impossivel custa uma inferencia inteira - dezenas de segundos de relogio -
    # e ainda ensina o agente a bater a cabeca.
    campo_cheio = len(state.field) >= MAX_FIELD_MONSTERS
    if not campo_cheio and not ja_invocou:
        for slot, r in enumerate(state.hand):
            c = cards.get(r.card_id)
            if not c or not c.is_monster:
                continue
            # So a estrela A por enquanto. A tela "ESCOLHA O ATRIBUTO" oferece
            # as duas na ordem A, B, e escolher a B exige descer uma linha
            # antes de confirmar - mas o harness ainda nao sabe DETECTAR que
            # esta nesse prompt: MENU_ID, MODE e VIEW_FLAG ficam constantes
            # durante a invocacao inteira, e o numero de confirmes ate a carta
            # cair no campo varia com o tempo de animacao.
            #
            # Ate existir esse sinal, oferecer a estrela B seria mentir para o
            # agente: o codigo antigo aceitava guardian_star="b", nunca
            # apertava o "baixo" (a condicao que disparava o passo nunca era
            # verdadeira) e invocava com a estrela A do mesmo jeito. O agente
            # raciocinava sobre uma alavanca desligada.
            #
            # Melhor uma escolha a menos do que uma escolha falsa.
            acoes.append(Action(
                kind="summon",
                card_id=r.card_id,
                hand_slot=slot,
                guardian_star="a",
                label=(f"Invocar {c.name} ({c.attack}/{c.defense}) "
                       f"com guardian star "
                       f"{cards.guardian_star_label(c.guardian_a)}"),
            ))

    # --- atacar ------------------------------------------------------------
    # Pode atacar quem esta de frente e ainda NAO atacou neste turno. O bit
    # 0x4000 marca "ja atacou".
    for slot, a in enumerate(state.field):
        if not a.can_attack or slot in excluidos:
            continue
        ca = cards.get(a.card_id)
        nome_a = ca.name if ca else f"id {a.card_id}"
        # So MONSTRO e alvo de ataque. Magia e armadilha ocupam o campo do
        # oponente e apareciam na lista como alvo com "(0/0)" - uma acao que o
        # jogo nunca ia aceitar, e que o modelo escolhia justamente por parecer
        # o alvo mais fraco da mesa. Sem monstro do outro lado, o ataque vai
        # direto nos LP, mesmo que haja magias no campo dele.
        alvos = [(i, r) for i, r in enumerate(state.opponent_field)
                 if (c := cards.get(r.card_id)) and c.is_monster]
        if alvos:
            for alvo_slot, alvo in alvos:
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
