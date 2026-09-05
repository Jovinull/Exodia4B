"""EXODIA-4B :: compara a RAM entre dois savestates.

Serve para achar endereco de coisa que nao esta documentada: coloque o jogo em
duas situacoes que diferem por UMA caracteristica, salve um state em cada, e
veja quais bytes mudaram.

Le por blocos via socket, entao vale restringir as regioes. As faixas padrao
cobrem onde o estado do duelo ja se mostrou vivo.

Uso:
    python scripts/ram_diff.py --a pos_summon --b campo_livre
    python scripts/ram_diff.py --a x --b y --regions 9B000:1000 E9000:2000
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from exodia.bridge import Bridge, BridgeError  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
EMUHAWK = ROOT / "tools" / "BizHawk" / "EmuHawk.exe"
LUA = ROOT / "exodia" / "bridge.lua"
ISO = (ROOT / "[PS1]_Yu-Gi-Oh! Forbidden Memories (PT-BR)"
       / "Yu-Gi-Oh! Forbidden Memories (PT-BR).cue")
HOST, PORT = "127.0.0.1", 55355

# offset dentro da MainRAM : tamanho
REGIOES_PADRAO = ["09B000:2000", "0E9000:2000", "184000:2000", "1A7000:2000"]
CHUNK = 512


def ler_regioes(b: Bridge, ram: str, regioes: list[tuple[int, int]]) -> dict:
    dados = {}
    for base, tam in regioes:
        buf = bytearray()
        for off in range(0, tam, CHUNK):
            n = min(CHUNK, tam - off)
            buf += b.read_bytes(base + off, n, ram)
        dados[base] = bytes(buf)
    return dados


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", required=True, help="savestate A")
    ap.add_argument("--b", required=True, help="savestate B")
    ap.add_argument("--regions", nargs="*", default=REGIOES_PADRAO,
                    help="offset:tamanho em hex, dentro da MainRAM")
    ap.add_argument("--max-show", type=int, default=60)
    ap.add_argument("--settle", type=int, default=8, help="frames apos load")
    args = ap.parse_args()

    regioes = []
    for r in args.regions:
        base, _, tam = r.partition(":")
        regioes.append((int(base, 16), int(tam or "1000", 16)))

    bridge = Bridge(HOST, PORT)
    bridge.listen()
    subprocess.Popen(
        [str(EMUHAWK), f"--socket_ip={HOST}", f"--socket_port={PORT}",
         f"--lua={LUA}", str(ISO)],
        cwd=str(EMUHAWK.parent),
    )
    try:
        bridge.start_after_listen(timeout=180)
        RAM = bridge.main_ram()
        bridge.speed(900)

        leituras = {}
        for nome in (args.a, args.b):
            p = ROOT / "runs" / "states" / f"{nome}.State"
            if not p.exists():
                print(f"savestate nao existe: {p}")
                return 1
            bridge.loadstate(str(p))
            bridge.frame_advance(args.settle)
            leituras[nome] = ler_regioes(bridge, RAM, regioes)
            total = sum(len(v) for v in leituras[nome].values())
            print(f"lido {nome}: {total} bytes")

        A, B = leituras[args.a], leituras[args.b]
        difs: list[tuple[int, int, int]] = []
        for base in A:
            for i, (x, y) in enumerate(zip(A[base], B[base])):
                if x != y:
                    difs.append((base + i, x, y))

        print(f"\n{len(difs)} bytes diferentes entre '{args.a}' e '{args.b}'")
        if not difs:
            return 0

        # agrupa enderecos vizinhos, que costumam ser o mesmo campo
        grupos: list[list[tuple[int, int, int]]] = [[difs[0]]]
        for d in difs[1:]:
            if d[0] - grupos[-1][-1][0] <= 3:
                grupos[-1].append(d)
            else:
                grupos.append([d])

        print(f"agrupados em {len(grupos)} regioes contiguas\n")
        print(f"{'endereco PS1':>14} {'tam':>4} {args.a[:10]:>12} "
              f"{args.b[:10]:>12}")
        for g in grupos[:args.max_show]:
            ini = g[0][0]
            va = int.from_bytes(bytes(x for _, x, _ in g), "little")
            vb = int.from_bytes(bytes(y for _, _, y in g), "little")
            print(f"  0x{0x80000000 | ini:08X} {len(g):4} {va:12} {vb:12}")
        if len(grupos) > args.max_show:
            print(f"  ... e mais {len(grupos) - args.max_show} regioes")
        return 0
    except BridgeError as exc:
        print("ERRO:", exc)
        return 1
    finally:
        bridge.close()


if __name__ == "__main__":
    raise SystemExit(main())
