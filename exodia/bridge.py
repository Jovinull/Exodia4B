"""EXODIA-4B :: Left Arm (peca 1/5)

Servidor TCP que conversa com o bridge.lua rodando dentro do BizHawk.

Direcao do protocolo (detalhe que todo mundo erra):
    o Lua do BizHawk so tem CLIENTE de socket, entao o PYTHON e o SERVIDOR.

Formato do enquadramento:
    BizHawk >= 2.6.2 exige que TUDO que o servidor manda venha prefixado com
    "<tamanho_em_decimal> ". O que o BizHawk manda de volta tambem vem
    prefixado, entao o parser aceita as duas formas por seguranca.

Uso tipico:
    with Bridge() as b:
        b.start()                 # espera o EmuHawk conectar
        lp = b.read_u16(0x800EA004)
"""

from __future__ import annotations

import socket
import threading
from contextlib import suppress

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 55355

# Mascara que converte endereco do espaco PS1 (0x800xxxxx) em offset da MainRAM.
PSX_RAM_MASK = 0x1FFFFF


class BridgeError(RuntimeError):
    pass


class Bridge:
    """Servidor TCP com semantica de request/response contra o bridge.lua.

    O Lua roda um loop: manda o resultado do comando anterior, entao espera o
    proximo comando. Portanto cada `command()` faz: recebe o status pendente,
    manda o comando, recebe o resultado.
    """

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
                 timeout: float = 30.0) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self._srv: socket.socket | None = None
        self._conn: socket.socket | None = None
        self._buf = b""
        self._lock = threading.Lock()

    # ------------------------------------------------------------ ciclo de vida

    def listen(self) -> None:
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind((self.host, self.port))
        self._srv.listen(1)

    def accept(self, timeout: float = 120.0) -> None:
        if self._srv is None:
            self.listen()
        assert self._srv is not None
        self._srv.settimeout(timeout)
        try:
            self._conn, _ = self._srv.accept()
        except socket.timeout as exc:
            raise BridgeError(
                f"o EmuHawk nao conectou em {timeout}s. Ele foi aberto com "
                f"--socket_ip={self.host} --socket_port={self.port} e com o "
                f"--lua=bridge.lua?"
            ) from exc
        self._conn.settimeout(self.timeout)

    def start(self, timeout: float = 120.0) -> str:
        """Sobe o servidor, espera a conexao e consome o HELLO inicial."""
        self.listen()
        return self.start_after_listen(timeout)

    def start_after_listen(self, timeout: float = 120.0) -> str:
        """Como start(), mas para quem ja chamou listen() antes.

        Util quando o processo precisa estar ouvindo ANTES de lancar o EmuHawk,
        senao o cliente Lua nao acha o servidor.
        """
        self.accept(timeout)
        return self._recv_message()

    def close(self) -> None:
        for s in (self._conn, self._srv):
            if s is not None:
                with suppress(OSError):
                    s.close()
        self._conn = self._srv = None

    def __enter__(self) -> "Bridge":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ------------------------------------------------------- enquadramento

    def _recv_message(self) -> str:
        """Le uma mensagem. Aceita com ou sem prefixo de tamanho."""
        assert self._conn is not None
        # tenta interpretar "<n> <payload>"
        while True:
            sp = self._buf.find(b" ")
            if sp != -1:
                head = self._buf[:sp]
                if head.isdigit():
                    n = int(head)
                    if len(self._buf) >= sp + 1 + n:
                        msg = self._buf[sp + 1: sp + 1 + n]
                        self._buf = self._buf[sp + 1 + n:]
                        return msg.decode("utf-8", "replace")
                else:
                    # sem prefixo: devolve o que houver ate agora
                    data, self._buf = self._buf, b""
                    return data.decode("utf-8", "replace").strip()
            chunk = self._conn.recv(65536)
            if not chunk:
                raise BridgeError("o EmuHawk fechou a conexao")
            self._buf += chunk

    def _send_message(self, msg: str) -> None:
        assert self._conn is not None
        payload = msg.encode("utf-8")
        self._conn.sendall(f"{len(payload)} ".encode("ascii") + payload)

    # --------------------------------------------------------------- comandos

    def command(self, cmd: str) -> str:
        """Manda um comando e devolve o resultado."""
        if self._conn is None:
            raise BridgeError("nao conectado; chame start() antes")
        with self._lock:
            self._send_message(cmd)
            while True:
                res = self._recv_message()
                # o Lua manda IDLE quando um poll expira sem comando: ignora
                if res != "IDLE":
                    return res

    # --------------------------------------------------- helpers de alto nivel

    def ping(self) -> bool:
        return self.command("PING") == "PONG"

    def info(self) -> dict[str, str]:
        raw = self.command("INFO")
        out: dict[str, str] = {}
        for part in raw.split("|"):
            if "=" in part:
                k, v = part.split("=", 1)
                out[k] = v
        return out

    def domains(self) -> dict[str, int]:
        raw = self.command("DOMAINS")
        out: dict[str, int] = {}
        for part in raw.split(","):
            if ":" in part:
                k, v = part.rsplit(":", 1)
                with suppress(ValueError):
                    out[k] = int(v)
        return out

    def main_ram(self) -> str:
        """Descobre o nome do dominio de RAM principal (2 MB) neste core.

        O nome varia entre os cores de PSX do BizHawk (Nymashock x Octoshock),
        entao nunca assuma "MainRAM" - detecte.
        """
        doms = self.domains()
        for name, size in doms.items():
            if size == 2 * 1024 * 1024:
                return name
        # fallback: o maior dominio gravavel que nao seja video/audio/bios
        ignore = ("GPURAM", "SPURAM", "BiosROM", "DCache", "Memcard", "Waterbox")
        cand = {k: v for k, v in doms.items()
                if v > 0 and not any(k.startswith(i) for i in ignore)}
        if not cand:
            raise BridgeError(f"nenhum dominio de RAM plausivel em: {doms}")
        return max(cand, key=cand.get)

    def _read(self, addr: int, size: int, domain: str = "MainRAM") -> int:
        res = self.command(f"READ {addr & PSX_RAM_MASK:06X} {size} {domain}")
        if res.startswith("ERR"):
            raise BridgeError(res)
        return int(res)

    def read_u8(self, addr: int, domain: str = "MainRAM") -> int:
        return self._read(addr, 1, domain)

    def read_u16(self, addr: int, domain: str = "MainRAM") -> int:
        return self._read(addr, 2, domain)

    def read_u32(self, addr: int, domain: str = "MainRAM") -> int:
        return self._read(addr, 4, domain)

    def read_bytes(self, addr: int, length: int, domain: str = "MainRAM") -> bytes:
        res = self.command(f"READRANGE {addr & PSX_RAM_MASK:06X} {length} {domain}")
        if res.startswith("ERR"):
            raise BridgeError(res)
        return bytes.fromhex(res)

    # ------------------------------------------------------------- botoes
    #
    # ARMADILHA: no core PSX do BizHawk o D-pad se chama "D-Pad Right" (nao
    # "Right") e o confirmar se chama "X" (nao "Cross"). Circulo, quadrado e
    # triangulo sao simbolos Unicode. Por isso resolvemos tudo pelos BYTES
    # reais que o core reporta, e nunca por nome adivinhado.

    _ALIASES = {
        "up": ("D-Pad Up",),
        "down": ("D-Pad Down",),
        "left": ("D-Pad Left",),
        "right": ("D-Pad Right",),
        "cross": ("X",),
        "start": ("Start",),
        "select": ("Select",),
        "l1": ("L1",), "l2": ("L2",), "r1": ("R1",), "r2": ("R2",),
        # simbolos: casados por codepoint, nao por texto digitado
        "circle": ("○", "◯", "⭕", "O"),
        "square": ("□", "⬜"),
        "triangle": ("△", "▵"),
    }

    def _button_map(self) -> dict[str, str]:
        """alias amigavel -> hex dos bytes exatos do nome do botao."""
        if getattr(self, "_btnmap", None):
            return self._btnmap  # type: ignore[return-value]
        raw = self.command("BUTTONS")
        by_name: dict[str, str] = {}
        for item in raw.split(","):
            if ":" in item:
                hx, name = item.split(":", 1)
                by_name[name] = hx
        out: dict[str, str] = {}
        for alias, cands in self._ALIASES.items():
            for c in cands:
                if c in by_name:
                    out[alias] = by_name[c]
                    break
        self._btnmap = out  # type: ignore[attr-defined]
        return out

    def buttons(self) -> dict[str, str]:
        """Aliases disponiveis neste core (para diagnostico)."""
        return dict(self._button_map())

    def press(self, button: str, frames: int = 2) -> None:
        """Aperta um botao. Aceita alias amigavel ('right', 'cross') ou o
        nome exato do core."""
        hx = self._button_map().get(button.strip().lower())
        if hx:
            self.command(f"PRESSHEX {hx} {frames}")
        else:
            self.command(f"PRESS {button} {frames}")

    def sequence(self, seq: str) -> None:
        """seq no formato 'down:2,down:2,cross:2'."""
        for item in seq.split(","):
            item = item.strip()
            if not item:
                continue
            btn, _, fr = item.partition(":")
            self.press(btn, int(fr) if fr.isdigit() else 2)

    def frame_advance(self, n: int = 1) -> int:
        return int(self.command(f"FRAME {n}"))

    def screenshot(self, path: str) -> str:
        return self.command(f"SCREENSHOT {path}")

    def speed(self, percent: int) -> None:
        self.command(f"SPEED {percent}")

    def savestate(self, path: str) -> None:
        self.command(f"SAVESTATE {path}")

    def loadstate(self, path: str) -> None:
        self.command(f"LOADSTATE {path}")
