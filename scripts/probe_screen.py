"""EXODIA-4B :: que endereco distingue a VISAO DE CAMPO da MAO?

`OVERLAY_OPEN` (0x8009B0AC) foi eleito para esse papel e reprovou: mede 1 nas
duas telas. O estrago e grande porque `close_overlay()` confia nele para
decidir se aperta START - e START na visao de campo ENCERRA O TURNO. Ou seja,
uma leitura errada faz o agente passar o proprio turno achando que estava
fechando uma janela.

Este script aperta uma sequencia conhecida de botoes e, a cada passo, anota os
candidatos e tira um screenshot. A tela e a prova; a RAM e so a hipotese.

Uso:
    python scripts/probe_screen.py --load meu_turno
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from exodia import cards, state as st  # noqa: E402
from exodia.actuator import Actuator  # noqa: E402
from exodia.bridge import Bridge, BridgeError  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
EMUHAWK = ROOT / "tools" / "BizHawk" / "EmuHawk.exe"
LUA = ROOT / "exodia" / "bridge.lua"
ISO = (ROOT / "[PS1]_Yu-Gi-Oh! Forbidden Memories (PT-BR)"
       / "Yu-Gi-Oh! Forbidden Memories (PT-BR).cue")
HOST, PORT = "127.0.0.1", 55355

# Candidatos a "que tela estou vendo". Todos ja foram observados variando por
# tela em algum momento; nenhum foi confirmado.
CANDIDATOS = {
    "MENU_ID": (st.MENU_ID, 1),
    "MODE": (st.MODE_BYTE, 1),
    "OVERLAY": (st.OVERLAY_OPEN, 1),
    "OVERLAY_ALT": (st.OVERLAY_OPEN_ALT, 1),
    "VIEW_FLAG": (st.VIEW_FLAG, 1),
    "SELECTED": (st.SELECTED_CARD, 2),
}

# Sequencia deliberada: sai do campo, entra na mao, anda, volta.
PASSOS = [
    ("(inicial)", None),
    ("start", "start"),
    ("right", "right"),
    ("right", "right"),
    ("start", "start"),
    ("circle", "circle"),
]


def ler(b: Bridge, ram: str) -> dict[str, int]:
    out = {}
    for nome, (addr, tam) in CANDIDATOS.items():
        out[nome] = (b.read_u8(addr, ram) if tam == 1
                     else b.read_u16(addr, ram))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--load", default="meu_turno")
    args = ap.parse_args()

    out = ROOT / "runs" / "telas"
    out.mkdir(parents=True, exist_ok=True)

    b = Bridge(HOST, PORT)
    b.listen()
    subprocess.Popen(
        [str(EMUHAWK), f"--socket_ip={HOST}", f"--socket_port={PORT}",
         f"--lua={LUA}", str(ISO)],
        cwd=str(EMUHAWK.parent),
    )
    try:
        b.start_after_listen(timeout=180)
        RAM = b.main_ram()
        b.speed(900)
        b.loadstate(str(ROOT / "runs" / "states" / f"{args.load}.State"))
        b.frame_advance(30)
        act = Actuator(b, RAM)
        act.wait_for_idle()

        cab = f"{'passo':12}" + "".join(f"{k:>13}" for k in CANDIDATOS)
        cab += f"{'mao':>5}{'campo':>6}{'op':>4}  cursor"
        print(cab)
        print("-" * len(cab))

        for i, (rotulo, botao) in enumerate(PASSOS):
            if botao:
                b.press(botao, 4)
                act.wait_for_idle(stable_for=30)
            vals = ler(b, RAM)
            gs = st.read(b, RAM)
            c = cards.get(vals["SELECTED"])
            linha = f"{rotulo:12}" + "".join(
                f"{vals[k]:>13}" for k in CANDIDATOS)
            linha += (f"{len(gs.hand):>5}{len(gs.field):>6}"
                      f"{len(gs.opponent_field):>4}  "
                      f"{c.name[:22] if c else '-'}")
            print(linha)
            b.screenshot(str(out / f"{i}_{rotulo.strip('()')}.png"))

        print(f"\nscreenshots em {out}")
        print("\nOlhe as imagens e case cada linha com a tela. O endereco que "
              "muda EXATAMENTE quando a tela muda e o candidato bom.")
        return 0
    except BridgeError as exc:
        print("ERRO:", exc)
        return 1
    finally:
        b.close()


if __name__ == "__main__":
    raise SystemExit(main())
