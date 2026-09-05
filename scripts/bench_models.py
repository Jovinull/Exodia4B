"""EXODIA-4B :: benchmark da escada de modelos.

Responde a pergunta da Fase 3: **qual o modelo mais leve que ainda joga bem?**
Nao o maior - o mais leve que entrega qualidade alta (Notes/15).

Duas etapas, porque medir bem exige separar duas coisas que se confundem:

  --capturar   liga no emulador, carrega savestates reais e grava os PROMPTS
               exatos que o agente veria. Nao gasta inferencia nenhuma.
  (padrao)     roda os modelos OFFLINE contra esses prompts.

Por que separar: comparar modelos num duelo ao vivo e injusto e lento. Cada um
joga um duelo diferente, encontra estados diferentes, e uma jogada ruim no
turno 2 muda tudo que vem depois. Com os prompts congelados, todo modelo
responde exatamente as MESMAS perguntas - a diferenca medida e do modelo, e
nao da sorte.

O que se mede aqui e velocidade e disciplina de formato. Qualidade de jogo de
verdade so o duelo ao vivo mostra (`run_llm.py`).

Uso:
    python scripts/bench_models.py --capturar
    python scripts/bench_models.py --modelos qwen3:4b,llama3.2:3b,qwen3:8b
    python scripts/bench_models.py --threads 0,4,6,8      # sweep de threads
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from exodia import state as st  # noqa: E402
from exodia.bridge import Bridge, BridgeError  # noqa: E402
from exodia.llm import LLMClient, LLMError  # noqa: E402
from exodia.prompt import SISTEMA, montar_duelo  # noqa: E402
from exodia.rules import legal_actions  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
EMUHAWK = ROOT / "tools" / "BizHawk" / "EmuHawk.exe"
LUA = ROOT / "exodia" / "bridge.lua"
ISO = (ROOT / "[PS1]_Yu-Gi-Oh! Forbidden Memories (PT-BR)"
       / "Yu-Gi-Oh! Forbidden Memories (PT-BR).cue")
HOST, PORT = "127.0.0.1", 55355

FIXTURES = ROOT / "runs" / "bench" / "prompts.jsonl"


# --------------------------------------------------------------- captura

def capturar(estados: list[str], destino: Path) -> int:
    """Grava um prompt real por savestate."""
    destino.parent.mkdir(parents=True, exist_ok=True)
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
        with destino.open("w", encoding="utf-8") as f:
            for nome in estados:
                caminho = ROOT / "runs" / "states" / f"{nome}.State"
                if not caminho.exists():
                    print(f"  - {nome}: savestate nao existe, pulando")
                    continue
                b.loadstate(str(caminho))
                b.frame_advance(20)
                gs = st.read(b, RAM)
                acoes = legal_actions(gs)
                if not gs.in_duel or len(acoes) < 2:
                    print(f"  - {nome}: nao esta num duelo decidivel, pulando")
                    continue
                f.write(json.dumps({
                    "estado": nome,
                    "prompt": montar_duelo(gs, acoes, turno=0),
                    "n_acoes": len(acoes),
                    "acoes": [a.label for a in acoes],
                    "kinds": [a.kind for a in acoes],
                }, ensure_ascii=False) + "\n")
                n += 1
                print(f"  - {nome}: {len(acoes)} acoes legais")
    except BridgeError as exc:
        print("ERRO:", exc)
    finally:
        b.close()
    return n


# ------------------------------------------------------------- benchmark

def medir(cliente: LLMClient, fixtures: list[dict], repeticoes: int,
          rotulo: str) -> dict:
    """Roda um modelo contra todos os prompts e devolve as metricas."""
    latencias: list[int] = []
    saida: list[int] = []
    entrada: list[int] = []
    validas = 0
    total = 0
    erros = 0
    passar_sempre = 0

    print(f"\n>>> {rotulo}")
    print(f"    aquecendo... {cliente.aquecer():.1f}s")
    for rep in range(repeticoes):
        for fx in fixtures:
            total += 1
            try:
                r = cliente.decidir(SISTEMA, fx["prompt"])
            except LLMError as exc:
                erros += 1
                print(f"    ! {exc}")
                continue
            aid = r.dados.get("action_id")
            ok = isinstance(aid, int) and 0 <= aid < fx["n_acoes"]
            validas += int(ok)
            latencias.append(r.latencia_ms)
            saida.append(r.completion_tokens)
            entrada.append(r.prompt_tokens)
            # "passar o turno" e a saida preguicosa: um modelo que so passa o
            # turno tem 100% de acao valida e nao joga nada. Sem esta coluna a
            # tabela premiaria justamente o modelo inutil.
            if ok and fx["kinds"][aid] == "end_turn":
                passar_sempre += 1
            print(f"    [{rep}] {fx['estado'][:12]:12} {r.latencia_ms/1000:5.1f}s "
                  f"in={r.prompt_tokens:4} out={r.completion_tokens:3} "
                  f"-> #{aid} {'ok' if ok else 'INVALIDA'}")

    return {
        "rotulo": rotulo,
        "amostras": total,
        "erros": erros,
        "validas_pct": 100.0 * validas / total if total else 0.0,
        "passar_pct": 100.0 * passar_sempre / validas if validas else 0.0,
        "lat_media": statistics.mean(latencias) if latencias else 0,
        "lat_mediana": statistics.median(latencias) if latencias else 0,
        "tok_s": (sum(saida) / (sum(latencias) / 1000)) if latencias else 0,
        "out_medio": statistics.mean(saida) if saida else 0,
        "in_medio": statistics.mean(entrada) if entrada else 0,
    }


def tabela(linhas: list[dict]) -> str:
    cab = (f"{'modelo / config':28} {'lat med':>8} {'mediana':>8} "
           f"{'tok/s':>7} {'valida':>7} {'so passa':>9} {'out':>5}")
    out = [cab, "-" * len(cab)]
    for r in linhas:
        out.append(
            f"{r['rotulo'][:28]:28} {r['lat_media']/1000:7.1f}s "
            f"{r['lat_mediana']/1000:7.1f}s {r['tok_s']:7.1f} "
            f"{r['validas_pct']:6.0f}% {r['passar_pct']:8.0f}% "
            f"{r['out_medio']:5.0f}")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--capturar", action="store_true")
    ap.add_argument("--estados",
                    default="meu_turno,maoaberta,campo_livre,pos_summon,saibau")
    ap.add_argument("--modelos", default="qwen3:4b")
    ap.add_argument("--threads", default="",
                    help="lista de num_thread para varrer, ex: 0,4,6,8 "
                         "(0 = deixa o Ollama decidir)")
    ap.add_argument("--repeticoes", type=int, default=2)
    ap.add_argument("--fixtures", default=str(FIXTURES))
    args = ap.parse_args()

    destino = Path(args.fixtures)

    if args.capturar:
        print("capturando prompts reais do jogo...")
        n = capturar([e.strip() for e in args.estados.split(",") if e.strip()],
                     destino)
        print(f"\n{n} prompts gravados em {destino}")
        return 0 if n else 1

    if not destino.exists():
        print(f"ERRO: {destino} nao existe. Rode antes:\n"
              f"    python scripts/bench_models.py --capturar")
        return 1
    fixtures = [json.loads(ln) for ln in
                destino.read_text(encoding="utf-8").splitlines() if ln.strip()]
    print(f"{len(fixtures)} prompts, {args.repeticoes} repeticoes cada")

    sonda = LLMClient()
    if not sonda.disponivel():
        print("ERRO: Ollama nao respondeu")
        return 1
    baixados = sonda.modelos()

    resultados: list[dict] = []
    modelos = [m.strip() for m in args.modelos.split(",") if m.strip()]
    threads = ([int(t) for t in args.threads.split(",") if t.strip()]
               if args.threads else [0])

    for modelo in modelos:
        if modelo not in baixados:
            print(f"\n!! {modelo} nao esta baixado; pulando")
            continue
        for th in threads:
            rotulo = modelo + (f" t={th}" if th else "")
            cliente = LLMClient(modelo=modelo, num_thread=th or None)
            resultados.append(medir(cliente, fixtures, args.repeticoes, rotulo))

    if not resultados:
        print("nada medido")
        return 1

    print("\n" + "=" * 76)
    print(tabela(resultados))
    print("=" * 76)
    print("valida = escolheu um numero da lista | so passa = das validas, "
          "quantas foram 'passar o turno'")

    saida = destino.parent / "resultado.json"
    saida.write_text(json.dumps(resultados, indent=2, ensure_ascii=False),
                     encoding="utf-8")
    print(f"\ndetalhe em {saida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
