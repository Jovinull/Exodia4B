"""EXODIA-4B :: testa o posicionamento do cursor por SLOT.

Endereçar por id de carta e ambiguo com copias repetidas. Aqui o cursor e
levado ate a ponta e conta passos a partir dela, sem depender de nenhum
endereco novo.

O teste pede cada slot da mao e confere se a carta que ficou sob o cursor e a
que o leitor de estado diz estar naquela posicao.

Uso:
    python scripts/test_slot.py --load meu_turno
"""

from __future__ import annotations

import argparse
import subprocess
import sys
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
    ap.add_argument("--load", default="meu_turno")
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
        b.frame_advance(4)

        act = Actuator(b, RAM)
        act.wait_for_idle()
        act.recover()
        act.ensure_hand_view()
        act.wait_for_idle(stable_for=20)

        mao = st.read(b, RAM).hand
        print("mao segundo o leitor de estado:")
        for i, r in enumerate(mao):
            print(f"  slot {i}: id={r.card_id:4} idx={r.index:2}  "
                  f"{cards.name(r.card_id)}")

        borda = act.home_cursor()
        print(f"\nborda esquerda: id={borda} ({cards.name(borda)})")

        print(f"\n{'slot':>5} {'esperado':>28} {'cursor parou em':>28}  ok")
        acertos = 0
        for slot, r in enumerate(mao):
            if not act.move_cursor_to_slot(slot):
                print(f"{slot:5} {cards.name(r.card_id)[:28]:>28} "
                      f"{'nao alcancou':>28}  x")
                continue
            achou = act.cursor_card()
            ok = achou == r.card_id
            acertos += ok
            print(f"{slot:5} {cards.name(r.card_id)[:28]:>28} "
                  f"{cards.name(achou)[:28]:>28}  {'ok' if ok else 'x'}")

        print(f"\n{acertos}/{len(mao)} slots corretos")
        return 0 if acertos == len(mao) else 1
    except BridgeError as exc:
        print("ERRO:", exc)
        return 1
    finally:
        b.close()


if __name__ == "__main__":
    raise SystemExit(main())
