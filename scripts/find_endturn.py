"""EXODIA-4B :: descobre como encerrar o turno.

Faz uma invocacao completa, grava o estado, e entao testa cada botao a partir
DESSE mesmo ponto, recarregando o savestate antes de cada teste. Encerrar o
turno se detecta pelo efeito: o oponente joga, entao muda o campo dele, os LP
ou o tamanho da nossa mao (compra).

Uso:
    python scripts/find_endturn.py --load saibau
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

BOTOES = ["none", "cross", "circle", "square", "triangle", "start",
          "select", "up", "down", "left", "right", "l1", "r1", "l2", "r2"]


def resumo(g: st.GameState) -> tuple:
    return (g.lp_player, g.lp_opponent, len(g.hand), len(g.field),
            len(g.opponent_field), g.opponent_hand_size, g.menu_id, g.mode)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--load", default="saibau")
    ap.add_argument("--state", default="pos_summon")
    ap.add_argument("--frames", type=int, default=400)
    args = ap.parse_args()

    out = ROOT / "runs" / "endturn"
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.png"):
        old.unlink()
    sp = ROOT / "runs" / "states" / f"{args.state}.State"

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

        # --- 1. prepara um estado logo depois de uma invocacao completa
        b.loadstate(str(ROOT / "runs" / "states" / f"{args.load}.State"))
        b.frame_advance(4)
        act = Actuator(b, RAM)
        act.wait_for_idle()
        act.open_hand()
        act.wait_for_idle()
        gs = st.read(b, RAM)
        mao = gs.hand
        monstros = [r for r in mao
                    if (c := cards.get(r.card_id)) and c.is_monster]
        if not monstros:
            print("sem monstro na mao")
            return 1
        alvo = max(monstros, key=lambda r: r.attack)
        print(f"invocando {cards.name(alvo.card_id)} para preparar o estado...")
        if not act.summon(alvo.card_id, valid_ids={r.card_id for r in mao}):
            print("a invocacao falhou; abortando")
            return 1
        b.savestate(str(sp))
        time.sleep(0.5)
        base = resumo(st.read(b, RAM))
        print(f"estado '{args.state}' gravado\n")
        print("base:", base, "\n")

        # --- 2. testa cada botao isoladamente a partir dele
        print(f"{'botao':>8}  {'mudou':>6}  o que mudou")
        achados = []
        for btn in BOTOES:
            b.loadstate(str(sp))
            b.frame_advance(4)
            if btn != "none":
                b.press(btn, 4)
            b.frame_advance(args.frames)

            g = st.read(b, RAM)
            cur = resumo(g)
            campos = ["lp_voce", "lp_op", "mao", "campo", "campo_op",
                      "mao_op", "menu", "mode"]
            diff = {campos[i]: (base[i], cur[i])
                    for i in range(len(base)) if cur[i] != base[i]}
            marca = "SIM" if diff else "-"
            if diff:
                achados.append((btn, diff))
            print(f"{btn:>8}  {marca:>6}  {diff if diff else ''}")
            b.screenshot(str(out / f"{btn}.png"))
            time.sleep(0.15)

        print("\n--- candidatos a encerrar o turno ---")
        if not achados:
            print("  nenhum botao mudou o estado; o turno pode exigir "
                  "uma sequencia, nao um botao so")
        for btn, diff in achados:
            print(f"  {btn}: {diff}")
        return 0
    except BridgeError as exc:
        print("ERRO:", exc)
        return 1
    finally:
        b.close()


if __name__ == "__main__":
    raise SystemExit(main())
