"""EXODIA-4B :: Head (peca 5/5) - cliente do modelo local.

Fala com o Ollama por HTTP e devolve SEMPRE uma decisao estruturada.

Duas escolhas que definem este arquivo:

1. **JSON Schema, nao "format: json".** Pedir "responda em JSON" a um modelo
   pequeno rende JSON quase certo - com um campo a mais, uma virgula solta ou
   um preambulo em prosa. Passar o schema no parametro `format` faz o Ollama
   restringir a decodificacao token a token: o modelo fica impedido de emitir
   um token que quebraria o schema. Deixa de ser parsing e vira garantia.

2. **`reasoning` antes de `action_id`.** O modelo gera da esquerda para a
   direita, entao o campo que vem primeiro condiciona o que vem depois. Com o
   raciocinio primeiro ele pensa antes de escolher; invertido, ele escolhe um
   numero e depois inventa uma justificativa. E, de quebra, o overlay consegue
   transmitir o pensamento enquanto ele se forma.

Sobre modo de raciocinio (qwen3 e hibrido): DESLIGADO por padrao. Em CPU, os
tokens de "thinking" custam dezenas de segundos por jogada e nao aparecem no
video - o raciocinio que interessa e o do campo `reasoning`, que e curto,
capturavel e mostravel.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

import requests

DEFAULT_HOST = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen3:4b"

# Schema da decisao. A ORDEM DAS CHAVES E FUNCIONAL, nao estetica: o Ollama
# repassa a ordem para o gramatico de decodificacao, entao `reasoning` ser o
# primeiro e o que forca o modelo a pensar antes de escolher.
DECISION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "reasoning": {"type": "string", "maxLength": 220},
        "action_id": {"type": "integer", "minimum": 0},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "note": {"type": "string", "maxLength": 120},
    },
    "required": ["reasoning", "action_id", "confidence"],
}


class LLMError(RuntimeError):
    pass


@dataclass
class Resposta:
    """Uma resposta do modelo, com o custo dela.

    A telemetria vem junto de proposito: latencia e contagem de tokens sao
    metrica do video (quao rapido a IA pensa) e ferramenta de diagnostico
    (jogada que demorou 40s costuma ser prompt inchado, nao modelo lento).
    """

    dados: dict[str, Any]
    texto_cru: str
    latencia_ms: int
    prompt_tokens: int = 0
    completion_tokens: int = 0
    modelo: str = ""

    @property
    def tokens_por_segundo(self) -> float:
        if self.latencia_ms <= 0:
            return 0.0
        return self.completion_tokens / (self.latencia_ms / 1000.0)


@dataclass
class LLMClient:
    """Cliente do Ollama afinado para CPU.

    `num_thread` fica em None por padrao para o Ollama decidir. No i5-1335U
    (2 P-cores + 8 E-cores) forcar o numero de nucleos fisicos costuma render
    mais que deixar ele usar todos - as E-cores puxam a media para baixo
    quando o trabalho e dividido por igual.
    """

    modelo: str = DEFAULT_MODEL
    host: str = DEFAULT_HOST
    num_thread: int | None = None
    # 2048 e medido, nao chutado: o maior prompt real observado tem ~840
    # tokens (estado + historico + 20 notas + acoes legais) e a resposta fica
    # em ~60. O dobro disso da folga de sobra. Baixar de 4096 para 2048 tira
    # ~0,3 GB do KV cache - e nesta maquina, com OBS gravando, 0,3 GB nao e
    # detalhe: e a diferenca entre caber e paginar.
    num_ctx: int = 2048
    num_predict: int = 256
    temperature: float = 0.4
    think: bool = False
    timeout: float = 300.0
    keep_alive: str = "30m"
    _sessao: requests.Session = field(default_factory=requests.Session,
                                      repr=False)

    # ------------------------------------------------------------- infra

    def disponivel(self) -> bool:
        try:
            r = self._sessao.get(f"{self.host}/api/version", timeout=5)
            return r.ok
        except requests.RequestException:
            return False

    def modelos(self) -> list[str]:
        r = self._sessao.get(f"{self.host}/api/tags", timeout=10)
        r.raise_for_status()
        return [m["name"] for m in r.json().get("models", [])]

    def aquecer(self) -> float:
        """Carrega o modelo na RAM e devolve quanto tempo levou.

        Vale chamar antes do duelo: a primeira inferencia paga o carregamento
        do modelo (varios segundos em CPU) e, sem isolar isso, essa conta
        aparece como se fosse a latencia de uma jogada.
        """
        t0 = time.perf_counter()
        # Uma geracao REAL, ainda que minima. Mandar `messages: []` devolve na
        # hora sem carregar os pesos, e a conta do carregamento acaba caindo na
        # primeira jogada: medi 26,8 s naquela e 8,5 s nas seguintes, o que
        # sujava a latencia media do duelo inteiro.
        self._sessao.post(
            f"{self.host}/api/chat",
            json={"model": self.modelo,
                  "messages": [{"role": "user", "content": "oi"}],
                  "stream": False, "think": self.think,
                  "keep_alive": self.keep_alive,
                  "options": {"num_predict": 1, "num_ctx": self.num_ctx}},
            timeout=self.timeout,
        )
        return time.perf_counter() - t0

    # ---------------------------------------------------------- inferencia

    def conversar(self, sistema: str, usuario: str,
                  schema: dict[str, Any] | None = None,
                  temperature: float | None = None) -> Resposta:
        corpo: dict[str, Any] = {
            "model": self.modelo,
            "messages": [
                {"role": "system", "content": sistema},
                {"role": "user", "content": usuario},
            ],
            "stream": False,
            "think": self.think,
            "keep_alive": self.keep_alive,
            "options": {
                "temperature": (self.temperature if temperature is None
                                else temperature),
                "num_ctx": self.num_ctx,
                "num_predict": self.num_predict,
            },
        }
        if schema is not None:
            corpo["format"] = schema
        if self.num_thread:
            corpo["options"]["num_thread"] = self.num_thread

        t0 = time.perf_counter()
        try:
            r = self._sessao.post(f"{self.host}/api/chat", json=corpo,
                                  timeout=self.timeout)
        except requests.RequestException as exc:
            raise LLMError(f"Ollama nao respondeu: {exc}") from exc
        latencia = int((time.perf_counter() - t0) * 1000)
        if not r.ok:
            raise LLMError(f"Ollama devolveu {r.status_code}: {r.text[:300]}")

        payload = r.json()
        texto = (payload.get("message") or {}).get("content", "")
        dados: dict[str, Any] = {}
        if schema is not None:
            try:
                dados = json.loads(texto)
            except json.JSONDecodeError as exc:
                # Com schema isso praticamente nao acontece; quando acontece e
                # porque a geracao foi cortada por num_predict no meio do JSON.
                raise LLMError(
                    f"resposta nao e JSON valido ({exc}): {texto[:200]}"
                ) from exc

        return Resposta(
            dados=dados,
            texto_cru=texto,
            latencia_ms=latencia,
            prompt_tokens=int(payload.get("prompt_eval_count") or 0),
            completion_tokens=int(payload.get("eval_count") or 0),
            modelo=self.modelo,
        )

    def decidir(self, sistema: str, prompt: str,
                temperature: float | None = None) -> Resposta:
        """Uma decisao de jogada, presa ao schema."""
        return self.conversar(sistema, prompt, DECISION_SCHEMA, temperature)
