"""EXODIA-4B :: Right Arm (peca 2/5) - atuador.

Traduz intencao em botoes, SEMPRE em laco fechado.

A regra que vale mais que qualquer outra aqui: nunca confie em timing fixo.
Aperte, releia a RAM e confirme que o estado foi para onde voce esperava. Sem
isso, um press cai no meio de uma animacao, e engolido em silencio, e o
harness segue achando que funcionou. Foi assim que o nome do jogador saiu
"pgZ" em vez de "EXODIA".
"""

from __future__ import annotations

from dataclasses import dataclass

from .bridge import Bridge
from .state import SELECTED_CARD


class ActuatorError(RuntimeError):
    pass


@dataclass
class Actuator:
    bridge: Bridge
    domain: str = "MainRAM"
    settle_frames: int = 4
    max_wait_frames: int = 420

    # ----------------------------------------------------------- primitivas

    def _read(self, addr: int, size: int = 2) -> int:
        if size == 1:
            return self.bridge.read_u8(addr, self.domain)
        return self.bridge.read_u16(addr, self.domain)

    def press_until_change(self, button: str, addr: int, size: int = 2,
                           hold: int = 3) -> bool:
        """Aperta e espera o valor em `addr` mudar E assentar.

        Nao basta detectar a primeira mudanca: durante uma animacao o endereco
        do cursor exibe valores transitorios. Ja aconteceu de ele mostrar a
        carta que o oponente estava usando para atacar, no meio da animacao de
        dano, e o atuador achar que o cursor tinha se movido para la.

        Por isso: espera mudar, depois espera parar de mudar.
        """
        before = self._read(addr, size)
        self.bridge.press(button, hold)
        waited = 0
        while waited < self.max_wait_frames:
            self.bridge.frame_advance(self.settle_frames)
            waited += self.settle_frames
            if self._read(addr, size) != before:
                self.wait_stable(addr, size)
                return True
        return False

    def wait_for_idle(self, addr: int = SELECTED_CARD, size: int = 2,
                      stable_for: int = 40) -> int:
        """Espera o jogo parar de animar antes de agir.

        Use isto ANTES de comecar uma sequencia de inputs. Agir enquanto o
        oponente ataca faz os presses serem engolidos e a leitura de estado
        pegar valores de animacao.
        """
        return self.wait_stable(addr, size, stable_for=stable_for)

    def wait_stable(self, addr: int, size: int = 2,
                    stable_for: int = 12) -> int:
        """Espera o valor em `addr` parar de mudar e devolve o valor final.

        Util depois de uma acao que dispara animacao: evita ler estado no meio
        da transicao.
        """
        last = self._read(addr, size)
        stable = 0
        waited = 0
        while waited < self.max_wait_frames and stable < stable_for:
            self.bridge.frame_advance(self.settle_frames)
            waited += self.settle_frames
            cur = self._read(addr, size)
            stable = stable + self.settle_frames if cur == last else 0
            last = cur
        return last

    # -------------------------------------------------------- alto nivel

    def cursor_card(self) -> int:
        """Card id sob o cursor."""
        return self._read(SELECTED_CARD, 2)

    def move_cursor_to_card(self, target_id: int, button: str = "right",
                            max_steps: int = 12,
                            valid_ids: "set[int] | None" = None) -> bool:
        """Anda com o cursor ate ele pousar na carta pedida.

        Confere a cada passo em vez de contar cliques. Se der uma volta
        completa sem achar, desiste - assim um alvo impossivel falha rapido em
        vez de girar para sempre.

        `valid_ids` e o conjunto de cartas que podem legitimamente estar sob o
        cursor (normalmente a nossa mao). Serve para separar duas coisas que se
        parecem: um cursor que realmente parou numa carta, e o endereco
        exibindo a carta de uma ANIMACAO em curso - por exemplo o monstro do
        oponente durante o ataque dele. Sem isso o atuador conta a animacao
        como se fosse posicao de cursor e desiste achando que deu a volta.
        """
        self.wait_for_idle()
        seen: set[int] = set()
        for _ in range(max_steps):
            cur = self.cursor_card()
            if cur == target_id:
                return True
            if valid_ids is not None and cur not in valid_ids:
                # leitura suspeita: espera a animacao acabar e reavalia sem
                # gastar um passo
                self.wait_for_idle(stable_for=60)
                if self.cursor_card() == target_id:
                    return True
                if self.cursor_card() not in valid_ids:
                    self.press_until_change(button, SELECTED_CARD)
                continue
            if cur in seen and len(seen) > 1:
                return False          # deu a volta e nao achou
            seen.add(cur)
            if not self.press_until_change(button, SELECTED_CARD):
                return False          # cursor travou
        return self.cursor_card() == target_id

    def confirm(self) -> None:
        self.bridge.press("cross", 3)
        self.bridge.frame_advance(self.settle_frames * 2)

    def cancel(self) -> None:
        self.bridge.press("circle", 3)
        self.bridge.frame_advance(self.settle_frames * 2)

    def open_hand(self) -> None:
        """Start abre a visao da mao durante o duelo."""
        self.bridge.press("start", 4)
        self.bridge.frame_advance(self.settle_frames * 6)

    # ------------------------------------------------------------- invocacao

    def summon(self, card_id: int, valid_ids: "set[int] | None" = None,
               guardian_star: str = "a", slot_moves: int = 0,
               max_prompts: int = 5, face_up: bool = True) -> bool:
        """Invoca uma carta da mao. Devolve True se ela chegou ao campo.

        Fluxo do jogo, mapeado por screenshot:
            1. cursor na carta       (right/left na visao da mao)
            2. cross                 -> seleciona a carta
            3. cross                 -> escolhe o slot do campo
            4. cross                 -> escolhe a guardian star

        A tela da guardian star ("ESCOLHA O ATRIBUTO") oferece duas opcoes, na
        ordem A e depois B da carta. `guardian_star="b"` desce uma antes de
        confirmar. `slot_moves` desloca o slot escolhido com "right".

        Nao confirma sozinho o sucesso pelo numero de passos: confere no fim se
        alguma carta nossa ficou com a flag de campo.
        """
        from . import state as _st          # import tardio evita ciclo

        self.wait_for_idle()
        if not self.move_cursor_to_card(card_id, valid_ids=valid_ids):
            return False

        antes_s = _st.read(self.bridge, self.domain)
        campo_antes = sum(1 for r in antes_s.field if r.card_id == card_id)
        mao_antes = sum(1 for r in antes_s.hand if r.card_id == card_id)

        self.confirm()                       # seleciona a carta
        self.wait_for_idle(stable_for=20)

        # A carta comeca VIRADA PARA BAIXO. Uma seta para qualquer lado a
        # desvira. Sem este passo o monstro entra de costas e nao pode atacar -
        # foi o que fez o agente encher o campo de cartas inuteis.
        if face_up:
            self.bridge.press("right", 3)
            self.bridge.frame_advance(self.settle_frames * 3)

        for _ in range(slot_moves):          # desloca o slot, se pedido
            self.bridge.press("right", 3)
            self.bridge.frame_advance(self.settle_frames * 2)

        # Daqui em diante o numero de prompts NAO e fixo. Confirmar tres vezes
        # as cegas dessincroniza: se o jogo pedir um passo a menos, o confirme
        # sobrando comeca a colocar a proxima carta, e o duelo fica preso num
        # prompt de escolha de slot que nenhum outro botao resolve.
        #
        # Por isso o laco olha o ESTADO a cada volta e decide o que fazer:
        #   carta no campo e fora da mao  -> terminou
        #   carta no campo e ainda na mao -> e o prompt da guardian star
        #   nenhum dos dois               -> ainda falta confirmar posicao
        # ARMADILHA: o deck tem cartas repetidas. Perguntar "essa carta esta no
        # campo e fora da mao?" da falso negativo quando existe outra copia da
        # mesma carta na mao. Por isso conta-se QUANTAS copias estao em cada
        # lugar, e nao se existe alguma.
        def contagem(s) -> tuple[int, int]:
            return (sum(1 for r in s.field if r.card_id == card_id),
                    sum(1 for r in s.hand if r.card_id == card_id))

        for _ in range(max_prompts):
            s = _st.read(self.bridge, self.domain)
            campo_agora, mao_agora = contagem(s)
            if campo_agora > campo_antes:
                return True
            # uma copia a menos na mao com o campo ainda igual = estamos no
            # meio da colocacao, entao ainda ha prompt para confirmar
            if mao_agora < mao_antes and guardian_star.lower() == "b":
                self.bridge.press("down", 3)
                self.bridge.frame_advance(self.settle_frames * 2)
            self.confirm()
            self.wait_for_idle(stable_for=20)

        campo_fim, _ = contagem(_st.read(self.bridge, self.domain))
        return campo_fim > campo_antes

    # ---------------------------------------------------------- sobreposicao

    def overlay_open(self) -> bool:
        """True enquanto houver visao de mao ou prompt na tela."""
        from .state import OVERLAY_OPEN
        return bool(self.bridge.read_u8(OVERLAY_OPEN, self.domain))

    def wait_overlay_closed(self, timeout_frames: int | None = None) -> bool:
        """Espera voltar para a visao de campo limpa."""
        from .state import OVERLAY_OPEN
        budget = timeout_frames or self.max_wait_frames
        waited = 0
        while waited < budget:
            if not self.bridge.read_u8(OVERLAY_OPEN, self.domain):
                return True
            self.bridge.frame_advance(self.settle_frames)
            waited += self.settle_frames
        return False

    def close_overlay(self, tries: int = 4) -> bool:
        """Sai da visao da mao ou de um prompt ate chegar na visao de campo."""
        for _ in range(tries):
            if not self.overlay_open():
                return True
            self.cancel()
            self.wait_for_idle(stable_for=20)
        return not self.overlay_open()

    # ------------------------------------------------------------- ataque

    def attack(self, card_id: int, target_card_id: int | None = None) -> bool:
        """Ataca com um monstro nosso. Devolve True se o duelo mudou.

        Fluxo observado numa pessoa jogando devagar:
            1. cursor no NOSSO monstro, na visao de campo
            2. confirmar               -> escolhe o atacante
            3. NAVEGAR ate o monstro do oponente   <- o passo que faltava
            4. confirmar               -> declara o ataque

        A versao anterior dava dois confirmes seguidos sem andar ate o alvo, e
        por isso falhou em 19 de 19 tentativas: o segundo confirme caia no
        vazio.

        Sucesso nao se assume pela sequencia: mede-se pelo efeito - LP do
        oponente, cartas no campo dele, ou o bit de "pode agir" do atacante.
        """
        from . import state as _st

        self.close_overlay()
        antes = _st.read(self.bridge, self.domain)

        def chave(s):
            return (s.lp_opponent, s.lp_player,
                    tuple(sorted(r.card_id for r in s.opponent_field)),
                    tuple(sorted(r.card_id for r in s.field if r.can_act)))

        k = chave(antes)
        meus = {r.card_id for r in antes.field}
        if not self.move_cursor_to_card(card_id, valid_ids=meus):
            return False
        self.confirm()
        self.wait_for_idle(stable_for=20)

        if target_card_id is not None:
            inimigos = {r.card_id for r in antes.opponent_field}
            # se nao achar o alvo, confirma mesmo assim: em ataque direto o
            # jogo nao pede alvo nenhum
            self.move_cursor_to_card(target_card_id, valid_ids=inimigos)
        self.confirm()
        self.wait_for_idle(stable_for=60)

        return chave(_st.read(self.bridge, self.domain)) != k

    # ---------------------------------------------------------- fim de turno

    def end_turn(self) -> bool:
        """Encerra o turno.

        Start so encerra o turno na VISAO DE CAMPO. Com a mao aberta ele apenas
        alterna a visao, o que por muito tempo pareceu "Start nao faz nada".
        Por isso fecha-se a sobreposicao antes.

        Devolve True se o estado do duelo mudou depois disso - normalmente
        porque o oponente jogou.
        """
        from . import state as _st

        self.close_overlay()
        antes = _st.read(self.bridge, self.domain)

        def chave(s):
            # inclui o campo do oponente carta a carta: ele pode trocar um
            # monstro por outro sem mudar a contagem
            return (s.lp_player, s.lp_opponent, len(s.hand),
                    s.opponent_hand_size,
                    tuple(sorted(r.card_id for r in s.opponent_field)))

        k = chave(antes)
        self.bridge.press("start", 4)

        # O turno do oponente inclui compra, jogada e as vezes um ataque com
        # animacao inteira. Esperar pouco fazia o fim de turno ser dado como
        # falho mesmo tendo funcionado.
        for _ in range(8):
            self.wait_for_idle(stable_for=40)
            if chave(_st.read(self.bridge, self.domain)) != k:
                return True
        return False
