"""EXODIA-4B :: decodifica o campo de flags dos registros de carta.

Cruza cada registro com o tipo da carta no banco para descobrir o que cada bit
significa, em vez de adivinhar. Le varios savestates para pegar situacoes
diferentes (mao, campo, oponente).

Uso:
    python scripts/decode_flags.py --states saibau mao_aberta maoaberta
"""

from __future__ import annotations

import argparse
import struct
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from exodia import cards  # noqa: E402
from exodia.bridge import Bridge, BridgeError  # noqa: E402
from exodia.state import CARD_RECORDS, RECORD_STRIDE  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
EMUHAWK = ROOT / "tools" / "BizHawk" / "EmuHawk.exe"
LUA = ROOT / "exodia" / "bridge.lua"
ISO = (ROOT / "[PS1]_Yu-Gi-Oh! Forbidden Memories (PT-BR)"
       / "Yu-Gi-Oh! Forbidden Memories (PT-BR).cue")
HOST, PORT = "127.0.0.1", 55355
NREC = 32


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--states", nargs="+", default=["saibau", "mao_aberta"])
    args = ap.parse_args()

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

        por_bit: dict[int, list[str]] = defaultdict(list)
        for name in args.states:
            p = ROOT / "runs" / "states" / f"{name}.State"
            if not p.exists():
                print(f"(pulando {name}: nao existe)")
                continue
            b.loadstate(str(p))
            b.frame_advance(4)
            blob = b.read_bytes(CARD_RECORDS, RECORD_STRIDE * NREC, RAM)
            print(f"\n=== {name} ===")
            print(f"{'#':>3} {'id':>4} {'flags':>7} {'bits':>18} "
                  f"{'tipo':>12}  carta")
            for i in range(NREC):
                rec = blob[i * RECORD_STRIDE:(i + 1) * RECORD_STRIDE]
                cid, atk, dfs = struct.unpack_from("<HHH", rec, 0)
                flags, = struct.unpack_from("<H", rec, 10)
                if cid == 0 and flags == 0 and atk == 0:
                    continue
                c = cards.get(cid)
                tipo = c.type_name if c else "?"
                bits = " ".join(f"{b:04X}" for b in
                                (1 << k for k in range(16)) if flags & b) or "-"
                print(f"{i:3} {cid:4} 0x{flags:04X} {bits:>18} "
                      f"{tipo:>12}  {c.name[:26] if c else '???'}")
                for k in range(16):
                    if flags & (1 << k):
                        por_bit[1 << k].append(f"{tipo}/{'op' if i >= 15 else 'eu'}")

        print("\n=== resumo por bit ===")
        for bit in sorted(por_bit):
            amostras = por_bit[bit]
            tipos = sorted({a.split('/')[0] for a in amostras})
            lados = sorted({a.split('/')[1] for a in amostras})
            print(f"  0x{bit:04X}: {len(amostras):3}x  lados={lados}  "
                  f"tipos={tipos[:6]}")
        return 0
    except BridgeError as exc:
        print("ERRO:", exc)
        return 1
    finally:
        b.close()


if __name__ == "__main__":
    raise SystemExit(main())
