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
    max_wait_frames: int = 180

    # ----------------------------------------------------------- primitivas

    def _read(self, addr: int, size: int = 2) -> int:
        if size == 1:
            return self.bridge.read_u8(addr, self.domain)
        return self.bridge.read_u16(addr, self.domain)

    def press_until_change(self, button: str, addr: int, size: int = 2,
                           hold: int = 3) -> bool:
        """Aperta e espera o valor em `addr` mudar.

        Devolve True se mudou dentro do orcamento de frames. False significa
        que o input nao teve efeito - provavelmente foi engolido por uma
        animacao, ou aquele botao nao faz nada nesta tela.
        """
        before = self._read(addr, size)
        self.bridge.press(button, hold)
        waited = 0
        while waited < self.max_wait_frames:
            self.bridge.frame_advance(self.settle_frames)
            waited += self.settle_frames
            if self._read(addr, size) != before:
                return True
        return False

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
                            max_steps: int = 12) -> bool:
        """Anda com o cursor ate ele pousar na carta pedida.

        Confere a cada passo em vez de contar cliques. Se der uma volta
        completa sem achar, desiste - assim um alvo impossivel falha rapido em
        vez de girar para sempre.
        """
        seen: set[int] = set()
        for _ in range(max_steps):
            cur = self.cursor_card()
            if cur == target_id:
                return True
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
