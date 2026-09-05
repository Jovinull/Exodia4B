"""EXODIA-4B :: onde exatamente a invocacao quebra?

A primeira invocacao do duelo passa e as seguintes falham todas. O log do
agente so diz "sequencia de invocacao", que e o diagnostico generico - nao
aponta o passo.

Este script faz a mesma sequencia do `summon()`, mas parando em cada botao para
anotar o que mudou e tirar screenshot. A ideia e a de sempre neste projeto: a
RAM e a hipotese, a tela e a prova.

Uso:
    python scripts/trace_summon.py --load meu_turno --slot 0
    python scripts/trace_summon.py --load meu_turno --slot 0 --depois-de-invocar
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


class Tracador:
    def __init__(self, b: Bridge, ram: str, out: Path) -> None:
        self.b, self.ram, self.out = b, ram, out
        self.act = Actuator(b, ram)
        self.n = 0

    def marcar(self, rotulo: str) -> None:
        gs = st.read(self.b, self.ram)
        cur = self.act.cursor_card()
        c = cards.get(cur)
        mao = [cards.get(r.card_id) for r in gs.hand]
        campo = [cards.get(r.card_id) for r in gs.field]
        print(f"\n[{self.n}] {rotulo}")
        menu = self.b.read_u8(st.MENU_ID, self.ram)
        modo = self.b.read_u8(st.MODE_BYTE, self.ram)
        vis = self.b.read_u8(st.VIEW_FLAG, self.ram)
        print(f"     cursor -> {c.name if c else cur}   "
              f"na_mao={int(self.act.cursor_on_hand())}")
        print(f"     menu={menu} modo={modo} view={vis}")
        print(f"     mao ({len(mao)}): "
              f"{', '.join(x.name[:16] if x else '?' for x in mao)}")
        print(f"     campo ({len(campo)}): "
              f"{', '.join(x.name[:16] if x else '?' for x in campo) or '-'}")
        # Sem espacos no nome: o comando SCREENSHOT da ponte separa argumentos
        # por espaco, e o caminho vinha truncado no primeiro branco - varios
        # passos gravavam por cima do mesmo arquivo, sem extensao.
        limpo = "".join(ch if ch.isalnum() else "-" for ch in rotulo[:24])
        self.b.screenshot(str(self.out / f"{self.n:02d}_{limpo}.png"))
        self.n += 1

    def passo(self, botao: str, rotulo: str, frames: int = 3) -> None:
        self.b.press(botao, frames)
        self.act.wait_for_idle(stable_for=30)
        self.marcar(f"{rotulo} ({Bridge.rotulo(botao)})")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--load", default="meu_turno")
    ap.add_argument("--slot", type=int, default=0)
    ap.add_argument("--confirmes", type=int, default=6)
    ap.add_argument("--down-antes", type=int, default=0,
                    help="aperta baixo antes do enesimo confirme, para escolher "
                         "a segunda opcao do prompt de atributo")
    ap.add_argument("--depois-de-invocar", action="store_true",
                    help="invoca uma carta antes de tracar, para reproduzir o "
                         "caso em que so a PRIMEIRA invocacao funciona")
    args = ap.parse_args()

    out = ROOT / "runs" / "trace_summon"
    out.mkdir(parents=True, exist_ok=True)
    for velho in out.glob("*.png"):
        velho.unlink()

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
        b.frame_advance(60)

        t = Tracador(b, RAM, out)
        t.act.wait_for_idle()

        if args.depois_de_invocar:
            gs = st.read(b, RAM)
            alvo = next((i for i, r in enumerate(gs.hand)
                         if (c := cards.get(r.card_id)) and c.is_monster), None)
            if alvo is None:
                print("nao ha monstro na mao para a invocacao preparatoria")
                return 1
            print(f"invocacao preparatoria do slot {alvo}...")
            ok = t.act.summon(alvo, gs.hand[alvo].card_id)
            print(f"  -> {'ok' if ok else 'FALHOU'}")

        t.marcar("estado inicial")

        print("\n--- garantindo a visao da mao ---")
        na_mao = t.act.ensure_hand_view()
        t.marcar(f"ensure_hand_view -> {na_mao}")

        print("\n--- levando o cursor para a borda esquerda ---")
        t.act.home_cursor()
        t.marcar("home_cursor")

        for i in range(args.slot):
            t.passo("right", f"andando para o slot {i + 1}")

        gs = st.read(b, RAM)
        antes_campo = len(gs.field)
        antes_mao = len(gs.hand)

        t.passo("cross", "seleciona a carta")
        t.passo("right", "desvira a carta")

        # Daqui em diante o numero de prompts nao e fixo. Em vez de adivinhar,
        # confirma ate a carta aparecer no campo - e registra em QUAL aperto
        # ela apareceu, que e a informacao que faltava.
        for i in range(args.confirmes):
            if args.down_antes and i + 1 == args.down_antes:
                t.passo("down", f"desce no prompt antes do confirme #{i + 1}")
            t.passo("cross", f"confirma #{i + 1}")
            if len(st.read(b, RAM).field) > antes_campo:
                print(f"\n  >>> a carta entrou no campo no confirme #{i + 1}")
                break

        gs = st.read(b, RAM)
        print("\n===== VEREDITO =====")
        print(f"  mao   : {antes_mao} -> {len(gs.hand)}")
        print(f"  campo : {antes_campo} -> {len(gs.field)}")
        if len(gs.field) > antes_campo:
            print("  a carta ENTROU no campo")
        else:
            print("  a carta NAO entrou. Veja em que screenshot a tela parou "
                  "de responder ao botao.")
        print(f"\nscreenshots em {out}")
        return 0
    except BridgeError as exc:
        print("ERRO:", exc)
        return 1
    finally:
        b.close()


if __name__ == "__main__":
    raise SystemExit(main())
