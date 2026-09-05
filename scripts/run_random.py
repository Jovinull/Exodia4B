"""EXODIA-4B :: roda o agente aleatorio num duelo.

Criterio de saida da etapa do atuador: completar um duelo do inicio ao fim sem
travar, ganhando ou perdendo.

Uso:
    python scripts/run_random.py --load saibau --turns 20
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from exodia import state as st  # noqa: E402
from exodia.agent_random import RandomAgent  # noqa: E402
from exodia.bridge import Bridge, BridgeError  # noqa: E402
from exodia.rules import legal_actions, render_actions  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
EMUHAWK = ROOT / "tools" / "BizHawk" / "EmuHawk.exe"
LUA = ROOT / "exodia" / "bridge.lua"
ISO = (ROOT / "[PS1]_Yu-Gi-Oh! Forbidden Memories (PT-BR)"
       / "Yu-Gi-Oh! Forbidden Memories (PT-BR).cue")
HOST, PORT = "127.0.0.1", 55355


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--load", default="saibau")
    ap.add_argument("--turns", type=int, default=20)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--speed", type=int, default=900)
    args = ap.parse_args()

    out = ROOT / "runs" / "aleatorio"
    out.mkdir(parents=True, exist_ok=True)
    diario = out / "log.txt"
    linhas: list[str] = []

    def log(s: str = "") -> None:
        print(s, flush=True)
        linhas.append(str(s))
        try:
            diario.write_text("\n".join(linhas), encoding="utf-8")
        except OSError:
            pass

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
        b.speed(args.speed)
        b.loadstate(str(ROOT / "runs" / "states" / f"{args.load}.State"))
        b.frame_advance(4)

        gs = st.read(b, RAM)
        log("estado inicial:")
        log(gs.render())
        log("\nacoes legais no inicio:")
        log(render_actions(legal_actions(gs)))

        agente = RandomAgent(b, RAM, seed=args.seed)
        r = agente.jogar(max_turnos=args.turns, log=log)

        log("\n" + "=" * 56)
        log(r.resumo())
        log("=" * 56)
        log(st.read(b, RAM).render())
        b.screenshot(str(out / "final.png"))
        time.sleep(0.4)
        log(f"\nlog: {diario}")
        return 0
    except BridgeError as exc:
        log(f"ERRO: {exc}")
        return 1
    finally:
        b.close()


if __name__ == "__main__":
    raise SystemExit(main())
