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
               guardian_star: str = "a", slot_moves: int = 0) -> bool:
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

        antes = len(_st.read(self.bridge, self.domain).field)

        self.confirm()                      # 1. seleciona a carta
        self.wait_for_idle(stable_for=20)

        for _ in range(slot_moves):         # 2. desloca o slot, se pedido
            self.bridge.press("right", 3)
            self.bridge.frame_advance(self.settle_frames * 2)
        self.confirm()                      # confirma o slot
        self.wait_for_idle(stable_for=20)

        if guardian_star.lower() == "b":    # 3. escolhe a estrela
            self.bridge.press("down", 3)
            self.bridge.frame_advance(self.settle_frames * 2)
        self.confirm()
        self.wait_for_idle(stable_for=30)

        return len(_st.read(self.bridge, self.domain).field) > antes
