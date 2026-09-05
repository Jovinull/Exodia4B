"""EXODIA-4B :: sonda de botoes.

Para cada botao: recarrega o MESMO savestate, aperta so aquele botao, tira
screenshot e mede o que mudou na RAM. Isola o efeito de cada botao sem
interferencia dos anteriores.

Uso:
    python scripts/probe_buttons.py --load saibau
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from exodia.bridge import Bridge, BridgeError  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
EMUHAWK = ROOT / "tools" / "BizHawk" / "EmuHawk.exe"
LUA = ROOT / "exodia" / "bridge.lua"
ISO = (ROOT / "[PS1]_Yu-Gi-Oh! Forbidden Memories (PT-BR)"
       / "Yu-Gi-Oh! Forbidden Memories (PT-BR).cue")
HOST, PORT = "127.0.0.1", 55355

CARD_RECORDS = 0x801A7AE4
HAND = 0x801A7E20
PROBE = [(0x800EA004, 2, "lp1"), (0x800EA024, 2, "lp2"),
         (0x80184594, 1, "menu"), (0x8009B26C, 1, "mode"),
         (0x8009B1D5, 1, "turn"), (0x8009B338, 2, "sel_card"),
         (0x8009B364, 1, "terrain")]

BUTTONS = ["none", "cross", "circle", "square", "triangle",
           "start", "select", "up", "down", "left", "right", "l1", "r1"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--load", default="saibau")
    ap.add_argument("--hold", type=int, default=4)
    ap.add_argument("--frames", type=int, default=120)
    args = ap.parse_args()

    out = ROOT / "runs" / "probe"
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.png"):
        old.unlink()

    b = Bridge(HOST, PORT)
    b.listen()
    subprocess.Popen(
        [str(EMUHAWK), f"--socket_ip={HOST}", f"--socket_port={PORT}",
         f"--lua={LUA}", str(ISO)],
        cwd=str(EMUHAWK.parent),
    )
    state = str(ROOT / "runs" / "states" / f"{args.load}.State")
    try:
        b.start_after_listen(timeout=180)
        RAM = b.main_ram()
        b.speed(900)
        print("aliases resolvidos:", sorted(b.buttons()))
        print()

        baseline_hash = None
        base_vals = None
        print(f"{'botao':>9}  {'tela':>8}  valores")
        for btn in BUTTONS:
            b.loadstate(state)
            b.frame_advance(2)
            if btn != "none":
                b.press(btn, args.hold)
            b.frame_advance(args.frames)

            vals = {}
            for addr, size, nm in PROBE:
                vals[nm] = (b.read_u16(addr, RAM) if size == 2
                            else b.read_u8(addr, RAM))
            recs = b.read_bytes(CARD_RECORDS, 28 * 8, RAM)
            hand = b.read_bytes(HAND, 30, RAM)

            shot = out / f"{btn}.png"
            b.screenshot(str(shot))
            for _ in range(40):
                if shot.exists() and shot.stat().st_size > 0:
                    break
                time.sleep(0.05)
            h = hashlib.md5(shot.read_bytes()).hexdigest() if shot.exists() else "?"

            if btn == "none":
                baseline_hash, base_vals = h, vals
                base_recs, base_hand = recs, hand
                print(f"{btn:>9}  {'BASE':>8}  {vals}")
                continue

            tela = "igual" if h == baseline_hash else "MUDOU"
            diff = {k: (base_vals[k], v) for k, v in vals.items()
                    if v != base_vals[k]}
            extra = []
            if recs != base_recs:
                extra.append("REGISTROS mudaram")
            if hand != base_hand:
                extra.append("MAO mudou")
            print(f"{btn:>9}  {tela:>8}  {diff if diff else ''} "
                  f"{' '.join(extra)}")
        print(f"\nscreenshots em {out}")
        return 0
    except BridgeError as exc:
        print("ERRO:", exc)
        return 1
    finally:
        b.close()


if __name__ == "__main__":
    raise SystemExit(main())
