"""EXODIA-4B :: onde o ataque a um monstro quebra?

Sintoma: atacar DIRETO (campo do oponente vazio) funciona, e atacar um monstro
falha sempre. A diferenca entre os dois caminhos e um so: a navegacao ate o
alvo. O suspeito e o `move_cursor_to_slot`, que comeca encostando o cursor na
borda ESQUERDA - e depois de escolher o atacante o cursor ja esta do lado do
oponente, onde andar para a esquerda pode sair da mira em vez de encostar numa
borda.

O relato de quem jogou devagar foi: `cross`, `right` cinco vezes, `cross`. Ou
seja, a partir do proprio atacante o cursor ANDA PARA A DIREITA ate o alvo -
sem voltar para canto nenhum.

Este script prepara um monstro nosso em campo, declara o ataque e para em cada
botao, anotando LP dos dois lados e screenshot.

Uso:
    python scripts/trace_attack.py --load meu_turno --rights 5
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from exodia import cards, state as st  # noqa: E402
from exodia.actuator import Actuator  # noqa: E402
from exodia.bridge import Bridge, BridgeError  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
EMUHAWK = ROOT / "tools" / "BizHawk" / "EmuHawk.exe"
LUA = ROOT / "exodia" / "bridge.lua"
ISO = (ROOT / "[PS1]_Yu-Gi-Oh! Forbidden Memories (PT-BR)"
       / "Yu-Gi-Oh! Forbidden Memories (PT-BR).cue")
HOST, PORT = "127.0.0.1", 55355


def onde(gs: st.GameState, cur: int) -> str:
    """Em que fileira o cursor esta, deduzido pelo card id sob ele.

    Nao ha endereco de posicao de cursor na RAM mapeada, entao a fileira sai da
    unica coisa confiavel: o id da carta sob o cursor comparado com o que a
    leitura de estado diz estar em cada lugar. Ambiguo quando a mesma carta
    esta em dois lugares - e ainda assim suficiente para responder a pergunta
    que interessa aqui: "o cursor saiu da mao?".
    """
    lugares = []
    if any(r.card_id == cur for r in gs.hand):
        lugares.append("MAO")
    if any(r.card_id == cur for r in gs.field):
        lugares.append("NOSSO CAMPO")
    if any(r.card_id == cur for r in gs.opponent_field):
        lugares.append("CAMPO DO OPONENTE")
    return "/".join(lugares) or "fora do estado (animacao?)"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--load", default="meu_turno")
    ap.add_argument("--ancorar", action="store_true",
                    help="chama ensure_hand_view antes de medir (nao usar em "
                         "teste de ataque: puxa o cursor de volta para a mao)")
    ap.add_argument("--gap", type=int, default=0,
                    help="frames de espera fixa entre os apertos (imita a "
                         "cadencia humana; 0 = espera o cursor assentar)")
    ap.add_argument("--raw", action="store_true",
                    help="usa aperto cru em vez de esperar o cursor mudar")
    ap.add_argument("--nav", default="up,up,up,right,right,right",
                    help="sequencia de botoes a testar, separada por virgula")
    args = ap.parse_args()

    out = ROOT / "runs" / "trace_attack"
    out.mkdir(parents=True, exist_ok=True)
    for velho in out.glob("*.png"):
        velho.unlink()

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
        b.loadstate(str(ROOT / "runs" / "states" / f"{args.load}.State"))
        b.frame_advance(60)
        act = Actuator(b, RAM)
        act.wait_for_idle()

        def marcar(rotulo: str) -> st.GameState:
            nonlocal n
            gs = st.read(b, RAM)
            cur = cards.get(act.cursor_card())
            campo = [f"{(cards.get(r.card_id) or '?')!s:.14}"
                     f"{'*' if r.has_attacked else ''}" for r in gs.field]
            opo = [f"{(cards.get(r.card_id) or '?')!s:.14}"
                   for r in gs.opponent_field]
            print(f"\n[{n}] {rotulo}")
            print(f"     LP {gs.lp_player} x {gs.lp_opponent}   "
                  f"cursor -> {cur.name if cur else act.cursor_card()}")
            print(f"     nosso campo: {campo or '-'}")
            print(f"     campo do oponente: {opo or '-'}")
            limpo = "".join(ch if ch.isalnum() else "-" for ch in rotulo[:24])
            b.screenshot(str(out / f"{n:02d}_{limpo}.png"))
            n += 1
            return gs

        # 1. garante um monstro nosso em campo para poder atacar
        gs = marcar("estado inicial")
        if not gs.field:
            alvo = next((i for i, r in enumerate(gs.hand)
                         if (c := cards.get(r.card_id)) and c.is_monster), None)
            if alvo is None:
                print("sem monstro na mao para preparar o ataque")
                return 1
            print(f"\npreparando: invocando o slot {alvo} da mao...")
            ok = act.summon(alvo, gs.hand[alvo].card_id)
            print(f"  -> {'ok' if ok else 'FALHOU'}")
            # NAO passa o turno. No log da pessoa jogando, o ataque veio logo
            # depois da invocacao, no MESMO turno - e foi justamente ai que o
            # cursor estava no campo. Passar a vez aqui jogava fora exatamente
            # a condicao que se quer medir.
            gs = marcar("logo apos invocar, sem passar a vez")

        if not gs.field:
            print("nao consegui por um monstro em campo; abortando")
            return 1

        # Precisa de um alvo. O oponente nem sempre tem monstro em campo logo
        # apos o nosso turno, entao passa a vez ate ele por um.
        for _ in range(4):
            if gs.opponent_field:
                break
            print("  oponente sem monstro; passando a vez...")
            act.end_turn()
            gs = marcar("apos passar a vez esperando um alvo")
        if not gs.opponent_field:
            print("o oponente seguiu sem monstros; abortando")
            return 1

        # 2. percorre a sequencia pedida, dizendo a cada passo em que FILEIRA
        #    o cursor caiu. Era essa a informacao que faltava: o ataque falhava
        #    porque o cursor nunca saia da mao, e "andar para a direita" so
        #    passeava entre as cartas da mao.
        gs0 = gs
        # Ancora o cursor na mao ANTES de medir. Depois do turno do oponente,
        # SELECTED_CARD ainda exibe a carta da animacao dele - a leitura esta
        # velha, o cursor nao esta la. Sem esta ancoragem, todo passo parece
        # "nao mudou nada" e a medicao vira lixo.
        # ...mas SO quando pedido. Ancorar chama ensure_hand_view(), que puxa o
        # cursor de volta para a mao - justamente o que destroi a condicao que
        # se quer medir no ataque, onde o cursor precisa ficar no campo.
        if args.ancorar:
            act.ensure_hand_view()
        marcar(f"inicio -> {onde(st.read(b, RAM), act.cursor_card())}")

        print(f"\n--- navegando: {args.nav} ---")
        for passo in [p.strip() for p in args.nav.split(",") if p.strip()]:
            if passo == "cross":
                act.confirm()
                act.wait_for_idle(stable_for=30)
                mudou = True
            elif passo == "circle":
                act.cancel()
                act.wait_for_idle(stable_for=30)
                mudou = True
            elif args.gap:
                # Reproduz a CADENCIA de uma pessoa jogando, em vez de esperar
                # o SELECTED_CARD assentar. Serve para separar duas causas que
                # dao o mesmo sintoma: "o cursor esta no lugar errado" e "os
                # apertos estao chegando cedo demais, no meio de animacao".
                b.press(passo, 3)
                b.frame_advance(args.gap)
                mudou = True
            elif args.raw:
                # Aperto cru. Necessario para medir movimento na GRADE DO
                # CAMPO: la existem slots VAZIOS, e num slot vazio o
                # SELECTED_CARD nao muda. O press_until_change entao reporta
                # "nao andou" para um cursor que andou - falso negativo que faz
                # a rota parecer inexistente.
                b.press(passo, 3)
                act.wait_for_idle(stable_for=30)
                mudou = True
            else:
                mudou = act.press_until_change(passo, st.SELECTED_CARD)
            lugar = onde(st.read(b, RAM), act.cursor_card())
            marcar(f"{passo} mudou={int(mudou)} -> {lugar}")

        fim = st.read(b, RAM)

        print("\n===== VEREDITO =====")
        print(f"  LP do oponente: {gs0.lp_opponent} -> {fim.lp_opponent}")
        print(f"  campo dele    : {len(gs0.opponent_field)} -> "
              f"{len(fim.opponent_field)}")
        atacou = any(r.has_attacked for r in fim.field)
        print(f"  algum nosso marcado como 'ja atacou': {atacou}")
        if (fim.lp_opponent != gs0.lp_opponent
                or len(fim.opponent_field) != len(gs0.opponent_field)
                or atacou):
            print("  O ATAQUE ACONTECEU")
        else:
            print("  nada mudou: o ataque nao saiu")
        print(f"\nscreenshots em {out}")
        return 0
    except BridgeError as exc:
        print("ERRO:", exc)
        return 1
    finally:
        b.close()


if __name__ == "__main__":
    raise SystemExit(main())
