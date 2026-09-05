"""EXODIA-4B :: inspeciona o estado de um duelo na RAM.

Valida V2: o array de registros de carta em 0x801A7AE4 (stride 28), minerado
do fonte da recompilacao (psx_fusion_assist.c):

    +0  u16 Card ID
    +2  u16 ATK
    +4  u16 DEF
    +10 u16 Flags  (0x8000 = carta viva, 0x0400 = monstro em campo)
    +12 u16 slot

Uso:
    python scripts/inspect_duel.py --load saibau --advance 300
"""

from __future__ import annotations

import argparse
import struct
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
STRIDE = 28
HAND = 0x801A7E20
LP1, LP2 = 0x800EA004, 0x800EA024

FLAG_LIVE = 0x8000
FLAG_FIELD = 0x0400


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--load", default="saibau")
    ap.add_argument("--advance", type=int, default=0)
    ap.add_argument("--press", default="")
    ap.add_argument("--count", type=int, default=30, help="registros a ler")
    ap.add_argument("--raw", action="store_true",
                    help="mostra os 28 bytes crus e os offsets desconhecidos")
    ap.add_argument("--tag", default="duelo")
    args = ap.parse_args()

    out = ROOT / "runs" / args.tag
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

        for item in [x for x in args.press.split(",") if x.strip()]:
            b.press(item.strip(), 3)
            b.frame_advance(30)
        if args.advance:
            b.frame_advance(args.advance)

        lp1 = b.read_u16(LP1, RAM)
        lp2 = b.read_u16(LP2, RAM)
        print(f"LP voce={lp1}  LP oponente={lp2}\n")

        blob = b.read_bytes(CARD_RECORDS, STRIDE * args.count, RAM)
        print(f"{'#':>3} {'id':>5} {'atk':>5} {'def':>5} {'flags':>6} "
              f"{'slot':>4}  interpretacao")
        vivos = 0
        for i in range(args.count):
            rec = blob[i * STRIDE:(i + 1) * STRIDE]
            cid, atk, dfs = struct.unpack_from("<HHH", rec, 0)
            flags, = struct.unpack_from("<H", rec, 10)
            slot, = struct.unpack_from("<H", rec, 12)
            if cid == 0 and flags == 0 and atk == 0:
                continue
            vivos += 1
            tags = []
            if flags & FLAG_LIVE:
                tags.append("VIVA")
            if flags & FLAG_FIELD:
                tags.append("CAMPO")
            print(f"{i:3} {cid:5} {atk:5} {dfs:5} 0x{flags:04X} "
                  f"{slot:4}  {' '.join(tags)}")
            if args.raw:
                # offsets conhecidos: 0-1 id, 2-3 atk, 4-5 def, 10-11 flags,
                # 12-13 slot. O resto e o que precisamos identificar (V4).
                print(f"      raw : {rec.hex(' ')}")
                unk = {6: rec[6:8], 8: rec[8:10], 14: rec[14:16],
                       16: rec[16:18], 18: rec[18:20], 20: rec[20:22],
                       22: rec[22:24], 24: rec[24:26], 26: rec[26:28]}
                desc = "  ".join(
                    f"+{o}={int.from_bytes(v, 'little')}"
                    for o, v in unk.items())
                print(f"      desc: {desc}")
        print(f"\nregistros nao-vazios: {vivos}")

        hand = b.read_bytes(HAND, 30, RAM)
        print("\nmao (0x801A7E20, 30 bytes):")
        print("  hex :", hand.hex(" "))
        print("  u16 :", list(struct.unpack("<15H", hand)))

        shot = out / "inspect.png"
        b.screenshot(str(shot))
        time.sleep(0.8)
        print("\nscreenshot:", shot)
        return 0
    except BridgeError as exc:
        print("ERRO:", exc)
        return 1
    finally:
        b.close()


if __name__ == "__main__":
    raise SystemExit(main())
