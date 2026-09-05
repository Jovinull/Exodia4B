"""EXODIA-4B :: agente aleatorio.

Escolhe uma acao legal ao acaso e executa. Nao serve para jogar bem - serve
para exercitar o harness inteiro sem gastar inferencia: se ele completa um
duelo sem travar, o caminho esta livre para o LLM entrar no lugar dele.

E a melhor ferramenta de debug do projeto: encontra bug de navegacao e de
leitura de estado de graca.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from . import state as st
from .actuator import Actuator
from .bridge import Bridge
from .rules import Action, legal_actions


@dataclass
class Resultado:
    turnos: int = 0
    acoes_ok: int = 0
    acoes_falhas: int = 0
    por_tipo: dict[str, list[int]] = field(default_factory=dict)
    terminou: str = "limite de turnos"

    def registrar(self, kind: str, ok: bool) -> None:
        v = self.por_tipo.setdefault(kind, [0, 0])
        v[0 if ok else 1] += 1
        if ok:
            self.acoes_ok += 1
        else:
            self.acoes_falhas += 1

    def resumo(self) -> str:
        linhas = [f"turnos: {self.turnos}",
                  f"acoes: {self.acoes_ok} ok, {self.acoes_falhas} falhas",
                  f"fim: {self.terminou}"]
        for kind, (ok, falhou) in sorted(self.por_tipo.items()):
            linhas.append(f"  {kind:15} {ok} ok / {falhou} falhas")
        return "\n".join(linhas)


class RandomAgent:
    def __init__(self, bridge: Bridge, domain: str = "MainRAM",
                 seed: int | None = None) -> None:
        self.bridge = bridge
        self.domain = domain
        self.act = Actuator(bridge, domain)
        self.rng = random.Random(seed)

    # ------------------------------------------------------------ execucao

    def executar(self, a: Action, gs: st.GameState) -> bool:
        if a.kind == "summon":
            return self.act.summon(
                a.card_id,
                valid_ids={r.card_id for r in gs.hand},
                guardian_star=a.guardian_star,
            )
        if a.kind in ("attack", "attack_direct"):
            return self.act.attack(a.card_id, a.target_index)
        if a.kind == "end_turn":
            return self.act.end_turn()
        return False

    def jogar(self, max_turnos: int = 30, acoes_por_turno: int = 4,
              log=print) -> Resultado:
        r = Resultado()
        self.act.wait_for_idle()

        for t in range(max_turnos):
            gs = st.read(self.bridge, self.domain)
            if gs.lp_player <= 0 or gs.lp_opponent <= 0:
                r.terminou = ("derrota" if gs.lp_player <= 0 else "vitoria")
                break

            r.turnos += 1
            log(f"\n--- turno {t} --- LP {gs.lp_player} x {gs.lp_opponent} | "
                f"mao {len(gs.hand)} campo {len(gs.field)} "
                f"campo_op {len(gs.opponent_field)}")

            for _ in range(acoes_por_turno):
                gs = st.read(self.bridge, self.domain)
                acoes = legal_actions(gs)
                # o fim de turno so entra no sorteio quando e a unica saida,
                # senao o agente passa o turno o tempo todo e nada acontece
                candidatas = [a for a in acoes if a.kind != "end_turn"] or acoes
                escolha = self.rng.choice(candidatas)
                ok = self.executar(escolha, gs)
                r.registrar(escolha.kind, ok)
                log(f"    {escolha.label[:58]:58} {'ok' if ok else 'FALHOU'}")
                if escolha.kind == "end_turn":
                    break
            else:
                # gastou as acoes do turno sem passar a vez: passa agora
                ok = self.act.end_turn()
                r.registrar("end_turn", ok)
                log(f"    {'(fim de turno automatico)':58} "
                    f"{'ok' if ok else 'FALHOU'}")
        return r
