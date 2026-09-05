"""EXODIA-4B :: gera um savestate limpo no comeco do NOSSO turno.

O savestate `saibau` carrega numa selecao onde so o Enter funciona, o que
falseia qualquer teste de botao: parece que nada responde quando na verdade
nao ha acao disponivel. Este script passa o turno, deixa o oponente jogar, e
grava o estado no momento em que o controle volta para nos.

Uso:
    python scripts/make_state.py --from saibau --save meu_turno
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from exodia import state as st  # noqa: E402
from exodia.actuator import Actuator  # noqa: E402
from exodia.bridge import Bridge, BridgeError  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
EMUHAWK = ROOT / "tools" / "BizHawk" / "EmuHawk.exe"
LUA = ROOT / "exodia" / "bridge.lua"
ISO = (ROOT / "[PS1]_Yu-Gi-Oh! Forbidden Memories (PT-BR)"
       / "Yu-Gi-Oh! Forbidden Memories (PT-BR).cue")
HOST, PORT = "127.0.0.1", 55355


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="origem", default="saibau")
    ap.add_argument("--save", default="meu_turno")
    ap.add_argument("--turns", type=int, default=1,
                    help="quantos turnos passar antes de gravar")
    args = ap.parse_args()

    out = ROOT / "runs" / "estados"
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
        b.loadstate(str(ROOT / "runs" / "states" / f"{args.origem}.State"))
        b.frame_advance(4)

        act = Actuator(b, RAM)
        act.wait_for_idle()
        print("estado de origem:")
        print(st.read(b, RAM).render())

        for i in range(args.turns):
            ok = act.end_turn()
            g = st.read(b, RAM)
            print(f"\npassou turno {i}: {'oponente jogou' if ok else 'nada mudou'}"
                  f"  |  LP {g.lp_player} x {g.lp_opponent}"
                  f"  campo_op {len(g.opponent_field)}")

        act.wait_for_idle(stable_for=60)
        destino = ROOT / "runs" / "states" / f"{args.save}.State"
        b.savestate(str(destino))
        time.sleep(0.6)

        g = st.read(b, RAM)
        print(f"\nsavestate gravado: {destino.name} "
              f"({destino.stat().st_size if destino.exists() else 0} bytes)")
        print(f"cursor na mao: {int(act.cursor_on_hand())}")
        print()
        print(g.render())
        b.screenshot(str(out / f"{args.save}.png"))
        time.sleep(0.3)
        print(f"\nscreenshot: {out / (args.save + '.png')}")
        return 0
    except BridgeError as exc:
        print("ERRO:", exc)
        return 1
    finally:
        b.close()


if __name__ == "__main__":
    raise SystemExit(main())
