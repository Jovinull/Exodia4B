"""EXODIA-4B :: dump_state - estado do duelo em texto ao vivo.

Mostra o GameState em texto sempre que ele muda, para comparar com a tela.
E o instrumento do criterio de saida da Fase 1: jogar um duelo inteiro com
isto rodando e o texto sempre batendo com o que aparece.

Uso:
    python scripts/dump_state.py --load saibau --watch 120
    python scripts/dump_state.py --no-launch --watch 300   # EmuHawk ja aberto
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from exodia import state as st  # noqa: E402
from exodia.bridge import Bridge, BridgeError  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
EMUHAWK = ROOT / "tools" / "BizHawk" / "EmuHawk.exe"
LUA = ROOT / "exodia" / "bridge.lua"
ISO = (ROOT / "[PS1]_Yu-Gi-Oh! Forbidden Memories (PT-BR)"
       / "Yu-Gi-Oh! Forbidden Memories (PT-BR).cue")
HOST, PORT = "127.0.0.1", 55355


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--load", default=None)
    ap.add_argument("--watch", type=int, default=120, help="segundos")
    ap.add_argument("--speed", type=int, default=100)
    ap.add_argument("--no-launch", action="store_true")
    args = ap.parse_args()

    b = Bridge(HOST, PORT)
    b.listen()
    if not args.no_launch:
        subprocess.Popen(
            [str(EMUHAWK), f"--socket_ip={HOST}", f"--socket_port={PORT}",
             f"--lua={LUA}", str(ISO)],
            cwd=str(EMUHAWK.parent),
        )
    try:
        b.start_after_listen(timeout=180)
        RAM = b.main_ram()
        if args.load:
            b.speed(900)
            b.loadstate(str(ROOT / "runs" / "states" / f"{args.load}.State"))
            b.frame_advance(2)
        b.speed(args.speed)

        print("=" * 62)
        print("dump_state ativo. Jogue no EmuHawk; o estado aparece aqui.")
        print("=" * 62)

        last = None
        end = time.time() + args.watch
        while time.time() < end:
            try:
                gs = st.read(b, RAM)
            except BridgeError:
                break
            key = (gs.lp_player, gs.lp_opponent, gs.menu_id, gs.mode,
                   tuple((r.card_id, r.flags, r.slot) for r in gs.records))
            if key != last:
                last = key
                print(f"\n--- menu={gs.menu_id} mode={gs.mode} "
                      f"cursor_card={gs.selected_card} "
                      f"{'EM DUELO' if gs.in_duel else 'fora de duelo'} ---")
                print(gs.render())
            time.sleep(0.3)
        return 0
    except BridgeError as exc:
        print("ERRO:", exc)
        return 1
    finally:
        b.close()


if __name__ == "__main__":
    raise SystemExit(main())
