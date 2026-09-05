"""EXODIA-4B :: joga turnos completos.

Repete o ciclo invocar -> encerrar turno a partir de um estado limpo de duelo,
mostrando o estado a cada volta. E o ensaio do agente aleatorio: se isto roda
varias voltas sem travar, o ciclo de turno esta fechado.

Uso:
    python scripts/test_turn.py --load saibau --turns 4
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
    ap.add_argument("--turns", type=int, default=4)
    args = ap.parse_args()

    out = ROOT / "runs" / "turnos_teste"
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
        b.frame_advance(4)

        act = Actuator(b, RAM)
        act.wait_for_idle()

        invocou = passou = 0
        for t in range(args.turns):
            g = st.read(b, RAM)
            print(f"\n=== turno {t} ===")
            print(f"LP {g.lp_player} x {g.lp_opponent} | "
                  f"mao {len(g.hand)} | campo {len(g.field)} | "
                  f"campo_op {len(g.opponent_field)} | "
                  f"cursor_na_mao {int(act.cursor_on_hand())}")

            act.ensure_hand_view()
            act.wait_for_idle()
            g = st.read(b, RAM)
            monstros = [r for r in g.hand
                        if (c := cards.get(r.card_id)) and c.is_monster]
            if monstros:
                alvo = max(monstros, key=lambda r: r.attack)
                nome = cards.name(alvo.card_id)
                ok = act.summon(g.hand.index(alvo), alvo.card_id)
                print(f"  invocar {nome}: {'OK' if ok else 'falhou'}")
                invocou += ok
            else:
                print("  sem monstro na mao")

            mudou = act.end_turn()
            print(f"  encerrar turno: {'o oponente jogou' if mudou else 'nada mudou'}")
            passou += mudou

            b.screenshot(str(out / f"t{t:02d}.png"))
            time.sleep(0.2)

        print(f"\ninvocacoes bem sucedidas: {invocou}/{args.turns}")
        print(f"turnos que passaram      : {passou}/{args.turns}")
        print()
        print(st.read(b, RAM).render())
        return 0 if passou >= args.turns - 1 else 1
    except BridgeError as exc:
        print("ERRO:", exc)
        return 1
    finally:
        b.close()


if __name__ == "__main__":
    raise SystemExit(main())
