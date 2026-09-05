"""EXODIA-4B :: caca ao endereco da POSICAO do cursor.

Hoje o harness mira o cursor por ID de carta. Isso e ambiguo: a mesma carta
pode estar na mao e no campo, e o deck tem copias repetidas. Foi o que fez o
agente selecionar a carta errada e travar. Para a fusao, que depende de
escolher cartas especificas, endereçar por ID nao serve de jeito nenhum.

O que este script faz: enquanto uma PESSOA move o cursor um slot por vez, ele
tira uma foto de uma regiao da RAM a cada movimento e procura enderecos que
andem junto com o cursor - isto e, que mudem a cada passo e voltem ao andar
para tras.

Tambem separa os movimentos feitos na MAO dos feitos no CAMPO, o que de quebra
deve revelar um sinal confiavel de "que tela e esta" - o flag que eu uso hoje
falha em jogo ao vivo.

Uso:
    python scripts/hunt_cursor.py --load meu_turno --seconds 150
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from exodia.bridge import Bridge, BridgeError  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
EMUHAWK = ROOT / "tools" / "BizHawk" / "EmuHawk.exe"
LUA = ROOT / "exodia" / "bridge.lua"
ISO = (ROOT / "[PS1]_Yu-Gi-Oh! Forbidden Memories (PT-BR)"
       / "Yu-Gi-Oh! Forbidden Memories (PT-BR).cue")
HOST, PORT = "127.0.0.1", 55355

# Faixa onde o estado de interface do duelo ja se mostrou vivo.
BASE, TAM = 0x09B000, 0x1000
CHUNK = 512


def ler(b: Bridge, ram: str) -> bytes:
    buf = bytearray()
    for off in range(0, TAM, CHUNK):
        buf += b.read_bytes(BASE + off, min(CHUNK, TAM - off), ram)
    return bytes(buf)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--load", default="meu_turno")
    ap.add_argument("--seconds", type=int, default=150)
    ap.add_argument("--chunk", type=int, default=30, help="frames por rodada")
    args = ap.parse_args()

    out = ROOT / "runs" / "cursor_hunt"
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
        b.speed(100)
        b.loadstate(str(ROOT / "runs" / "states" / f"{args.load}.State"))
        b.frame_advance(4)
        mapa = {v: k for k, v in b.buttons().items()}

        log("=" * 64)
        log(" MOVA O CURSOR DEVAGAR, UM SLOT POR VEZ")
        log("   1) Enter abre a mao; mova com as setas, um passo por vez")
        log("   2) Enter fecha a mao")
        log("   3) na visao de campo, mova com as setas um passo por vez")
        log(" nao precisa jogar nada, so mover")
        log("=" * 64)

        anterior = ler(b, RAM)
        # endereco -> lista de valores observados apos cada movimento
        historico: dict[int, list[int]] = defaultdict(list)
        movimentos = 0
        fim = time.time() + args.seconds

        while time.time() < fim:
            registro = b.command(f"FREERUN {args.chunk}")
            apertos = [mapa.get(item.split("=")[1].split("+")[0], "?")
                       for item in registro.split(",") if "=" in item]
            if not apertos:
                continue

            atual = ler(b, RAM)
            mudou = [i for i in range(TAM) if atual[i] != anterior[i]]
            movimentos += 1
            for i in mudou:
                historico[BASE + i].append(atual[i])
            log(f"  movimento {movimentos:3}  botoes={apertos}  "
                f"{len(mudou)} bytes mudaram")
            anterior = atual

        # Um bom candidato a posicao de cursor muda MUITO (quase todo
        # movimento) e assume poucos valores distintos e pequenos - um indice
        # de slot, nao um id de carta nem um contador.
        log(f"\n{'endereco':>12} {'mudou':>6} {'distintos':>10}  valores")
        candidatos = []
        for end, vals in historico.items():
            distintos = sorted(set(vals))
            if len(vals) >= max(3, movimentos // 3) and 2 <= len(distintos) <= 12 \
                    and max(distintos) <= 20:
                candidatos.append((len(vals), end, distintos))
        for n, end, distintos in sorted(candidatos, reverse=True)[:25]:
            log(f"  0x{0x80000000 | end:08X} {n:6} {len(distintos):10}  "
                f"{distintos}")
        if not candidatos:
            log("  nenhum candidato com cara de indice de slot")
        log(f"\nmovimentos observados: {movimentos}")
        log(f"log: {diario}")
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
