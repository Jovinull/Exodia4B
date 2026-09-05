"""EXODIA-4B :: em que tela o jogo REPOUSA depois de cada acao?

O agente acerta a primeira acao do turno e erra as seguintes. A causa provavel
e sempre a mesma familia de problema deste projeto: cada acao deixa o jogo numa
tela, e a proxima assume outra.

Ate agora isso foi tratado por tentativa (`ensure_hand_view` alternando
cancelar e left). Este script troca o chute por um mapa: executa uma acao real,
para, e registra onde o jogo ficou - com screenshot e com a classificacao do id
sob o cursor.

Uso:
    python scripts/map_repouso.py --load meu_turno
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


def onde(gs: st.GameState, cur: int) -> str:
    """Classifica o id sob o cursor contra o que a RAM diz de cada lugar."""
    lug = []
    if any(r.card_id == cur for r in gs.hand):
        lug.append("MAO")
    if any(r.card_id == cur for r in gs.field):
        lug.append("NOSSO CAMPO")
    if any(r.card_id == cur for r in gs.opponent_field):
        lug.append("CAMPO OPONENTE")
    return "/".join(lug) or "nada reconhecido"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--load", default="meu_turno")
    args = ap.parse_args()

    out = ROOT / "runs" / "repouso"
    out.mkdir(parents=True, exist_ok=True)
    for f in out.glob("*.png"):
        f.unlink()

    b = Bridge(HOST, PORT)
    b.listen()
    subprocess.Popen(
        [str(EMUHAWK), f"--socket_ip={HOST}", f"--socket_port={PORT}",
         f"--lua={LUA}", str(ISO)],
        cwd=str(EMUHAWK.parent),
    )
    n = 0
    try:
        b.start_after_listen(timeout=180)
        RAM = b.main_ram()
        b.speed(900)
        b.loadstate(str(ROOT / "runs" / "states" / f"{args.load}.State"))
        b.frame_advance(60)
        act = Actuator(b, RAM)
        act.wait_for_idle()

        def marco(rotulo: str) -> None:
            nonlocal n
            act.wait_for_idle(stable_for=40)
            gs = st.read(b, RAM)
            cur = act.cursor_card()
            c = cards.get(cur)
            print(f"\n[{n}] {rotulo}")
            print(f"     cursor -> {c.name if c else cur}   "
                  f"[{onde(gs, cur)}]")
            print(f"     mao {len(gs.hand)}  campo {len(gs.field)}  "
                  f"campo_op {len(gs.opponent_field)}  "
                  f"LP {gs.lp_player}x{gs.lp_opponent}")
            print(f"     cursor_on_hand={int(act.cursor_on_hand())}  "
                  f"cursor_on_our_field={int(act.cursor_on_our_field())}")
            limpo = "".join(ch if ch.isalnum() else "-" for ch in rotulo[:26])
            b.screenshot(str(out / f"{n:02d}_{limpo}.png"))
            n += 1

        def monstro_na_mao(gs: st.GameState) -> int | None:
            return next((i for i, r in enumerate(gs.hand)
                         if (c := cards.get(r.card_id)) and c.is_monster), None)

        marco("inicio do turno")

        # --- 1. invocar e ver onde para ---------------------------------
        gs = st.read(b, RAM)
        i = monstro_na_mao(gs)
        print(f"\n>>> summon(slot={i}) ...")
        ok = act.summon(i, gs.hand[i].card_id)
        print(f"    -> {ok}")
        marco("REPOUSO apos invocar")

        # --- 2. o harness consegue voltar para a mao? --------------------
        print("\n>>> ensure_hand_view() ...")
        volta = act.ensure_hand_view()
        print(f"    -> {volta}")
        marco("apos ensure_hand_view")

        # --- 3. segunda invocacao no mesmo turno -------------------------
        gs = st.read(b, RAM)
        i = monstro_na_mao(gs)
        if i is not None:
            print(f"\n>>> segunda summon(slot={i}) ...")
            ok2 = act.summon(i, gs.hand[i].card_id)
            print(f"    -> {ok2}")
            marco("REPOUSO apos 2a invocacao")

        # --- 4. atacar e ver onde para -----------------------------------
        gs = st.read(b, RAM)
        if gs.field and gs.opponent_field:
            print("\n>>> attack(0, 0) ...")
            oka = act.attack(0, 0, gs.field[0].card_id)
            print(f"    -> {oka}")
            marco("REPOUSO apos atacar")

            print("\n>>> ensure_hand_view() depois do ataque ...")
            v2 = act.ensure_hand_view()
            print(f"    -> {v2}")
            marco("apos ensure_hand_view (pos-ataque)")
        else:
            print("\n(sem alvo para atacar nesta amostra)")

        # --- 5. fim de turno ---------------------------------------------
        print("\n>>> end_turn() ...")
        okt = act.end_turn()
        print(f"    -> {okt}")
        marco("REPOUSO apos fim de turno")

        print(f"\nscreenshots em {out}")
        return 0
    except BridgeError as exc:
        print("ERRO:", exc)
        return 1
    finally:
        b.close()


if __name__ == "__main__":
    raise SystemExit(main())
