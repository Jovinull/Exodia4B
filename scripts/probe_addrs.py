"""EXODIA-4B :: le enderecos escolhidos em varios savestates.

Depois que o ram_diff aponta candidatos, este script confere o valor de cada um
em varias situacoes conhecidas. Um candidato so vira endereco confiavel se o
padrao se repetir em todas elas.

Uso:
    python scripts/probe_addrs.py --states pos_summon campo_livre mao_aberta \
        --addrs 8009B0AC:1 8009B124:1 8009B327:1
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--states", nargs="+", required=True)
    ap.add_argument("--addrs", nargs="+", required=True,
                    help="endereco:tamanho em hex, ex 8009B0AC:1")
    ap.add_argument("--settle", type=int, default=8)
    args = ap.parse_args()

    alvos = []
    for a in args.addrs:
        end, _, tam = a.partition(":")
        alvos.append((int(end, 16), int(tam or "1")))

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

        tabela: dict[str, list[int]] = {}
        for nome in args.states:
            p = ROOT / "runs" / "states" / f"{nome}.State"
            if not p.exists():
                print(f"(pulando {nome}: nao existe)")
                continue
            b.loadstate(str(p))
            b.frame_advance(args.settle)
            linha = []
            for end, tam in alvos:
                if tam == 1:
                    linha.append(b.read_u8(end, RAM))
                elif tam == 2:
                    linha.append(b.read_u16(end, RAM))
                else:
                    linha.append(b.read_u32(end, RAM))
            tabela[nome] = linha

        cab = "estado".ljust(16) + "".join(
            f"0x{e:08X}".rjust(13) for e, _ in alvos)
        print(cab)
        print("-" * len(cab))
        for nome, linha in tabela.items():
            print(nome.ljust(16) + "".join(str(v).rjust(13) for v in linha))

        print("\n--- estabilidade por endereco ---")
        for i, (end, _) in enumerate(alvos):
            vals = [linha[i] for linha in tabela.values()]
            distintos = len(set(vals))
            veredito = ("constante (nao distingue)" if distintos == 1
                        else f"{distintos} valores distintos")
            print(f"  0x{end:08X}: {vals}  -> {veredito}")
        return 0
    except BridgeError as exc:
        print("ERRO:", exc)
        return 1
    finally:
        b.close()


if __name__ == "__main__":
    raise SystemExit(main())
