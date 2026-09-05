"""EXODIA-4B :: prova que 0x8009B0AC e paridade de frame, nao flag de menu.

Este endereco foi usado por varias sessoes como "tem sobreposicao aberta?". Era
o que `close_overlay()` consultava para decidir se apertava START - e START na
visao de campo ENCERRA O TURNO. Resultado: o harness passava o proprio turno no
meio de uma jogada, na sorte, e as invocacoes e ataques "falhavam sem motivo".

O script existe para nao deixar essa conclusao virar folclore. Ele mede duas
vezes o mesmo endereco, mudando so o intervalo entre as leituras:

  1 frame entre leituras  -> 101010101010...   alterna todo frame
  4 frames entre leituras -> 111111111111...   parece constante

A segunda linha e a armadilha inteira. O atuador usa `settle_frames = 4`, entao
todas as amostras historicas cairam na mesma fase da onda. Um bit que alterna a
cada frame, amostrado de 4 em 4, parece uma flag estavel - e foi assim que ele
"passou" na validacao em 5 savestates diferentes.

Licao geral, que vale para qualquer endereco novo: **antes de dar significado a
um byte, confira se ele nao esta apenas sincronizado com a sua taxa de
amostragem.**

Uso:
    python scripts/check_parity.py --load meu_turno
"""

from __future__ import annotations

import argparse
import subprocess
import sys
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


def amostrar(b: Bridge, ram: str, addr: int, n: int, passo: int) -> str:
    saida = []
    for _ in range(n):
        saida.append(str(b.read_u8(addr, ram)))
        b.frame_advance(passo)
    return "".join(saida)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--load", default="meu_turno")
    ap.add_argument("--amostras", type=int, default=40)
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
        b.loadstate(str(ROOT / "runs" / "states" / f"{args.load}.State"))
        b.frame_advance(60)

        print(f"endereco 0x{st.FRAME_PARITY:08X}, sem apertar nenhum botao\n")
        p1 = amostrar(b, RAM, st.FRAME_PARITY, args.amostras, 1)
        print(f"  1 frame entre leituras : {p1}")
        p4 = amostrar(b, RAM, st.FRAME_PARITY, args.amostras, 4)
        print(f"  4 frames entre leituras: {p4}")

        alterna = all(p1[i] != p1[i + 1] for i in range(len(p1) - 1))
        constante = len(set(p4)) == 1
        print("\nVEREDITO")
        if alterna and constante:
            print("  alterna a cada frame e parece constante de 4 em 4:")
            print("  E PARIDADE DE FRAME. Nao use como flag de tela.")
            return 0
        print(f"  comportamento diferente do documentado "
              f"(alterna={alterna}, constante_em_4={constante}).")
        print("  Vale reabrir a investigacao e corrigir state.py.")
        return 1
    except BridgeError as exc:
        print("ERRO:", exc)
        return 1
    finally:
        b.close()


if __name__ == "__main__":
    raise SystemExit(main())
