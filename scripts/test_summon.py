"""EXODIA-4B :: testa a invocacao pelo atuador.

Verifica duas coisas de uma vez:
  1. a primeira invocacao do turno chega mesmo ao campo;
  2. a segunda e RECUSADA pelo jogo.

O item 2 nao e falha do atuador: em Forbidden Memories so se joga uma carta
por turno. O teste passa quando o comportamento bate com a regra.

Uso:
    python scripts/test_summon.py --load saibau
    python scripts/test_summon.py --load saibau --star b
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
    ap.add_argument("--star", default="a", choices=["a", "b"])
    ap.add_argument("--count", type=int, default=3)
    args = ap.parse_args()

    out = ROOT / "runs" / "summon_test"
    out.mkdir(parents=True, exist_ok=True)

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
        act.ensure_hand_view()
        act.wait_for_idle()

        resultados: list[bool] = []
        for n in range(args.count):
            gs = st.read(b, RAM)
            mao = gs.hand
            monstros = [r for r in mao
                        if (c := cards.get(r.card_id)) and c.is_monster]
            if not monstros:
                print("acabaram os monstros na mao")
                break
            alvo = max(monstros, key=lambda r: r.attack)
            c = cards.get(alvo.card_id)
            estrelas = (f"A={cards.guardian_star_label(c.guardian_a)} "
                        f"B={cards.guardian_star_label(c.guardian_b)}")
            print(f"\n[{n}] invocando {c.short()}  ({estrelas})")
            print(f"    campo antes: {len(gs.field)}")

            venceu = act.summon(mao.index(alvo), alvo.card_id,
                                guardian_star=args.star)
            depois = st.read(b, RAM)
            print(f"    campo depois: {len(depois.field)}  -> "
                  f"{'OK' if venceu else 'FALHOU'}")
            for r in depois.field:
                cc = cards.get(r.card_id)
                print(f"      em campo: {cc.short() if cc else r.card_id} "
                      f"flags=0x{r.flags:04X} slot={r.slot}")
            resultados.append(venceu)
            b.screenshot(str(out / f"summon_{n}.png"))
            time.sleep(0.3)

        esperado = [i == 0 for i in range(len(resultados))]
        passou = resultados == esperado
        print(f"\ninvocacoes: {resultados}")
        print(f"esperado  : {esperado}   "
              f"(so a primeira do turno pode passar)")
        print("VEREDITO  :", "OK" if passou else "COMPORTAMENTO INESPERADO")
        print()
        print(st.read(b, RAM).render())
        return 0 if passou else 1
    except BridgeError as exc:
        print("ERRO:", exc)
        return 1
    finally:
        b.close()


if __name__ == "__main__":
    raise SystemExit(main())
