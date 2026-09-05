"""EXODIA-4B :: roda o agente em velocidade normal, para uma pessoa assistir.

Igual ao run_random, mas devagar e narrando cada passo antes de executar, para
dar tempo de acompanhar na tela do EmuHawk o que o agente esta tentando fazer.

Serve para diagnosticar pela tela o que a RAM nao conta: se a carta entra
virada, se um menu fica aberto, se o cursor para no lugar errado.

Uso:
    python scripts/watch_agent.py --load meu_turno --turns 4
    python scripts/watch_agent.py --load meu_turno --turns 4 --speed 200
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
from exodia.rules import legal_actions  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
EMUHAWK = ROOT / "tools" / "BizHawk" / "EmuHawk.exe"
LUA = ROOT / "exodia" / "bridge.lua"
ISO = (ROOT / "[PS1]_Yu-Gi-Oh! Forbidden Memories (PT-BR)"
       / "Yu-Gi-Oh! Forbidden Memories (PT-BR).cue")
HOST, PORT = "127.0.0.1", 55355


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--load", default="meu_turno")
    ap.add_argument("--turns", type=int, default=4)
    ap.add_argument("--speed", type=int, default=100,
                    help="100 = velocidade normal, da para assistir")
    ap.add_argument("--pausa", type=float, default=1.5,
                    help="segundos de pausa antes de cada acao")
    args = ap.parse_args()

    out = ROOT / "runs" / "assistido"
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
        act = Actuator(b, RAM)
        act.wait_for_idle()

        log("=" * 62)
        log(" ASSISTA A JANELA DO EMUHAWK")
        log(f" velocidade {args.speed}%  |  pausa de {args.pausa}s antes de agir")
        log(" repare especialmente: a carta entra de FRENTE ou de COSTAS?")
        log("=" * 62)

        for t in range(args.turns):
            g = st.read(b, RAM)
            log(f"\n=== turno {t} === LP {g.lp_player} x {g.lp_opponent}")
            log(g.render())

            campo = g.field
            if campo:
                log("  detalhe do nosso campo:")
                for r in campo:
                    log(f"    {cards.name(r.card_id)[:26]:26} "
                        f"flags=0x{r.flags:04X}  "
                        f"{'DE COSTAS' if r.face_down else 'de frente'}  "
                        f"{'ja atacou' if r.has_attacked else 'pode atacar'}")

            acoes = legal_actions(g)
            log(f"  {len(acoes)} acoes legais")

            # prioriza ATACAR quando houver, senao invoca. Antes o script fazia
            # uma acao e passava o turno, entao nunca chegava a atacar.
            escolha = next((a for a in acoes if a.kind.startswith("attack")),
                           None) or next(
                (a for a in acoes if a.kind == "summon"), acoes[0])
            log(f"\n  >> vou executar: {escolha.label}")
            time.sleep(args.pausa)

            if escolha.kind == "summon":
                ok = act.summon(escolha.hand_slot, escolha.card_id,
                                guardian_star=escolha.guardian_star)
            elif escolha.kind in ("attack", "attack_direct"):
                ok = act.attack(escolha.field_slot, escolha.target_slot,
                                escolha.card_id)
            else:
                ok = act.end_turn()
            log(f"  resultado: {'ok' if ok else 'FALHOU'}")

            depois = st.read(b, RAM)
            for r in depois.field:
                log(f"    campo agora: {cards.name(r.card_id)[:24]:24} "
                    f"0x{r.flags:04X} "
                    f"{'DE COSTAS' if r.face_down else 'de frente'}")
            b.screenshot(str(out / f"t{t:02d}.png"))
            time.sleep(args.pausa)

            log("  >> passando o turno")
            act.end_turn()

        log("\nfim. log em " + str(diario))
        return 0
    except KeyboardInterrupt:
        log("\ninterrompido")
        return 0
    except BridgeError as exc:
        log(f"ERRO: {exc}")
        return 1
    finally:
        b.close()


if __name__ == "__main__":
    raise SystemExit(main())
