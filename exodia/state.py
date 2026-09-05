"""EXODIA-4B :: Right Leg (peca 4/5) - leitura de estado.

Traduz a RAM crua do PS1 em um GameState tipado.

TUDO aqui foi verificado ao vivo contra a tela na ISO PT-BR (SLUS_014.11).
Ver Notes/PROGRESS.md para o registro das validacoes.

DESCOBERTA IMPORTANTE: o RAM map publico do Data Crystal aponta 0x801A7E20
como "Player's Hand", mas esse array fica DESATUALIZADO durante o duelo (foi
observado ainda mostrando uma carta ja jogada). A mao viva e autoritativa e o
array de registros em 0x801A7AE4. Use CARD_RECORDS, nao HAND_SNAPSHOT.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

from . import cards
from .bridge import Bridge

# ------------------------------------------------------------------ enderecos

LP_PLAYER = 0x800EA004        # u16 - validado: 8000, e caiu para 7750 em combate
LP_OPPONENT = 0x800EA024      # u16
LP_PLAYER_DISPLAY = 0x800EA002
LP_OPPONENT_DISPLAY = 0x800EA022

CARD_RECORDS = 0x801A7AE4     # array vivo; stride 28
RECORD_STRIDE = 28
# 30 e o limite util observado (indices 30+ trazem memoria nao inicializada).
# Ler so 24 cortava a faixa final e escondia registros validos.
MAX_RECORDS = 30

HAND_SNAPSHOT = 0x801A7E20    # 5 x 6 bytes; FICA DESATUALIZADO - so diagnostico
PLAYER_DECK = 0x801D0200      # 40 x u16 (nao embaralhado)
TRUNK = 0x801D0250            # 722 bytes: contagem por card id
MENU_ID = 0x80184594          # u8  - 89 durante o duelo
MODE_BYTE = 0x8009B26C        # u8  - 194/195/197 conforme a tela
OPPONENT_ID = 0x8009B361      # u8  - 1 = primeiro duelo
TERRAIN = 0x8009B364          # u8
SELECTED_CARD = 0x8009B338    # u16 - card id sob o cursor
VIEW_FLAG = 0x8009B1D5        # u8  - muda ao abrir a mao com Start
FUSION_RESULT = 0x800EA118    # u16 - resultado da ultima fusao

# NAO E FLAG DE SOBREPOSICAO. E UM BIT DE PARIDADE DE FRAME.
#
# Este endereco foi eleito como "tem menu aberto?" e reprovou da pior forma
# possivel: ele alterna 1,0,1,0,... a CADA FRAME, sem relacao nenhuma com a
# tela. Medido lendo 40 vezes seguidas com 1 frame entre as leituras:
#
#     1010101010101010101010101010101010101010
#
# E o motivo de ele ter passado na validacao original esta na leitura seguinte,
# com 4 frames entre as amostras:
#
#     1111111111111111111111111111111111111111
#
# Amostrado de 4 em 4 frames, um bit que alterna a cada frame parece CONSTANTE.
# O `settle_frames=4` do atuador criou exatamente esse aliasing, e por isso o
# endereco pareceu estavel em 5 savestates diferentes.
#
# O estrago: `close_overlay()` decidia apertar START com base nisso, e START na
# visao de campo ENCERRA O TURNO. Na pratica o harness passava o proprio turno
# no meio de uma jogada, por cara ou coroa. Era a causa das invocacoes e
# ataques que "falhavam" sem explicacao.
#
# Mantido aqui documentado de proposito: sem este comentario, o endereco volta
# a parecer uma boa ideia na proxima vez que alguem procurar uma flag de menu.
FRAME_PARITY = 0x8009B0AC
FRAME_PARITY_ALT = 0x8009B124   # acompanha o de cima: mesma paridade

# Nomes antigos, mantidos so para os scripts de diagnostico que os citam.
OVERLAY_OPEN = FRAME_PARITY
OVERLAY_OPEN_ALT = FRAME_PARITY_ALT

# Flags do registro de 28 bytes, confirmadas contra a tela:
#
#   0x8000  carta ATIVA (na mao ou em campo). Confirmado por screenshot: no
#           inicio do duelo o registro do Raigeki tem 0x0000 e ele de fato NAO
#           aparece na mao; as outras cinco cartas tem 0x8000 e sao exatamente
#           as cinco desenhadas na tela.
#   0x2000  carta do OPONENTE. So apareceu do lado do oponente, em amostras de
#           tipos diferentes (Magia, Maquina, Terra).
#   0x1000  significa coisas DIFERENTES nos dois lados:
#             - do oponente: carta em campo (o monstro de 250 ATK que atacou
#               tinha esse bit, e o dano recebido bateu com o ATK dele);
#             - do nosso lado: carta VIRADA PARA BAIXO. Invocar apertando uma
#               seta, que desvira a carta, termina em 0x8000; invocar sem
#               apertar nada termina em 0x9000, e essa carta nao ataca.
#   0x0400  "monstro em campo" segundo o fonte da recompilacao; nunca foi
#           observado ligado aqui. Nao confiar.
#
# O intervalo de indice serve de sanidade extra, nao de criterio principal:
#   indices  0..14  = jogador
#   indices 15..29  = oponente
#   indices 30+     = lixo/memoria nao inicializada (aparece "Blue-eyes" id=1)
FLAG_ACTIVE = 0x8000
FLAG_OPPONENT = 0x2000
# 0x1000 no NOSSO lado indica carta VIRADA PARA BAIXO, nao "em campo".
# Medido: invocar apertando uma seta (que desvira a carta) termina em 0x8000;
# invocar sem apertar nada termina em 0x9000. Uma carta de costas nao ataca.
FLAG_FACE_DOWN = 0x1000
FLAG_ON_FIELD_OPPONENT = 0x1000   # do lado do oponente o mesmo bit marca campo
# 0x4000 significa "JA ATACOU neste turno", e nao "pode agir".
# Medido no log de uma pessoa jogando: logo apos invocar o monstro esta em
# 0x8000; depois de ele declarar ataque passa a 0xC000; e volta a 0x8000 no
# comeco do turno seguinte. Eu tinha lido esse bit ao contrario, e por isso o
# filtro de acoes excluia justamente os monstros que podiam atacar.
FLAG_HAS_ATTACKED = 0x4000
FLAG_EXTRA_0400 = 0x0400   # acompanha 0x4000 as vezes; significado incerto

# Layout do array, deduzido observando uma pessoa jogar um duelo inteiro:
#
#   0..4    nossa MAO
#   5..14   nosso CAMPO (slots fixos; um slot vazio simplesmente nao aparece,
#           foi visto #5 e #7 ocupados com #6 ausente)
#   15..29  lado do OPONENTE
#
# ARMADILHA: o bit 0x1000 marca campo do OPONENTE, mas do nosso lado ele quer
# dizer "virada para baixo". Do nosso lado as flags ainda oscilam entre 0x8000,
# 0xC000 e 0xC400 conforme o monstro pode agir no turno, voltando a 0x8000
# depois do fim de turno. Por isso o nosso campo se identifica pelo INDICE.
#
# Isso custou varias sessoes: enquanto o campo proprio era lido pela flag, o
# agente enxergava "Seu campo: vazio" com dois monstros nossos em jogo.
PLAYER_HAND_MAX = 4
PLAYER_INDEX_MAX = 14
LAST_VALID_INDEX = 29
MAX_CARD_ID = 722

# Offsets ainda NAO identificados dentro do registro de 28 bytes:
#   +6, +8, +14..19  -> zerados enquanto a carta esta na mao.
#                       Candidatos a guardian star / posicao / face-up.
#                       Precisam ser lidos com um monstro EM CAMPO (V4).
#   +20..23          -> ponteiro para a proxima entrada de 0x801A7E20
#                       (lista encadeada; 0x801A7E2C, 0x801A7E32, ...)


@dataclass
class CardInRecord:
    index: int
    card_id: int
    attack: int
    defense: int
    flags: int
    slot: int
    raw: bytes = field(repr=False, default=b"")

    @property
    def live(self) -> bool:
        """Carta ativa: esta na mao ou em campo, e nao e lixo de memoria."""
        return (bool(self.flags & FLAG_ACTIVE)
                and 1 <= self.card_id <= MAX_CARD_ID
                and self.index <= LAST_VALID_INDEX)

    @property
    def is_opponent(self) -> bool:
        return bool(self.flags & FLAG_OPPONENT) or self.index > PLAYER_INDEX_MAX

    @property
    def on_field(self) -> bool:
        """Em campo.

        Dois criterios porque o jogo marca os dois lados de formas diferentes:
        do oponente pelo bit 0x1000, do nosso lado pelo indice do registro.
        """
        if self.is_opponent:
            return bool(self.flags & FLAG_ON_FIELD_OPPONENT)
        return self.index > PLAYER_HAND_MAX

    @property
    def has_attacked(self) -> bool:
        """Nosso monstro que ja declarou ataque neste turno."""
        return bool(self.flags & FLAG_HAS_ATTACKED)

    @property
    def can_attack(self) -> bool:
        """Pode declarar ataque: em campo, de frente e ainda nao atacou."""
        return (self.on_field and not self.is_opponent
                and not self.face_down and not self.has_attacked)

    @property
    def face_down(self) -> bool:
        """Carta nossa virada para baixo. De costas ela nao ataca."""
        return not self.is_opponent and bool(self.flags & FLAG_FACE_DOWN)

    def describe(self) -> str:
        c = cards.get(self.card_id)
        base = c.short() if c else f"<id {self.card_id}>"
        who = "oponente" if self.is_opponent else "voce"
        where = "campo" if self.on_field else "mao"
        return f"{base} [{who}/{where}]"


@dataclass
class GameState:
    lp_player: int
    lp_opponent: int
    opponent_id: int
    terrain: int
    menu_id: int
    mode: int
    selected_card: int
    records: list[CardInRecord]

    @property
    def in_duel(self) -> bool:
        """Heuristica: dentro de duelo os LP sao plausiveis e ha cartas vivas."""
        return (0 < self.lp_player <= 8000 or 0 < self.lp_opponent <= 8000) \
            and any(r.live for r in self.records)

    @property
    def hand(self) -> list[CardInRecord]:
        return [r for r in self.records
                if r.live and not r.is_opponent and not r.on_field]

    @property
    def field(self) -> list[CardInRecord]:
        return [r for r in self.records
                if r.live and not r.is_opponent and r.on_field]

    @property
    def opponent_field(self) -> list[CardInRecord]:
        return [r for r in self.records
                if r.live and r.is_opponent and r.on_field]

    @property
    def opponent_hand_size(self) -> int:
        """Quantidade, nao conteudo: um humano ve o numero de cartas, nao quais.
        Expor as cartas do oponente ao agente seria trapaca (Notes/06)."""
        return sum(1 for r in self.records
                   if r.live and r.is_opponent and not r.on_field)

    def render(self) -> str:
        """Texto legivel - e a base do que vai para o prompt do agente.

        So mostra o que um humano veria na tela. As cartas na MAO do oponente
        aparecem como contagem, nunca como lista.
        """
        out = [
            f"Seus LP: {self.lp_player}  |  Oponente (#{self.opponent_id}) "
            f"LP: {self.lp_opponent}",
        ]
        if self.terrain:
            out.append(f"Terreno: {self.terrain}")
        out.append("Sua mao:")
        for i, r in enumerate(self.hand, 1):
            c = cards.get(r.card_id)
            out.append(f"  {i}. {c.short() if c else f'<id {r.card_id}>'}")
        fld = self.field
        out.append("Seu campo: " + ("vazio" if not fld else ""))
        for r in fld:
            c = cards.get(r.card_id)
            out.append(f"  - {c.short() if c else f'<id {r.card_id}>'}")
        ofld = self.opponent_field
        out.append("Campo do oponente: " + ("vazio" if not ofld else ""))
        for r in ofld:
            c = cards.get(r.card_id)
            out.append(f"  - {c.short() if c else f'<id {r.card_id}>'}")
        out.append(f"Cartas na mao do oponente: {self.opponent_hand_size}")
        return "\n".join(out)


def read(bridge: Bridge, domain: str = "MainRAM") -> GameState:
    blob = bridge.read_bytes(CARD_RECORDS, RECORD_STRIDE * MAX_RECORDS, domain)
    records: list[CardInRecord] = []
    for i in range(MAX_RECORDS):
        rec = blob[i * RECORD_STRIDE:(i + 1) * RECORD_STRIDE]
        cid, atk, dfs = struct.unpack_from("<HHH", rec, 0)
        flags, = struct.unpack_from("<H", rec, 10)
        slot, = struct.unpack_from("<H", rec, 12)
        if cid == 0 and flags == 0 and atk == 0:
            continue
        r = CardInRecord(i, cid, atk, dfs, flags, slot, rec)
        if not r.live:
            continue          # indices 30+ trazem memoria nao inicializada
        records.append(r)

    return GameState(
        lp_player=bridge.read_u16(LP_PLAYER, domain),
        lp_opponent=bridge.read_u16(LP_OPPONENT, domain),
        opponent_id=bridge.read_u8(OPPONENT_ID, domain),
        terrain=bridge.read_u8(TERRAIN, domain),
        menu_id=bridge.read_u8(MENU_ID, domain),
        mode=bridge.read_u8(MODE_BYTE, domain),
        selected_card=bridge.read_u16(SELECTED_CARD, domain),
        records=records,
    )


def read_deck(bridge: Bridge, domain: str = "MainRAM") -> list[int]:
    return list(struct.unpack("<40H", bridge.read_bytes(PLAYER_DECK, 80, domain)))


def read_trunk(bridge: Bridge, domain: str = "MainRAM") -> dict[int, int]:
    """card_id -> quantidade. No inicio do jogo vem tudo zero (tudo no deck)."""
    raw = bridge.read_bytes(TRUNK, 722, domain)
    return {i + 1: q for i, q in enumerate(raw) if q}
