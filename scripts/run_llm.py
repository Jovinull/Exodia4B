"""EXODIA-4B :: roda o agente LLM num duelo.

Criterio de saida da fase do agente: vencer um duelo inicial.

Uso:
    python scripts/run_llm.py --load meu_turno --turns 30
    python scripts/run_llm.py --model qwen3:4b --speed 400 --think
    python scripts/run_llm.py --capturar        # so grava fixtures do prompt

Cada corrida escreve em runs/llm/<carimbo>/:
    log.txt          o que apareceu no terminal, gravado LINHA A LINHA
    decisions.jsonl  telemetria de cada decisao
    notes.md         o caderno do agente (persiste entre corridas se --caderno)
    prompts.jsonl    os prompts exatos, para o benchmark offline
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from exodia import state as st  # noqa: E402
from exodia.agent_llm import LLMAgent  # noqa: E402
from exodia.bridge import Bridge, BridgeError  # noqa: E402
from exodia.llm import LLMClient  # noqa: E402
from exodia.memory import Caderno, Telemetria  # noqa: E402
from exodia.prompt import montar_duelo  # noqa: E402
from exodia.rules import legal_actions, render_actions  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
EMUHAWK = ROOT / "tools" / "BizHawk" / "EmuHawk.exe"
LUA = ROOT / "exodia" / "bridge.lua"
ISO = (ROOT / "[PS1]_Yu-Gi-Oh! Forbidden Memories (PT-BR)"
       / "Yu-Gi-Oh! Forbidden Memories (PT-BR).cue")
HOST, PORT = "127.0.0.1", 55355


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--load", default="meu_turno", help="savestate inicial")
    ap.add_argument("--turns", type=int, default=30)
    ap.add_argument("--speed", type=int, default=900)
    ap.add_argument("--model", default="qwen3:4b")
    ap.add_argument("--threads", type=int, default=0,
                    help="0 = deixa o Ollama decidir")
    ap.add_argument("--think", action="store_true",
                    help="liga o modo de raciocinio do modelo (bem mais lento)")
    ap.add_argument("--cache", action="store_true",
                    help="reaproveita decisao em estado repetido (modo farm)")
    ap.add_argument("--caderno", default="",
                    help="caminho de um notes.md para continuar de corridas "
                         "anteriores")
    ap.add_argument("--timeout", type=float, default=3600.0)
    ap.add_argument("--capturar", action="store_true",
                    help="grava os prompts para o benchmark offline")
    args = ap.parse_args()

    carimbo = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = ROOT / "runs" / "llm" / carimbo
    out.mkdir(parents=True, exist_ok=True)
    diario = out / "log.txt"

    # Grava a cada linha, e nao no fim. Um Ctrl+C ou uma queda de socket ja
    # levaram junto os dados de duas sessoes inteiras neste projeto.
    arquivo_log = diario.open("a", encoding="utf-8")

    def log(s: str = "") -> None:
        print(s, flush=True)
        arquivo_log.write(str(s) + "\n")
        arquivo_log.flush()

    llm = LLMClient(modelo=args.model, think=args.think,
                    num_thread=args.threads or None)
    if not llm.disponivel():
        log("ERRO: o Ollama nao respondeu em " + llm.host)
        return 1
    if args.model not in llm.modelos():
        log(f"ERRO: modelo '{args.model}' nao esta baixado. "
            f"Disponiveis: {llm.modelos()}")
        return 1

    log(f"modelo: {args.model}  (think={args.think})")
    log(f"aquecendo o modelo... {llm.aquecer():.1f}s")

    caderno = Caderno(Path(args.caderno) if args.caderno
                      else out / "notes.md").carregar()
    if caderno.notas:
        log(f"caderno carregado com {len(caderno.notas)} notas")

    fixtures = (out / "prompts.jsonl").open("a", encoding="utf-8") \
        if args.capturar else None

    b = Bridge(HOST, PORT)
    b.listen()
    subprocess.Popen(
        [str(EMUHAWK), f"--socket_ip={HOST}", f"--socket_port={PORT}",
         f"--lua={LUA}", str(ISO)],
        cwd=str(EMUHAWK.parent),
    )
    tel = Telemetria(out / "decisions.jsonl")
    try:
        b.start_after_listen(timeout=180)
        RAM = b.main_ram()
        b.speed(args.speed)
        b.loadstate(str(ROOT / "runs" / "states" / f"{args.load}.State"))
        b.frame_advance(4)

        gs = st.read(b, RAM)
        log("\nestado inicial:")
        log(gs.render())
        log("\nacoes legais no inicio:")
        log(render_actions(legal_actions(gs)))

        agente = LLMAgent(b, RAM, llm=llm, caderno=caderno, telemetria=tel,
                          usar_cache=args.cache, timeout_duelo_s=args.timeout)

        if fixtures:
            # Envolve a montagem do prompt para guardar exatamente o texto que
            # o modelo viu. Assim o benchmark offline compara modelos sobre
            # situacoes REAIS de jogo, e nao sobre exemplos inventados.
            original = agente.decidir

            def decidir_capturando(gs_, acoes, turno, log=log):
                fixtures.write(json.dumps({
                    "turno": turno,
                    "prompt": montar_duelo(gs_, acoes,
                                           historico=agente.buffer.lista(),
                                           notas=caderno.notas, turno=turno),
                    "n_acoes": len(acoes),
                    "acoes": [a.label for a in acoes],
                    "kinds": [a.kind for a in acoes],
                }, ensure_ascii=False) + "\n")
                fixtures.flush()
                return original(gs_, acoes, turno, log)

            agente.decidir = decidir_capturando

        inicio = time.perf_counter()
        r = agente.jogar(max_turnos=args.turns, log=log)
        duracao = time.perf_counter() - inicio

        log("\n" + "=" * 56)
        log(r.resumo())
        log(f"tempo de relogio: {duracao / 60:.1f} min")
        log("=" * 56)
        log(st.read(b, RAM).render())
        b.screenshot(str(out / "final.png"))
        time.sleep(0.4)
        log(f"\nsaida em: {out}")
        return 0 if r.terminou == "vitoria" else 2
    except BridgeError as exc:
        log(f"ERRO: {exc}")
        return 1
    finally:
        tel.fechar()
        if fixtures:
            fixtures.close()
        arquivo_log.close()
        b.close()


if __name__ == "__main__":
    raise SystemExit(main())
