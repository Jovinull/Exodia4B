"""EXODIA-4B :: Head - memoria do agente, em tres camadas.

| Camada          | Escopo                    | Onde vive        |
|-----------------|---------------------------|------------------|
| Buffer de turno | ultimas acoes do duelo    | RAM do processo  |
| Resumo de duelo | resultado de cada duelo   | duels.jsonl      |
| Caderno         | notas que o agente escreveu | notes.md       |

O caderno e o que permite "descoberta sem receita" (Notes/01): o conhecimento
que o agente acumula vem da experiencia DELE, escrito por ele no campo `note`.
Nada aqui e semeado pelo programador.

Poda: sem limite, o caderno vira lixo repetido e come o contexto - que em CPU
custa segundos por jogada. A poda e por semelhanca, nao so por idade: modelo
pequeno reescreve a mesma licao com outras palavras varias vezes seguidas.
"""

from __future__ import annotations

import contextlib
import json
import re
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

MAX_NOTAS = 20


def _normalizar(texto: str) -> str:
    """Reduz a nota a um esqueleto comparavel, para achar duplicata."""
    t = texto.lower().strip()
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    return " ".join(t.split())


def _parecidas(a: str, b: str, limiar: float = 0.6) -> bool:
    """Duas notas dizem a mesma coisa? Jaccard sobre palavras.

    Grosseiro de proposito: comparar por embedding custaria uma inferencia
    inteira por nota, e o que se quer aqui e so evitar vinte variacoes de
    'monstro virado para baixo nao ataca'.
    """
    pa, pb = set(_normalizar(a).split()), set(_normalizar(b).split())
    if not pa or not pb:
        return False
    return len(pa & pb) / len(pa | pb) >= limiar


@dataclass
class Caderno:
    """Notas persistentes do agente."""

    caminho: Path
    notas: list[str] = field(default_factory=list)
    maximo: int = MAX_NOTAS

    def carregar(self) -> "Caderno":
        if self.caminho.exists():
            self.notas = [ln[2:].strip() for ln in
                          self.caminho.read_text(encoding="utf-8").splitlines()
                          if ln.startswith("- ")]
        return self

    def adicionar(self, nota: str) -> bool:
        """Guarda a nota se ela for nova. Devolve se guardou."""
        nota = (nota or "").strip()
        if len(nota) < 8:
            return False
        if any(_parecidas(nota, n) for n in self.notas):
            return False
        self.notas.append(nota)
        if len(self.notas) > self.maximo:
            self.notas = self.notas[-self.maximo:]
        self.salvar()
        return True

    def salvar(self) -> None:
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        corpo = ["# Caderno do agente",
                 "",
                 "Escrito pelo proprio agente, pelo campo `note` das decisoes.",
                 ""]
        corpo += [f"- {n}" for n in self.notas]
        self.caminho.write_text("\n".join(corpo) + "\n", encoding="utf-8")


@dataclass
class BufferDeTurno:
    """Ultimas acoes do duelo atual, com resultado."""

    tamanho: int = 8
    itens: deque[str] = field(default_factory=lambda: deque(maxlen=8))

    def __post_init__(self) -> None:
        self.itens = deque(maxlen=self.tamanho)

    def registrar(self, turno: int, rotulo: str, ok: bool,
                  motivo: str = "") -> None:
        fim = "OK" if ok else f"FALHOU ({motivo})" if motivo else "FALHOU"
        self.itens.append(f"turno {turno}: {rotulo} -> {fim}")

    def lista(self) -> list[str]:
        return list(self.itens)

    def limpar(self) -> None:
        self.itens.clear()


class Telemetria:
    """Uma linha JSONL por decisao, gravada NA HORA.

    Escrever so no fim ja custou dois conjuntos de dados neste projeto: um
    Ctrl+C e uma queda de socket levaram junto tudo que estava em memoria.
    Cada linha vai para o disco com flush imediato - um duelo interrompido
    ainda deixa telemetria util.
    """

    def __init__(self, caminho: Path) -> None:
        self.caminho = Path(caminho)
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        self._f = self.caminho.open("a", encoding="utf-8")

    def escrever(self, registro: dict) -> None:
        registro.setdefault("ts", datetime.now().isoformat(timespec="seconds"))
        self._f.write(json.dumps(registro, ensure_ascii=False) + "\n")
        self._f.flush()

    def fechar(self) -> None:
        with contextlib.suppress(OSError):
            self._f.close()

    def __enter__(self) -> "Telemetria":
        return self

    def __exit__(self, *exc) -> None:
        self.fechar()
