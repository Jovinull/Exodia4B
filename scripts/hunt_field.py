"""EXODIA-4B :: caca ao estado de CAMPO (V4 - guardian star).

Dirige o duelo apertando botoes ate que algum registro de carta ganhe a flag
0x0400 (monstro em campo). Quando isso acontece, despeja os 28 bytes do
registro para descobrir onde vive a guardian star.

Tambem registra, a cada passo, quais BYTES da regiao dos registros mudaram -
util para localizar campos ainda desconhecidos.

Uso:
    python scripts/hunt_field.py --steps 40
"""

from __future__ import annotations

import argparse
import struct
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from exodia import cards  # noqa: E402
from exodia.bridge import Bridge, BridgeError  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
EMUHAWK = ROOT / "tools" / "BizHawk" / "EmuHawk.exe"
LUA = ROOT / "exodia" / "bridge.lua"
ISO = (ROOT / "[PS1]_Yu-Gi-Oh! Forbidden Memories (PT-BR)"
       / "Yu-Gi-Oh! Forbidden Memories (PT-BR).cue")
HOST, PORT = "127.0.0.1", 55355

CARD_RECORDS = 0x801A7AE4
STRIDE = 28
NREC = 16
FLAG_LIVE, FLAG_FIELD = 0x8000, 0x0400
LP1, LP2 = 0x800EA004, 0x800EA024

# ciclo de botoes que costuma abrir a mao, escolher carta e confirmar posicao
CYCLE = ["cross", "cross", "cross", "down", "cross", "cross",
         "right", "cross", "cross", "circle"]


def decode(blob: bytes):
    out = []
    for i in range(NREC):
        rec = blob[i * STRIDE:(i + 1) * STRIDE]
        cid, atk, dfs = struct.unpack_from("<HHH", rec, 0)
        flags, = struct.unpack_from("<H", rec, 10)
        slot, = struct.unpack_from("<H", rec, 12)
        out.append((i, cid, atk, dfs, flags, slot, rec))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--load", default="saibau")
    ap.add_argument("--steps", type=int, default=40)
    ap.add_argument("--frames", type=int, default=60)
    args = ap.parse_args()

    out = ROOT / "runs" / "hunt"
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

        prev = b.read_bytes(CARD_RECORDS, STRIDE * NREC, RAM)
        print(f"{'passo':>5} {'botao':>7} {'lp1':>5} {'lp2':>5} "
              f"{'campo':>5}  bytes que mudaram")
        found = False
        for step in range(args.steps):
            btn = CYCLE[step % len(CYCLE)]
            b.press(btn, 3)
            b.frame_advance(args.frames)

            blob = b.read_bytes(CARD_RECORDS, STRIDE * NREC, RAM)
            recs = decode(blob)
            onfield = [r for r in recs if r[4] & FLAG_FIELD]

            changed = sorted({(i % STRIDE) for i in range(len(blob))
                              if blob[i] != prev[i]})
            prev = blob
            lp1, lp2 = b.read_u16(LP1, RAM), b.read_u16(LP2, RAM)
            print(f"{step:5} {btn:>7} {lp1:5} {lp2:5} {len(onfield):5}  "
                  f"{changed if len(changed) < 14 else 'muitos'}")

            if onfield and not found:
                found = True
                print("\n*** MONSTRO EM CAMPO DETECTADO ***")
                for (i, cid, atk, dfs, flags, slot, rec) in onfield:
                    c = cards.get(cid)
                    print(f"  #{i} {c.name if c else '???'} "
                          f"atk={atk} def={dfs} flags=0x{flags:04X} slot={slot}")
                    print(f"     GsA={c.guardian_a if c else '?'} "
                          f"GsB={c.guardian_b if c else '?'}")
                    print(f"     raw {rec.hex(' ')}")
                    for o in range(6, 28):
                        if rec[o]:
                            print(f"       +{o:2} = {rec[o]}")
                shot = out / f"campo_{step:03d}.png"
                b.screenshot(str(shot))
                time.sleep(0.6)
                print("  screenshot:", shot)
                b.savestate(str(ROOT / "runs" / "states" / "campo.State"))
                time.sleep(0.5)
                print("  savestate: campo.State")

        if not found:
            print("\nnenhum monstro chegou ao campo nesta sequencia")
        return 0
    except BridgeError as exc:
        print("ERRO:", exc)
        return 1
    finally:
        b.close()


if __name__ == "__main__":
    raise SystemExit(main())
