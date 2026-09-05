"""EXODIA-4B :: descobre como colocar a carta virada para a frente.

Uma carta colocada de costas (defesa) nao ataca. O sinal disso na RAM e o bit
0x4000 do registro: monstro que pode agir tem 0xC000, o que ficou de costas
fica em 0x8000.

O script invoca a MESMA carta a partir do MESMO savestate, variando o botao
apertado depois de selecionar a carta, e mostra com que flags ela terminou.

Uso:
    python scripts/test_position.py --load saibau
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

VARIANTES = ["nenhum", "up", "down", "left", "right", "square", "triangle"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--load", default="saibau")
    args = ap.parse_args()

    out = ROOT / "runs" / "posicao"
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
        print(f"{'botao apos selecionar':>22}  {'entrou?':>8}  "
              f"{'flags':>7}  {'pode agir?':>10}")
        print("-" * 56)

        for v in VARIANTES:
            b.loadstate(estado)
            b.frame_advance(4)
            act = Actuator(b, RAM)
            act.wait_for_idle()
            act.open_hand()
            act.wait_for_idle()

            gs = st.read(b, RAM)
            monstros = [r for r in gs.hand
                        if (c := cards.get(r.card_id)) and c.is_monster]
            if not monstros:
                print("  sem monstro na mao")
                break
            alvo = monstros[0]
            validos = {r.card_id for r in gs.hand}
            campo_antes = sum(1 for r in gs.field if r.card_id == alvo.card_id)

            if not act.move_cursor_to_card(alvo.card_id, valid_ids=validos):
                print(f"{v:>22}  cursor nao chegou no alvo")
                continue

            act.confirm()                       # seleciona a carta
            act.wait_for_idle(stable_for=20)
            if v != "nenhum":                   # a variacao entra aqui
                b.press(v, 3)
                b.frame_advance(20)

            for _ in range(5):                  # confirma o resto dos prompts
                s = st.read(b, RAM)
                if sum(1 for r in s.field if r.card_id == alvo.card_id) > campo_antes:
                    break
                act.confirm()
                act.wait_for_idle(stable_for=20)

            s = st.read(b, RAM)
            posta = [r for r in s.field if r.card_id == alvo.card_id]
            if posta:
                r = posta[-1]
                print(f"{v:>22}  {'sim':>8}  0x{r.flags:04X}  "
                      f"{('SIM' if r.can_act else 'nao'):>10}")
            else:
                print(f"{v:>22}  {'nao':>8}  {'-':>7}  {'-':>10}")
            b.screenshot(str(out / f"{v}.png"))
            time.sleep(0.2)

        print(f"\nscreenshots em {out}")
        print("\nquem terminar com 'pode agir = SIM' e a posicao de ataque")
        return 0
    except BridgeError as exc:
        print("ERRO:", exc)
        return 1
    finally:
        b.close()


if __name__ == "__main__":
    raise SystemExit(main())
