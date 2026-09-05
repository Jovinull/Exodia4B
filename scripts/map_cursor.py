"""EXODIA-4B :: mapeia o cursor da mao no duelo.

Abre a mao com Start e anda com o D-pad lendo 0x8009B338 (card id sob o
cursor) a cada passo. Isso da o laco fechado que o atuador precisa: em vez de
contar cliques as cegas, ele move e CONFERE onde parou.

Uso:
    python scripts/map_cursor.py --load saibau
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from exodia import cards, state as st  # noqa: E402
from exodia.bridge import Bridge, BridgeError  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
EMUHAWK = ROOT / "tools" / "BizHawk" / "EmuHawk.exe"
LUA = ROOT / "exodia" / "bridge.lua"
ISO = (ROOT / "[PS1]_Yu-Gi-Oh! Forbidden Memories (PT-BR)"
       / "Yu-Gi-Oh! Forbidden Memories (PT-BR).cue")
HOST, PORT = "127.0.0.1", 55355


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--load", default="saibau")
    ap.add_argument("--frames", type=int, default=40)
    ap.add_argument("--save", default="mao_aberta")
    args = ap.parse_args()

    out = ROOT / "runs" / "cursor"
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
        b.frame_advance(2)

        gs = st.read(b, RAM)
        print("mao no inicio:")
        for i, r in enumerate(gs.hand):
            print(f"  [{i}] {cards.name(r.card_id)}")
        print(f"cursor antes de abrir a mao: {gs.selected_card} "
              f"({cards.name(gs.selected_card)})\n")

        b.press("start", 4)
        b.frame_advance(90)
        b.savestate(str(ROOT / "runs" / "states" / f"{args.save}.State"))
        time.sleep(0.4)
        print(f"mao aberta; savestate '{args.save}' gravado\n")

        seq = (["right"] * 6) + (["left"] * 6) + ["down", "up"]
        print(f"{'passo':>5} {'botao':>7} {'cursor':>7}  carta sob o cursor")
        cur = b.read_u16(st.SELECTED_CARD, RAM)
        print(f"{'-':>5} {'-':>7} {cur:7}  {cards.name(cur)}")
        for i, btn in enumerate(seq):
            b.press(btn, 3)
            b.frame_advance(args.frames)
            new = b.read_u16(st.SELECTED_CARD, RAM)
            mark = "" if new == cur else "  <- mudou"
            cur = new
            print(f"{i:5} {btn:>7} {cur:7}  {cards.name(cur)}{mark}")

        shot = out / "mao.png"
        b.screenshot(str(shot))
        time.sleep(0.6)
        print("\nscreenshot:", shot)
        return 0
    except BridgeError as exc:
        print("ERRO:", exc)
        return 1
    finally:
        b.close()


if __name__ == "__main__":
    raise SystemExit(main())
