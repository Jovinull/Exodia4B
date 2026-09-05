"""EXODIA-4B :: compara os dois lados da seta ao posicionar a carta.

Hipotese: uma seta poe o monstro em ATAQUE e a outra em DEFESA, ambas de
frente. Defesa de frente nao ataca, o que explicaria monstros nossos que nunca
ganham o bit 0x4000.

Invoca a mesma carta do mesmo savestate com cada seta e mostra as flags
resultantes, lidas na visao de campo.

Uso:
    python scripts/test_flip.py --load meu_turno
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
    ap.add_argument("--load", default="meu_turno")
    args = ap.parse_args()

    out = ROOT / "runs" / "flip"
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.png"):
        old.unlink()
    estado = str(ROOT / "runs" / "states" / f"{args.load}.State")

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
        print(f"{'seta':>10} {'invocou':>8} {'flags':>7} {'de costas':>10} "
              f"{'pode agir':>10}")
        print("-" * 50)

        for seta in ("right", "left", "nenhuma"):
            b.loadstate(estado)
            b.frame_advance(4)
            act = Actuator(b, RAM)
            act.wait_for_idle()

            g = st.read(b, RAM)
            monstros = [r for r in g.hand
                        if (c := cards.get(r.card_id)) and c.is_monster]
            if not monstros:
                print("sem monstro na mao")
                break
            alvo = monstros[0]

            ok = act.summon(
                alvo.card_id,
                valid_ids={r.card_id for r in g.hand},
                face_up=(seta != "nenhuma"),
                flip_button=("right" if seta == "nenhuma" else seta),
            )
            # le SEMPRE na visao de campo
            act.close_overlay()
            act.wait_for_idle(stable_for=30)
            s = st.read(b, RAM)
            posto = [r for r in s.field if r.card_id == alvo.card_id]
            if posto:
                r = posto[-1]
                print(f"{seta:>10} {'sim':>8} 0x{r.flags:04X} "
                      f"{('SIM' if r.face_down else 'nao'):>10} "
                      f"{('SIM' if r.has_attacked else 'nao'):>10}")
            else:
                print(f"{seta:>10} {'nao':>8} {'-':>7} {'-':>10} {'-':>10}")
            b.screenshot(str(out / f"{seta}.png"))
            time.sleep(0.25)

        print(f"\nscreenshots em {out}")
        print("a seta que der 'pode agir = SIM' e a posicao de ataque")
        return 0
    except BridgeError as exc:
        print("ERRO:", exc)
        return 1
    finally:
        b.close()


if __name__ == "__main__":
    raise SystemExit(main())
