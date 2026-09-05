"""EXODIA-4B :: observa uma pessoa jogando e correlaciona com a RAM.

Abre o jogo num savestate, deixa rodar em velocidade normal, e registra:
  - quais botoes a pessoa apertou, com o frame de cada aperto
  - o que mudou no estado do duelo depois deles

Serve para descobrir por observacao o que a sondagem automatica nao achou -
por exemplo qual acao realmente encerra o turno.

Teclas (padrao do BizHawk, ja configuradas):
    setas = D-Pad | Z = X | X = O | S = triangulo | A = quadrado
    Enter = Start | Espaco = Select | Q W E R = L1 R1 L2 R2

Uso:
    python scripts/watch_human.py --load saibau --seconds 180
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from exodia import cards, state as st  # noqa: E402
from exodia.bridge import Bridge, BridgeError  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
EMUHAWK = ROOT / "tools" / "BizHawk" / "EmuHawk.exe"
LUA = ROOT / "exodia" / "bridge.lua"
ISO = (ROOT / "[PS1]_Yu-Gi-Oh! Forbidden Memories (PT-BR)"
       / "Yu-Gi-Oh! Forbidden Memories (PT-BR).cue")
HOST, PORT = "127.0.0.1", 55355


def resumo(g: st.GameState) -> dict:
    return {
        "lp_voce": g.lp_player, "lp_op": g.lp_opponent,
        "mao": len(g.hand), "campo": len(g.field),
        "campo_op": len(g.opponent_field), "mao_op": g.opponent_hand_size,
        "menu": g.menu_id, "mode": g.mode, "oponente": g.opponent_id,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--load", default="saibau")
    ap.add_argument("--seconds", type=int, default=180)
    ap.add_argument("--chunk", type=int, default=45,
                    help="frames por rodada de observacao")
    args = ap.parse_args()

    out = ROOT / "runs" / "humano"
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.png"):
        old.unlink()
    diario = out / "log.txt"

    b = Bridge(HOST, PORT)
    b.listen()
    subprocess.Popen(
        [str(EMUHAWK), f"--socket_ip={HOST}", f"--socket_port={PORT}",
         f"--lua={LUA}", str(ISO)],
        cwd=str(EMUHAWK.parent),
    )
    linhas: list[str] = []

    def diga(s: str) -> None:
        print(s, flush=True)
        linhas.append(s)

    try:
        b.start_after_listen(timeout=180)
        RAM = b.main_ram()
        b.speed(100)
        b.loadstate(str(ROOT / "runs" / "states" / f"{args.load}.State"))
        b.frame_advance(4)
        mapa = {v: k for k, v in b.buttons().items()}   # hex -> alias

        diga("=" * 66)
        diga(" JOGUE NORMALMENTE NA JANELA DO EMUHAWK")
        diga(" setas=D-Pad  Z=X  X=O  S=triangulo  A=quadrado")
        diga(" Enter=Start  Espaco=Select  Q W E R = L1 R1 L2 R2")
        diga(f" observando por {args.seconds}s; cada mudanca aparece aqui")
        diga("=" * 66)

        anterior = resumo(st.read(b, RAM))
        diga(f"estado inicial: {anterior}")
        fim = time.time() + args.seconds
        n_shot = 0
        while time.time() < fim:
            log = b.command(f"FREERUN {args.chunk}")
            apertos = []
            for item in log.split(","):
                if "=" in item:
                    frame, _, hexes = item.partition("=")
                    nomes = [mapa.get(h, h) for h in hexes.split("+")]
                    apertos.append(f"{frame}:{'+'.join(nomes)}")

            atual = resumo(st.read(b, RAM))
            mudou = {k: (anterior[k], v) for k, v in atual.items()
                     if v != anterior[k]}
            if apertos or mudou:
                if apertos:
                    diga(f"  botoes  {' '.join(apertos)}")
                if mudou:
                    diga(f"  >>> MUDOU {mudou}")
                    g = st.read(b, RAM)
                    diga("      " + g.render().replace("\n", "\n      "))
                    n_shot += 1
                    b.screenshot(str(out / f"m{n_shot:03d}.png"))
                anterior = atual

        diga("\nfim da observacao")
        diario.write_text("\n".join(linhas), encoding="utf-8")
        print(f"\nlog salvo em {diario}")
        return 0
    except BridgeError as exc:
        print("ERRO:", exc)
        diario.write_text("\n".join(linhas), encoding="utf-8")
        return 1
    finally:
        b.close()


if __name__ == "__main__":
    raise SystemExit(main())
