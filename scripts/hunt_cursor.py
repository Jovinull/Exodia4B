"""EXODIA-4B :: caca ao endereco da POSICAO do cursor.

Hoje o harness mira o cursor por ID de carta. Isso e ambiguo: a mesma carta
pode estar na mao e no campo, e o deck tem copias repetidas. Foi o que fez o
agente selecionar a carta errada e travar. Para a fusao, que depende de
escolher cartas especificas, endereçar por ID nao serve de jeito nenhum.

Enquanto uma PESSOA move o cursor um slot por vez, este script fotografa uma
regiao da RAM a cada movimento e procura enderecos que andem junto com o
cursor.

As fotos vao para disco na hora. A conexao com o emulador ja caiu no meio de
uma coleta e levou junto uma sessao inteira de dados recem produzidos; com os
arquivos salvos, a analise pode ser refeita sem repetir o trabalho.

Uso:
    python scripts/hunt_cursor.py --load meu_turno --seconds 150
    python scripts/hunt_cursor.py --offline      # so reanalisa o que ja existe
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

OUT = ROOT / "runs" / "cursor_hunt"
SNAPS = OUT / "snapshots"


def ler(b: Bridge, ram: str) -> bytes:
    buf = bytearray()
    for off in range(0, TAM, CHUNK):
        buf += b.read_bytes(BASE + off, min(CHUNK, TAM - off), ram)
    return bytes(buf)


def analisar(log) -> None:
    """Le as fotos gravadas e aponta candidatos a indice de cursor.

    Um bom candidato muda em quase todo movimento e assume poucos valores
    pequenos - a cara de um indice de slot, e nao de um id de carta nem de um
    contador que so cresce.
    """
    arquivos = sorted(SNAPS.glob("*.bin"))
    if len(arquivos) < 2:
        log("dados insuficientes: menos de 2 fotos gravadas")
        return

    fotos = [(p.stem, p.read_bytes()) for p in arquivos]
    log(f"\nanalisando {len(fotos)} fotos de {TAM} bytes")

    historico: dict[int, list[int]] = defaultdict(list)
    for (_, a), (_, c) in zip(fotos, fotos[1:]):
        for i in range(min(len(a), len(c))):
            if a[i] != c[i]:
                historico[BASE + i].append(c[i])

    movimentos = len(fotos) - 1
    candidatos = []
    for end, vals in historico.items():
        distintos = sorted(set(vals))
        if (len(vals) >= max(2, movimentos // 3)
                and 2 <= len(distintos) <= 12
                and max(distintos) <= 20):
            candidatos.append((len(vals), end, distintos))

    log(f"\n{'endereco':>14} {'mudou':>6} {'distintos':>10}  valores")
    for n, end, distintos in sorted(candidatos, reverse=True)[:25]:
        log(f"  0x{0x80000000 | end:08X} {n:6} {len(distintos):10}  {distintos}")
    if not candidatos:
        log("  nenhum candidato com cara de indice de slot")

    log(f"\nvalor de cada candidato em cada foto (para ver se ANDA junto):")
    for _, end, _ in sorted(candidatos, reverse=True)[:8]:
        serie = [f[end - BASE] for _, f in fotos]
        log(f"  0x{0x80000000 | end:08X}: {serie}")
    log(f"\nmovimentos analisados: {movimentos}")


def coletar(args, log) -> None:
    SNAPS.mkdir(parents=True, exist_ok=True)
    for velho in SNAPS.glob("*.bin"):
        velho.unlink()

    b = Bridge(HOST, PORT)
    b.listen()
    subprocess.Popen(
        [str(EMUHAWK), f"--socket_ip={HOST}", f"--socket_port={PORT}",
         f"--lua={LUA}", str(ISO)],
        cwd=str(EMUHAWK.parent),
    )
    movimentos = 0
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
        log("   2) na visao de campo, mova com as setas um passo por vez")
        log(" nao precisa jogar; se precisar apertar Z para navegar, tudo bem")
        log("=" * 64)

        anterior = ler(b, RAM)
        SNAPS.joinpath("000_inicio.bin").write_bytes(anterior)
        fim = time.time() + args.seconds

        while time.time() < fim:
            registro = b.command(f"FREERUN {args.chunk}")
            apertos = [mapa.get(item.split("=")[1].split("+")[0], "?")
                       for item in registro.split(",") if "=" in item]
            if not apertos:
                continue

            atual = ler(b, RAM)
            movimentos += 1
            nome = "+".join(apertos)[:20]
            SNAPS.joinpath(f"{movimentos:03d}_{nome}.bin").write_bytes(atual)
            mudou = sum(1 for i in range(TAM) if atual[i] != anterior[i])
            log(f"  movimento {movimentos:3}  botoes={apertos}  "
                f"{mudou} bytes mudaram  (foto salva)")
            anterior = atual
    except KeyboardInterrupt:
        log("\ninterrompido pelo usuario")
    except (BridgeError, OSError) as exc:
        log(f"\nconexao com o emulador caiu: {exc}")
        log("as fotos ja gravadas foram preservadas")
    finally:
        b.close()
    log(f"\n{movimentos} movimentos capturados")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--load", default="meu_turno")
    ap.add_argument("--seconds", type=int, default=150)
    ap.add_argument("--chunk", type=int, default=30, help="frames por rodada")
    ap.add_argument("--offline", action="store_true",
                    help="nao coleta, so reanalisa as fotos ja gravadas")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    diario = OUT / "log.txt"
    linhas: list[str] = []

    def log(s: str = "") -> None:
        print(s, flush=True)
        linhas.append(str(s))
        try:
            diario.write_text("\n".join(linhas), encoding="utf-8")
        except OSError:
            pass

    if not args.offline:
        coletar(args, log)
    analisar(log)
    log(f"\nlog: {diario}")
    log(f"fotos: {SNAPS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
