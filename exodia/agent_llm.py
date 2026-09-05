"""EXODIA-4B :: Head (peca 5/5) - o agente que pensa.

Substitui o agente aleatorio mantendo a MESMA interface (`jogar`). Isso e de
proposito: o aleatorio continua existindo como controle. Quando algo quebra,
rodar os dois no mesmo savestate separa em minutos "o modelo jogou mal" de "o
harness quebrou" - a duvida que mais custou tempo neste projeto.

O modelo nunca inventa uma jogada: o `rules.py` enumera as acoes legais e ele
escolhe um NUMERO da lista. Isso mata alucinacao de jogada impossivel, torna a
validacao trivial e corta os tokens de saida - que em CPU valem segundos.

Anti-loop, em camadas (Notes/05). Modelo pequeno trava repetindo a mesma acao
invalida, entao a defesa e escalonada e cada degrau custa mais que o anterior:

  1. historico COM RESULTADO no prompt      - de graca, e o que mais resolve
  2. detector de repeticao                  - remove a acao e re-pergunta
  3. temperatura progressiva 0.4 -> 1.0     - tira o modelo do sulco
  4. fallback deterministico                - passa o turno, e ANUNCIA

O fallback aparece no log e no overlay. Esconder que a IA travou seria mentir
para quem assiste - e, alem de desonesto, e o momento mais engracado do video.
"""

from __future__ import annotations

import hashlib
import time
from collections import Counter
from dataclasses import dataclass, field

from . import state as st
from .actuator import Actuator
from .agent_random import Resultado
from .bridge import Bridge
from .llm import LLMClient, LLMError, Resposta
from .memory import BufferDeTurno, Caderno, Telemetria
from .prompt import SISTEMA, montar_duelo
from .rules import Action, legal_actions

# Sobe a cada nova tentativa no MESMO estado. Comeca baixo porque a jogada
# certa costuma ser obvia; so quando o modelo insiste no erro vale sortear
# mais longe do modo dele.
TEMPERATURAS = (0.4, 0.7, 1.0)

MAX_FIELD = 5


def hash_estado(gs: st.GameState) -> str:
    """Impressao digital do que importa para decidir.

    Serve ao detector de repeticao e ao cache: a mesma situacao de jogo tem que
    dar o mesmo hash. Entram LP, mao, campo dos dois lados e quem ja atacou - e
    fica de fora tudo que muda sozinho (contador de frames, carta sob o
    cursor), senao dois estados identicos nunca casariam.
    """
    partes = [
        gs.lp_player, gs.lp_opponent,
        tuple(sorted(r.card_id for r in gs.hand)),
        tuple(sorted((r.card_id, r.face_down, r.has_attacked)
                     for r in gs.field)),
        tuple(sorted(r.card_id for r in gs.opponent_field)),
    ]
    return hashlib.sha1(repr(partes).encode()).hexdigest()[:10]


@dataclass
class Decisao:
    """O que o agente decidiu, e quanto custou decidir."""

    acao: Action
    indice: int
    reasoning: str = ""
    confidence: float = 0.0
    note: str = ""
    tentativas: int = 0
    fallback: bool = False
    invalidas: int = 0
    latencia_ms: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cache: bool = False


@dataclass
class ResultadoLLM(Resultado):
    """Resultado do duelo mais as metricas do modelo."""

    decisoes: int = 0
    fallbacks: int = 0
    escolhas_invalidas: int = 0
    latencias: list[int] = field(default_factory=list)
    tokens_saida: int = 0
    tokens_prompt: int = 0
    acertos_cache: int = 0
    notas_novas: int = 0

    @property
    def latencia_media(self) -> float:
        return sum(self.latencias) / len(self.latencias) if self.latencias else 0

    @property
    def taxa_valida(self) -> float:
        """% das escolhas do modelo que cairam dentro da lista de primeira."""
        total = self.decisoes + self.escolhas_invalidas
        return 100.0 * self.decisoes / total if total else 0.0

    def resumo(self) -> str:
        linhas = [
            "",
            f"decisoes do modelo: {self.decisoes}",
            f"  latencia media  : {self.latencia_media / 1000:.1f}s",
            f"  acao valida     : {self.taxa_valida:.0f}%  "
            f"({self.escolhas_invalidas} escolhas fora da lista)",
            f"  fallbacks       : {self.fallbacks}",
            f"  tokens          : {self.tokens_prompt} entrada / "
            f"{self.tokens_saida} saida",
        ]
        if self.acertos_cache:
            linhas.append(f"  cache           : {self.acertos_cache} acertos")
        if self.notas_novas:
            linhas.append(f"  notas escritas  : {self.notas_novas}")
        return super().resumo() + "\n".join(linhas)


class LLMAgent:
    def __init__(self, bridge: Bridge, domain: str = "MainRAM",
                 llm: LLMClient | None = None,
                 caderno: Caderno | None = None,
                 telemetria: Telemetria | None = None,
                 max_tentativas: int = 3,
                 limite_repeticao: int = 2,
                 usar_cache: bool = False,
                 timeout_duelo_s: float = 3600.0) -> None:
        self.bridge = bridge
        self.domain = domain
        self.act = Actuator(bridge, domain)
        self.llm = llm or LLMClient()
        self.caderno = caderno
        self.tel = telemetria
        self.max_tentativas = max_tentativas
        self.limite_repeticao = limite_repeticao
        self.usar_cache = usar_cache
        self.timeout_duelo_s = timeout_duelo_s

        self.buffer = BufferDeTurno()
        self._repeticoes: Counter[tuple[str, str]] = Counter()
        self._cache: dict[str, str] = {}

    # ------------------------------------------------------------- decisao

    def decidir(self, gs: st.GameState, acoes: list[Action], turno: int,
                log=print) -> Decisao:
        """Pergunta ao modelo qual acao tomar, com todas as guardas.

        Devolve SEMPRE uma decisao executavel: se o modelo nao produzir uma
        escolha valida dentro do orcamento de tentativas, cai no fallback.
        Nunca propaga excecao para o laco do duelo - um duelo nao pode morrer
        porque o Ollama engasgou numa jogada.
        """
        chave_estado = hash_estado(gs)
        notas = self.caderno.notas if self.caderno else []

        # Cache: so no modo farm. Num duelo gravado, repetir raciocinio
        # empobrece o video, e o tempo economizado nao paga isso.
        #
        # Guarda o ROTULO da acao, nao o indice. O mesmo estado pode gerar uma
        # lista mais curta numa segunda visita - o `excluir` do turno tira
        # atacantes que ja falharam - e ai o indice 3 aponta para outra jogada.
        # Cache que devolve a acao errada e pior que cache nenhum.
        if self.usar_cache and chave_estado in self._cache:
            rotulo = self._cache[chave_estado]
            for i, a in enumerate(acoes):
                if a.label == rotulo:
                    return Decisao(a, i, cache=True,
                                   reasoning="[CACHE] situacao ja resolvida antes")

        # Os indices ORIGINAIS sao preservados: a lista mostrada ao modelo
        # encolhe quando uma acao e banida, e os numeros renumeram. Sem guardar
        # o indice de origem, o agente executaria a acao errada.
        disponiveis: list[tuple[int, Action]] = list(enumerate(acoes))
        banidas: set[int] = set()
        aviso = ""
        invalidas = 0

        for tentativa in range(self.max_tentativas):
            visiveis = [(i, a) for i, a in disponiveis if i not in banidas]
            if not visiveis:
                visiveis = disponiveis
            temp = TEMPERATURAS[min(tentativa, len(TEMPERATURAS) - 1)]
            prompt = montar_duelo(gs, [a for _, a in visiveis],
                                  historico=self.buffer.lista(), notas=notas,
                                  turno=turno, aviso=aviso)
            try:
                resp: Resposta = self.llm.decidir(SISTEMA, prompt, temp)
            except LLMError as exc:
                log(f"    !! o modelo falhou: {exc}")
                invalidas += 1
                aviso = ("A resposta anterior nao pode ser lida. "
                         "Responda apenas o JSON.")
                continue

            aid = resp.dados.get("action_id")
            if not isinstance(aid, int) or not 0 <= aid < len(visiveis):
                invalidas += 1
                aviso = (f"O numero {aid} nao esta na lista. Escolha um numero "
                         f"entre 0 e {len(visiveis) - 1}.")
                log(f"    !! escolha fora da lista ({aid}); re-perguntando")
                continue

            idx_original, escolha = visiveis[aid]

            # Camada 2: a mesma acao, no mesmo estado, pela enesima vez. Nao e
            # teimosia a toa - normalmente a acao falha por um motivo que o
            # modelo nao consegue ver. Entao ela sai do cardapio, e o porque
            # vai escrito no proximo prompt.
            marca = (chave_estado, escolha.label)
            if self._repeticoes[marca] >= self.limite_repeticao:
                banidas.add(idx_original)
                aviso = (f'Voce ja tentou "{escolha.label}" nesta mesma '
                         f"situacao e nao funcionou. Escolha outra coisa.")
                log("    !! acao repetida demais; removida da lista")
                continue

            return Decisao(
                acao=escolha, indice=idx_original,
                reasoning=(resp.dados.get("reasoning") or "").strip(),
                confidence=float(resp.dados.get("confidence") or 0),
                note=(resp.dados.get("note") or "").strip(),
                tentativas=tentativa + 1, invalidas=invalidas,
                latencia_ms=resp.latencia_ms,
                prompt_tokens=resp.prompt_tokens,
                completion_tokens=resp.completion_tokens,
            )

        # Camada 4: acabou o orcamento de tentativas. Passa o turno - e diz
        # bem alto que foi o harness, nao o modelo, que escolheu.
        passar = next((i for i, a in enumerate(acoes)
                       if a.kind == "end_turn"), len(acoes) - 1)
        log("    [FALLBACK] o modelo nao escolheu acao valida; passando o turno")
        return Decisao(acoes[passar], passar, fallback=True, invalidas=invalidas,
                       reasoning="[FALLBACK] o harness escolheu por seguranca")

    # ------------------------------------------------------------ execucao

    def executar(self, a: Action) -> bool:
        if a.kind == "summon":
            return self.act.summon(a.hand_slot, a.card_id,
                                   guardian_star=a.guardian_star)
        if a.kind in ("attack", "attack_direct"):
            return self.act.attack(a.field_slot, a.target_slot, a.card_id)
        if a.kind == "end_turn":
            return self.act.end_turn()
        return False

    def diagnostico(self, a: Action, gs: st.GameState) -> str:
        """Por que a acao pode ter falhado, olhando o estado de antes.

        Vai para o historico do prompt: dizer so "FALHOU" ensina o modelo a
        evitar aquele numero; dizer "campo cheio" ensina a regra.
        """
        if a.kind == "summon":
            return ("campo cheio" if len(gs.field) >= MAX_FIELD
                    else "sequencia de invocacao")
        if a.kind in ("attack", "attack_direct"):
            if a.field_slot is None or a.field_slot >= len(gs.field):
                return "atacante nao esta no campo"
            r = gs.field[a.field_slot]
            if r.face_down:
                return "atacante virado para baixo"
            if r.has_attacked:
                return "ja atacou neste turno"
            return "sequencia de ataque"
        if a.kind == "end_turn":
            return "nada mudou no estado do oponente"
        return "?"

    def _ainda_legal(self, a: Action, gs: st.GameState) -> bool:
        """A acao escolhida continua valendo depois de reler a RAM?

        Entre a pergunta e o aperto do botao passam varios segundos de
        inferencia, e nesse intervalo uma animacao pode terminar. Executar uma
        acao que deixou de existir e como apertar botao no escuro.
        """
        return any(x.kind == a.kind and x.card_id == a.card_id
                   and x.hand_slot == a.hand_slot
                   and x.field_slot == a.field_slot
                   and x.target_slot == a.target_slot
                   for x in legal_actions(gs))

    def _contabilizar(self, r: ResultadoLLM, d: Decisao, ok: bool) -> None:
        r.registrar(d.acao.kind, ok)
        if d.fallback:
            r.fallbacks += 1
        else:
            r.decisoes += 1
        if d.cache:
            r.acertos_cache += 1
        r.escolhas_invalidas += d.invalidas
        r.tokens_saida += d.completion_tokens
        r.tokens_prompt += d.prompt_tokens
        if d.latencia_ms:
            r.latencias.append(d.latencia_ms)

    # --------------------------------------------------------------- duelo

    def jogar(self, max_turnos: int = 30, acoes_por_turno: int = 4,
              log=print) -> ResultadoLLM:
        r = ResultadoLLM()
        inicio = time.perf_counter()
        self.act.wait_for_idle()

        for t in range(max_turnos):
            if time.perf_counter() - inicio > self.timeout_duelo_s:
                r.terminou = "tempo esgotado"
                log("\n!! estourou o tempo maximo de duelo")
                break

            gs = st.read(self.bridge, self.domain)
            if gs.lp_player <= 0 or gs.lp_opponent <= 0:
                r.terminou = "derrota" if gs.lp_player <= 0 else "vitoria"
                break

            r.turnos += 1
            falharam: set[int] = set()
            log(f"\n--- turno {t} --- LP {gs.lp_player} x {gs.lp_opponent} | "
                f"mao {len(gs.hand)} campo {len(gs.field)} "
                f"campo_op {len(gs.opponent_field)}")

            for _ in range(acoes_por_turno):
                # Ler NAO depende da tela aberta. Isso foi medido: os mesmos
                # registros, lidos em quatro visoes diferentes, deram a nossa
                # mao identica nas quatro - so o lado do oponente mudou, e
                # porque o jogo andou de verdade no meio. A crenca antiga de
                # que "com a mao aberta o bit de ja-atacou zera" vinha da flag
                # de sobreposicao quebrada, e nao de uma medicao.
                gs = st.read(self.bridge, self.domain)
                acoes = legal_actions(gs, excluir=falharam)

                d = self.decidir(gs, acoes, t, log=log)
                if d.reasoning:
                    log(f"    [IA] {d.reasoning}")

                if not d.fallback and not self._ainda_legal(
                        d.acao, st.read(self.bridge, self.domain)):
                    log("    !! o estado mudou durante a inferencia; relendo")
                    continue

                ok = self.executar(d.acao)
                motivo = "" if ok else self.diagnostico(d.acao, gs)
                self._contabilizar(r, d, ok)

                if not ok:
                    r.motivos[motivo] = r.motivos.get(motivo, 0) + 1
                    self._repeticoes[(hash_estado(gs), d.acao.label)] += 1
                    if d.acao.kind in ("attack", "attack_direct"):
                        falharam.add(d.acao.field_slot)

                self.buffer.registrar(t, d.acao.label[:46], ok, motivo)
                if self.caderno and d.note and self.caderno.adicionar(d.note):
                    r.notas_novas += 1
                    log(f"    [nota] {d.note}")

                if self.tel:
                    self.tel.escrever({
                        "mode": "DUEL", "turn": t,
                        "state_hash": hash_estado(gs),
                        "action_id": d.indice, "action": d.acao.label,
                        "kind": d.acao.kind, "ok": ok,
                        "reasoning": d.reasoning, "confidence": d.confidence,
                        "note": d.note, "fallback": d.fallback,
                        "retries": max(0, d.tentativas - 1),
                        "invalid": d.invalidas, "cached": d.cache,
                        "latency_ms": d.latencia_ms,
                        "prompt_tokens": d.prompt_tokens,
                        "completion_tokens": d.completion_tokens,
                        "motivo": motivo,
                        "lp_player": gs.lp_player,
                        "lp_opponent": gs.lp_opponent,
                    })

                if self.usar_cache and ok and not d.fallback:
                    self._cache[hash_estado(gs)] = d.acao.label

                marca = "[FALLBACK] " if d.fallback else ""
                tempo = f"  [{d.latencia_ms / 1000:.1f}s]" if d.latencia_ms else ""
                log(f"    {marca}{d.acao.label[:48]:48} "
                    f"{'ok' if ok else 'FALHOU'}"
                    f"{'' if ok else '  <- ' + motivo}{tempo}")

                # Rede de seguranca depois de uma acao que falhou: sai de
                # qualquer prompt pendente com CANCELAR, para a proxima acao
                # nao comecar no meio de um menu.
                #
                # A rede antiga perguntava "tem menu aberto?" a um bit de
                # paridade de frame e, quando ele dizia sim - metade das vezes,
                # ao acaso - apertava START. Na visao de campo, START encerra o
                # turno. A protecao era o dano.
                if not ok:
                    self.act.recover()
                if d.acao.kind == "end_turn":
                    break
            else:
                ok = self.act.end_turn()
                r.registrar("end_turn", ok)
                log(f"    {'(fim de turno automatico)':58} "
                    f"{'ok' if ok else 'FALHOU'}")
        return r
