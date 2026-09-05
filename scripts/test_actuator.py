"""EXODIA-4B :: testa o atuador em laco fechado.

Abre a mao e tenta pousar o cursor em cada carta, conferindo pela RAM em vez
de contar cliques. Registra quantos passos cada alvo custou e tira screenshot
de cada parada, para comparar com a tela.

Uso:
    python scripts/test_actuator.py --load saibau
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from exodia import cards, state as st  # noqa: E402
from exodia.actuator import Actuator  # noqa: E402
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
    args = ap.parse_args()

    out = ROOT / "runs" / "actuator"
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
    try:
        b.start_after_listen(timeout=180)
        RAM = b.main_ram()
        b.speed(900)
        b.loadstate(str(ROOT / "runs" / "states" / f"{args.load}.State"))
        b.frame_advance(2)

        act = Actuator(b, RAM)
        act.open_hand()
        # deixa a animacao de abertura terminar antes de mexer
        act.wait_stable(st.SELECTED_CARD)

        gs = st.read(b, RAM)
        alvos = [r.card_id for r in gs.records
                 if r.live and not r.is_opponent][:5]
        print("cartas alvo (dos registros do jogador):")
        for cid in alvos:
            print(f"  {cid:4}  {cards.name(cid)}")
        print(f"\ncursor inicial: {act.cursor_card()} "
              f"({cards.name(act.cursor_card())})\n")

        ok = falhou = 0
        for cid in alvos:
            achou = act.move_cursor_to_card(cid)
            pousou = act.cursor_card()
            status = "OK " if achou else "FALHOU"
            if achou:
                ok += 1
            else:
                falhou += 1
            print(f"  alvo {cid:4} {cards.name(cid)[:26]:26} -> "
                  f"cursor {pousou:4} {cards.name(pousou)[:22]:22} {status}")
            shot = out / f"alvo_{cid}.png"
            b.screenshot(str(shot))
            time.sleep(0.25)

        print(f"\nresultado: {ok} acertos, {falhou} falhas")
        print(f"screenshots em {out}")
        return 0 if falhou == 0 else 1
    except BridgeError as exc:
        print("ERRO:", exc)
        return 1
    finally:
        b.close()


if __name__ == "__main__":
    raise SystemExit(main())
