"""EXODIA-4B :: Head - montagem do prompt.

REGRA DE OURO (Notes/01): aqui entram REGRAS MECANICAS, nunca estrategia.
Explicar *como* uma fusao funciona: pode. Dizer *o que* fundir, qual carta e
boa, ou qual jogada e a melhor: nao pode. A descoberta e do agente - e e ela
que transforma um bot em personagem no video.

Na duvida, o teste e simples: se a frase ajudaria um jogador humano que ja
conhece as regras a jogar MELHOR, ela nao pode estar aqui.

Economia de tokens nao e detalhe. Em CPU cada token do prompt custa tempo de
relogio antes de o modelo comecar a responder, e cada token de saida custa
~120 ms. Um prompt duas vezes maior nao joga duas vezes melhor - so demora
duas vezes mais.
"""

from __future__ import annotations

from .rules import Action
from .state import GameState

SISTEMA = """Voce joga Yu-Gi-Oh! Forbidden Memories (PS1). Voce e o jogador.

Responda SOMENTE com JSON no schema dado. Nada fora do JSON.

Campos:
- reasoning: UMA frase curta (ate 20 palavras) dizendo POR QUE escolheu.
  Nunca repita o estado nem liste as acoes. Va direto ao motivo.
- action_id: o numero de uma acao da lista. So numeros que aparecem la.
- confidence: 0 a 1.
- note: deixe VAZIO quase sempre. Preencha so quando descobrir uma regra do
  jogo que valha para duelos FUTUROS - nunca para comentar a jogada atual.

Seja decidido. Escolha e siga."""

# Mecanica do jogo, sem juizo de valor. Cada linha e verificavel na tela.
REGRAS = """REGRAS
- Vence quem zerar os Life Points do adversario.
- Monstro invocado de frente pode atacar; cada um ataca uma vez por turno.
- Atacar monstro: quem tem ATK maior destroi o outro; a diferenca vira dano.
  ATK iguais destroem os dois. Nao ha dano se o defensor sobreviver.
- Sem monstros no campo do adversario, o ataque atinge os LP dele direto.
- Cada monstro tem uma guardian star. Certas estrelas tem vantagem sobre
  outras e dao um bonus grande de ATK no combate. Voce escolhe qual das duas
  estrelas da carta usar ao invocar; a escolha e permanente.
- O campo comporta ate 5 monstros por lado."""


def _historico(itens: list[str], limite: int = 5) -> str:
    """Ultimas acoes COM RESULTADO.

    Sem o resultado o historico nao ensina nada: "invoquei X" nao diz se deu
    certo. E o resultado que faz o modelo parar de repetir uma acao que falha
    - e a defesa anti-loop mais barata que existe, bem antes de mexer em
    temperatura ou fallback.
    """
    if not itens:
        return ""
    ultimos = itens[-limite:]
    return "SUAS ULTIMAS ACOES\n" + "\n".join(f"- {i}" for i in ultimos)


def _notas(notas: list[str], limite: int = 20) -> str:
    if not notas:
        return ""
    return "SUAS NOTAS\n" + "\n".join(f"- {n}" for n in notas[-limite:])


def montar_duelo(gs: GameState, acoes: list[Action],
                 historico: list[str] | None = None,
                 notas: list[str] | None = None,
                 turno: int = 0,
                 aviso: str = "") -> str:
    """Prompt do modo DUEL.

    `aviso` e a mensagem de re-pergunta depois de uma escolha invalida ou
    repetida. Ela entra no proprio prompt em vez de virar so um retry mudo:
    dizer ao modelo o que ele fez de errado corrige muito mais que sortear de
    novo com a mesma pergunta.
    """
    blocos = [
        REGRAS,
        f"ESTADO (turno {turno})\n{gs.render()}",
    ]
    if h := _historico(historico or []):
        blocos.append(h)
    if n := _notas(notas or []):
        blocos.append(n)
    blocos.append("ACOES LEGAIS\n" + "\n".join(
        f"{i}: {a.label}" for i, a in enumerate(acoes)))
    if aviso:
        blocos.append(f"ATENCAO\n{aviso}")
    blocos.append("Escolha uma acao e responda com o JSON.")
    return "\n\n".join(blocos)
