"""EXODIA-4B :: a visao aberta estraga a leitura de estado?

O harness gasta botoes fechando menu antes de CADA acao. A justificativa era:
"com a mao aberta o bit de ja-atacou aparece zerado". Essa conclusao foi tirada
quando a deteccao de menu se apoiava em 0x8009B0AC - que agora sabemos ser um
bit de paridade de frame, e nao uma flag de sobreposicao. Ou seja: a premissa
foi medida com um instrumento quebrado e precisa ser refeita.

Importa muito. Se a leitura NAO depende da tela, some a razao de existir do
`close_overlay()` no caminho de leitura - e com ela some o START solto que
encerrava o nosso turno sem querer.

Compara os mesmos registros lidos em cada tela, alternando com START, e tira
screenshot de cada uma para a tela servir de prova.

Uso:
    python scripts/check_view_read.py --load meu_turno
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


def foto(gs: st.GameState) -> str:
    """Assinatura textual do estado, para comparar leitura com leitura."""
    linhas = [f"LP {gs.lp_player}x{gs.lp_opponent}"]
    for r in gs.records:
        c = cards.get(r.card_id)
        linhas.append(f"  #{r.index:2} {(c.name if c else r.card_id)!s:24} "
                      f"flags=0x{r.flags:04X} campo={int(r.on_field)} "
                      f"atacou={int(r.has_attacked)} baixo={int(r.face_down)}")
    return "\n".join(linhas)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--load", default="meu_turno")
    ap.add_argument("--passos", type=int, default=4)
    args = ap.parse_args()

    out = ROOT / "runs" / "visao"
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
        b.frame_advance(60)
        act = Actuator(b, RAM)
        act.wait_for_idle()

        fotos: list[str] = []
        for i in range(args.passos):
            if i:
                b.press("start", 4)
                act.wait_for_idle(stable_for=40)
            gs = st.read(b, RAM)
            f = foto(gs)
            fotos.append(f)
            b.screenshot(str(out / f"{i}.png"))
            print(f"\n===== leitura {i} "
                  f"{'(apos START)' if i else '(inicial)'} =====")
            print(f)

        print("\n===== VEREDITO =====")
        distintas = {f for f in fotos}
        if len(distintas) == 1:
            print("as leituras sao IDENTICAS em todas as telas.")
            print("-> a leitura de estado NAO depende da visao aberta;")
            print("   fechar menu antes de ler e desnecessario.")
        else:
            print(f"{len(distintas)} leituras diferentes em {args.passos} "
                  f"telas - a visao AFETA a leitura. Detalhe acima.")
        print(f"\nscreenshots em {out}")
        return 0
    except BridgeError as exc:
        print("ERRO:", exc)
        return 1
    finally:
        b.close()


if __name__ == "__main__":
    raise SystemExit(main())
