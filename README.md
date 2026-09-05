# 🧩 EXODIA-4B

**Uma IA local de 4 bilhões de parâmetros tentando zerar Yu-Gi-Oh! Forbidden Memories (PS1).**

Um LLM pequeno rodando **100% na CPU** de um notebook, sem GPU dedicada, joga o
jogo sozinho: duela, percebe que está fraco, farma cartas, remonta o próprio
deck e volta pra tentar de novo — tudo com o raciocínio dele exibido na tela.

> **Por que o nome:** o sistema tem exatamente 5 peças que só funcionam juntas.
> E em *Forbidden Memories* as cartas de Exodia existem mas **não** dão vitória
> instantânea — juntar as peças não basta, ainda é preciso jogar bem.

---

## Como funciona

O truque central é **"visual para o público, dados para a IA"**:

- O jogo roda bonito na tela, com animações, pronto pra gravar.
- Mas o agente **não usa visão computacional**. Ele lê o estado do duelo direto
  da RAM do emulador, em texto estruturado.

Visão é lenta (1,5–4 s por inferência) e erra ao ler texto miúdo de carta. Ler a
memória é instantâneo e exato.

```
BizHawk (PS1) ──Lua/socket──▶ Python ──HTTP──▶ Ollama (LLM local)
      ▲                          │
      └────── inputs ────────────┘
```

## As 5 peças

| Peça | Módulo | Papel |
|---|---|---|
| 🧠 Head | `agent` + `llm` | Decide a jogada |
| 🦾 Right Arm | `actuator` | Traduz decisão em botões |
| 🦾 Left Arm | `exodia/bridge.{lua,py}` | Lê a memória do emulador |
| 🦵 Right Leg | `exodia/state.py` + `exodia/cards.py` | Percepção e regras |
| 🦵 Left Leg | `overlay` + `telemetry` | O que o público vê |

## Estado atual

✅ Ponte com o emulador funcionando
✅ Estado do duelo decodificado (mão, campo, LP, oponente)
🚧 Atuador, agente e overlay em construção

O agente já consegue ler um duelo assim:

```
Seus LP: 7750  |  Oponente (#1) LP: 8000
Sua mão:
  1. Hiro's Shadow Scout (650/500, FeraAlada)
  2. Zone Eater (250/200, Trevas)
  3. White Dolphin (500/400, Aqua)
Seu campo: vazio
Campo do oponente:
  - Steel Scorpion (250/300, Terra)
Cartas na mão do oponente: 4
```

## Regras do projeto

**Descoberta, não receita.** O agente recebe só fatos: o estado atual, as regras
mecânicas do jogo e as ações legais. Nunca uma lista das melhores fusões, das
cartas mais fortes ou um deck pronto. Ele precisa *descobrir* a estratégia
sozinho — é isso que transforma um bot em personagem.

**Sem trapaça.** O agente só enxerga o que um humano veria na tela. O deck
embaralhado do oponente e o PRNG estão na memória e são legíveis, mas **nunca**
entram no prompt. A mão do oponente aparece só como contagem.

## Rodando

Requisitos: Python 3.12+, [BizHawk](https://github.com/TASEmulators/BizHawk),
[Ollama](https://ollama.com), uma cópia do jogo e uma BIOS de PS1 (NTSC-U).
**Nenhum dos dois últimos está neste repositório.**

```bash
python -m venv .venv && .venv/Scripts/pip install pillow requests
ollama pull qwen3:4b

# base de cartas (722 cartas)
curl -sL -o data/raw/Cards.json \
  https://raw.githubusercontent.com/Solumin/YGO-FM-FusionCalc/master/data/Cards.json

# verifica a ponte com o emulador
python scripts/check_bridge.py
```

## Créditos

- RAM map: [Data Crystal](https://datacrystal.tcrf.net/wiki/Yu-Gi-Oh!_Forbidden_Memories/RAM_map)
- Estrutura dos registros de carta: [YuGiOhForbiddenMemoriesRecomp](https://github.com/Unchiga/YuGiOhForbiddenMemoriesRecomp)
- Banco de cartas: [YGO-FM-FusionCalc](https://github.com/Solumin/YGO-FM-FusionCalc)
- Emulação: [BizHawk](https://github.com/TASEmulators/BizHawk)

## Licença

MIT
