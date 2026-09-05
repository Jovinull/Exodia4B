"""EXODIA-4B :: verificacao do layout da RAM do duelo.

Testa hipoteses sobre a RAM e cruza tudo com a base de cartas.

    H1  hand[i][4:6] e o indice da carta no deck embaralhado (0x80177FE8)
    V4  guardian star esta em algum offset desconhecido do registro de 28 bytes
    V6  deck (0x801D0200) e bau (0x801D0250) sao legiveis

Uso:
    python scripts/check_ram_layout.py --load saibau
"""

from __future__ import annotations

import argparse
import struct
import subprocess
import sys
import time
from collections import Counter
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
HAND = 0x801A7E20
SHUFFLED_DECK = 0x80177FE8       # 80 bytes = 40 x u16  (uso APENAS de validacao)
PLAYER_DECK = 0x801D0200         # 80 bytes
TRUNK = 0x801D0250               # 722 bytes
LP1, LP2 = 0x800EA004, 0x800EA024


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--load", default="saibau")
    ap.add_argument("--advance", type=int, default=200)
    args = ap.parse_args()

    print(f"base de cartas: {cards.count()} cartas carregadas\n")

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
        b.press("cross", 3)
        b.frame_advance(args.advance)

        print(f"LP {b.read_u16(LP1, RAM)} x {b.read_u16(LP2, RAM)}\n")

        # ---------------------------------------------------------------- mao
        hand_raw = b.read_bytes(HAND, 30, RAM)
        hand = []
        for i in range(5):
            e = hand_raw[i * 6:(i + 1) * 6]
            cid = int.from_bytes(e[0:2], "little")
            s1, s2 = e[2], e[3]
            deck_idx = int.from_bytes(e[4:6], "little")
            hand.append((cid, s1, s2, deck_idx))

        print("MAO (0x801A7E20):")
        for i, (cid, s1, s2, di) in enumerate(hand):
            c = cards.get(cid)
            print(f"  [{i}] id={cid:4} slot={s1},{s2} deck_idx={di:3}  "
                  f"{c.short() if c else '???'}")

        # ------------------------------------------------- H1: deck embaralhado
        print("\nH1: hand[4:6] e indice no deck NAO embaralhado (0x801D0200)?")
        pdeck = list(struct.unpack("<40H", b.read_bytes(PLAYER_DECK, 80, RAM)))
        shuffled = list(struct.unpack("<40H",
                                      b.read_bytes(SHUFFLED_DECK, 80, RAM)))
        print(f"  deck embaralhado[0:6] : {shuffled[:6]}  "
              f"(os 5 primeiros sao a mao)")
        hits = 0
        for i, (cid, _, _, di) in enumerate(hand):
            got = pdeck[di] if 0 <= di < 40 else None
            ok = got == cid
            hits += ok
            print(f"  mao[{i}] id={cid:4} -> deck_jogador[{di:2}]={got}  "
                  f"{'MATCH' if ok else 'x'}")
        print(f"  => {hits}/5  "
              f"{'HIPOTESE CONFIRMADA' if hits == 5 else 'hipotese refutada'}")

        # --------------------------------------------- V4: guardian star / raw
        print("\nV4: offsets desconhecidos do registro de 28 bytes")
        blob = b.read_bytes(CARD_RECORDS, STRIDE * 8, RAM)
        for i in range(8):
            rec = blob[i * STRIDE:(i + 1) * STRIDE]
            cid, atk, dfs = struct.unpack_from("<HHH", rec, 0)
            flags, = struct.unpack_from("<H", rec, 10)
            if cid == 0 and flags == 0 and atk == 0:
                continue
            c = cards.get(cid)
            print(f"  #{i} {c.name[:28] if c else '???':28} "
                  f"GsA={c.guardian_a if c else '?'} GsB={c.guardian_b if c else '?'}")
            print(f"     raw {rec.hex(' ')}")
            vals = {o: rec[o] for o in (6, 7, 8, 9, 14, 15, 16, 17, 18, 19)}
            print("     bytes " + " ".join(f"+{o}={v}" for o, v in vals.items()))

        # ------------------------------------------------------ V6: deck e bau
        print("\nV6: deck do jogador e bau")
        known = [x for x in pdeck if 1 <= x <= 722]
        print(f"  deck (0x801D0200): {len(known)}/40 ids plausiveis")
        print(f"    primeiros 8: "
              f"{[cards.name(x)[:16] for x in pdeck[:8]]}")

        trunk = b.read_bytes(TRUNK, 722, RAM)
        owned = sum(1 for v in trunk if v > 0)
        total = sum(trunk)
        print(f"  bau  (0x801D0250): {owned} tipos de carta com copias, "
              f"{total} cartas no total")
        top = Counter({i + 1: v for i, v in enumerate(trunk) if v}).most_common(6)
        for cid, qty in top:
            print(f"    {qty:3}x {cards.name(cid)}")
        return 0
    except BridgeError as exc:
        print("ERRO:", exc)
        return 1
    finally:
        b.close()
        time.sleep(0.2)


if __name__ == "__main__":
    raise SystemExit(main())
