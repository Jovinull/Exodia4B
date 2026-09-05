"""EXODIA-4B :: Right Arm (peca 2/5) - atuador.

Traduz intencao em botoes, SEMPRE em laco fechado.

A regra que vale mais que qualquer outra aqui: nunca confie em timing fixo.
Aperte, releia a RAM e confirme que o estado foi para onde voce esperava. Sem
isso, um press cai no meio de uma animacao, e engolido em silencio, e o
harness segue achando que funcionou. Foi assim que o nome do jogador saiu
"pgZ" em vez de "EXODIA".
"""

from __future__ import annotations

from dataclasses import dataclass

from .bridge import Bridge
from .state import SELECTED_CARD


# Zonas de monstro por lado. Define o quanto o cursor pode precisar andar.
BOARD_SLOTS = 5


class ActuatorError(RuntimeError):
    pass


@dataclass
class Actuator:
    bridge: Bridge
    domain: str = "MainRAM"
    settle_frames: int = 4
    max_wait_frames: int = 420

    # ----------------------------------------------------------- primitivas

    def _read(self, addr: int, size: int = 2) -> int:
        if size == 1:
            return self.bridge.read_u8(addr, self.domain)
        return self.bridge.read_u16(addr, self.domain)

    def press_until_change(self, button: str, addr: int, size: int = 2,
                           hold: int = 3) -> bool:
        """Aperta e espera o valor em `addr` mudar E assentar.

        Nao basta detectar a primeira mudanca: durante uma animacao o endereco
        do cursor exibe valores transitorios. Ja aconteceu de ele mostrar a
        carta que o oponente estava usando para atacar, no meio da animacao de
        dano, e o atuador achar que o cursor tinha se movido para la.

        Por isso: espera mudar, depois espera parar de mudar.
        """
        before = self._read(addr, size)
        self.bridge.press(button, hold)
        waited = 0
        while waited < self.max_wait_frames:
            self.bridge.frame_advance(self.settle_frames)
            waited += self.settle_frames
            if self._read(addr, size) != before:
                self.wait_stable(addr, size)
                return True
        return False

    def wait_for_idle(self, addr: int = SELECTED_CARD, size: int = 2,
                      stable_for: int = 40) -> int:
        """Espera o jogo parar de animar antes de agir.

        Use isto ANTES de comecar uma sequencia de inputs. Agir enquanto o
        oponente ataca faz os presses serem engolidos e a leitura de estado
        pegar valores de animacao.
        """
        return self.wait_stable(addr, size, stable_for=stable_for)

    def wait_stable(self, addr: int, size: int = 2,
                    stable_for: int = 12) -> int:
        """Espera o valor em `addr` parar de mudar e devolve o valor final.

        Util depois de uma acao que dispara animacao: evita ler estado no meio
        da transicao.
        """
        last = self._read(addr, size)
        stable = 0
        waited = 0
        while waited < self.max_wait_frames and stable < stable_for:
            self.bridge.frame_advance(self.settle_frames)
            waited += self.settle_frames
            cur = self._read(addr, size)
            stable = stable + self.settle_frames if cur == last else 0
            last = cur
        return last

    # -------------------------------------------------------- alto nivel

    def cursor_card(self) -> int:
        """Card id sob o cursor."""
        return self._read(SELECTED_CARD, 2)

    def move_cursor_to_card(self, target_id: int, button: str = "right",
                            max_steps: int = 12,
                            valid_ids: "set[int] | None" = None) -> bool:
        """Anda com o cursor ate ele pousar na carta pedida.

        Confere a cada passo em vez de contar cliques. Se der uma volta
        completa sem achar, desiste - assim um alvo impossivel falha rapido em
        vez de girar para sempre.

        `valid_ids` e o conjunto de cartas que podem legitimamente estar sob o
        cursor (normalmente a nossa mao). Serve para separar duas coisas que se
        parecem: um cursor que realmente parou numa carta, e o endereco
        exibindo a carta de uma ANIMACAO em curso - por exemplo o monstro do
        oponente durante o ataque dele. Sem isso o atuador conta a animacao
        como se fosse posicao de cursor e desiste achando que deu a volta.
        """
        self.wait_for_idle()
        seen: set[int] = set()
        for _ in range(max_steps):
            cur = self.cursor_card()
            if cur == target_id:
                return True
            if valid_ids is not None and cur not in valid_ids:
                # leitura suspeita: espera a animacao acabar e reavalia sem
                # gastar um passo
                self.wait_for_idle(stable_for=60)
                if self.cursor_card() == target_id:
                    return True
                if self.cursor_card() not in valid_ids:
                    self.press_until_change(button, SELECTED_CARD)
                continue
            if cur in seen and len(seen) > 1:
                return False          # deu a volta e nao achou
            seen.add(cur)
            if not self.press_until_change(button, SELECTED_CARD):
                return False          # cursor travou
        return self.cursor_card() == target_id

    def home_cursor(self, max_steps: int = 8) -> int:
        """Leva o cursor ate a extremidade esquerda e devolve a carta de la.

        Existe porque endereçar o cursor por ID de carta e ambiguo: a mesma
        carta pode estar na mao e no campo, e o deck tem copias repetidas -
        foi o que fez o agente selecionar a carta errada e travar.

        A posicao do cursor NAO esta na RAM que ja mapeamos: a busca por um
        indice de slot na faixa 0x09B000 so encontrou contador de animacao,
        ruido de PRNG e o piscar do cursor. Entao a posicao e obtida por
        navegacao: encosta na ponta, e a partir dai conta passos.

        Para na borda quando um "left" nao muda mais a carta sob o cursor.
        """
        anterior = self.cursor_card()
        for _ in range(max_steps):
            if not self.press_until_change("left", SELECTED_CARD):
                return anterior          # nao mudou: e a borda
            atual = self.cursor_card()
            if atual == anterior:
                return atual
            anterior = atual
        return anterior

    def move_cursor_to_slot(self, slot: int, max_steps: int = 8) -> bool:
        """Posiciona o cursor no slot `slot`, contado a partir da esquerda.

        Diferente de mirar por ID, isto distingue duas copias da mesma carta -
        o que a fusao vai exigir.
        """
        self.wait_for_idle()
        self.home_cursor(max_steps)
        for _ in range(slot):
            if not self.press_until_change("right", SELECTED_CARD):
                return False             # acabou a fileira antes do slot
        return True

    def confirm(self) -> None:
        self.bridge.press("cross", 3)
        self.bridge.frame_advance(self.settle_frames * 2)

    def cancel(self) -> None:
        self.bridge.press("circle", 3)
        self.bridge.frame_advance(self.settle_frames * 2)

    # open_hand() foi removido. Ele apertava START achando que abria a visao da
    # mao; medido, START ENCERRA O TURNO. Quem precisa da mao usa
    # ensure_hand_view(), que so confere e nunca aperta botao com efeito de
    # jogo. O nome antigo fica citado aqui de proposito: a ideia de que "Start
    # abre a mao" aparece em varias fontes externas sobre este jogo e nao vale
    # para esta versao.

    # ------------------------------------------------------------- invocacao

    def summon(self, hand_slot: int, card_id: int,
               guardian_star: str = "a", slot_moves: int = 0,
               max_prompts: int = 8, face_up: bool = True,
               flip_button: str = "right") -> bool:
        """Invoca a carta que esta no slot `hand_slot` da mao.

        Fluxo do jogo, mapeado observando uma pessoa jogar:
            1. cursor na carta       (contando slots a partir da borda)
            2. cross                 -> seleciona a carta
            3. seta                  -> desvira (ela comeca de costas)
            4. cross                 -> escolhe o slot do campo
            5. cross                 -> escolhe a guardian star

        O alvo e o SLOT, e nao o id da carta: com copias repetidas no deck o id
        nao distingue duas cartas iguais, e a mesma carta pode estar na mao e
        no campo. `card_id` entra so para CONFERIR o resultado no fim.

        A tela da guardian star ("ESCOLHA O ATRIBUTO") oferece duas opcoes, na
        ordem A e depois B da carta. `guardian_star="b"` desce uma antes de
        confirmar. `slot_moves` desloca o slot de campo escolhido.
        """
        from . import state as _st          # import tardio evita ciclo

        self.wait_for_idle()

        # Garante a visao da mao CONFERINDO, nao apertando Start no escuro:
        # sem isso o cursor pode pousar no CAMPO, e o confirmar abre a escolha
        # de alvo de ataque em vez de invocar.
        if not self.ensure_hand_view():
            self.recover()
            return False

        if not self.move_cursor_to_slot(hand_slot):
            self.recover()
            return False

        antes_s = _st.read(self.bridge, self.domain)
        campo_antes = len(antes_s.field)
        mao_antes = sum(1 for r in antes_s.hand if r.card_id == card_id)

        self.confirm()                       # seleciona a carta
        self.wait_for_idle(stable_for=20)

        # A carta comeca VIRADA PARA BAIXO. Uma seta para qualquer lado a
        # desvira. Sem este passo o monstro entra de costas e nao pode atacar -
        # foi o que fez o agente encher o campo de cartas inuteis.
        if face_up:
            self.bridge.press(flip_button, 3)
            self.bridge.frame_advance(self.settle_frames * 3)

        for _ in range(slot_moves):          # desloca o slot, se pedido
            self.bridge.press("right", 3)
            self.bridge.frame_advance(self.settle_frames * 2)

        # Daqui em diante o numero de prompts NAO e fixo. Confirmar tres vezes
        # as cegas dessincroniza: se o jogo pedir um passo a menos, o confirme
        # sobrando comeca a colocar a proxima carta, e o duelo fica preso num
        # prompt de escolha de slot que nenhum outro botao resolve.
        #
        # O orcamento e 8 porque a medicao mostrou a carta entrando no CONFIRME
        # 5 (tracado passo a passo, com screenshot de cada tela). O valor
        # anterior era exatamente 5 - ou seja, em cima do limite: qualquer
        # prompt a mais e a invocacao falhava. Era isso que fazia so a PRIMEIRA
        # invocacao do duelo funcionar e todas as seguintes falharem com o
        # generico "sequencia de invocacao". Folga aqui nao custa nada: o laco
        # para assim que a carta aparece no campo.
        #
        # Por isso o laco olha o ESTADO a cada volta e decide o que fazer:
        #   carta no campo e fora da mao  -> terminou
        #   carta no campo e ainda na mao -> e o prompt da guardian star
        #   nenhum dos dois               -> ainda falta confirmar posicao
        # ARMADILHA: o deck tem cartas repetidas. Perguntar "essa carta esta no
        # campo e fora da mao?" da falso negativo quando existe outra copia da
        # mesma carta na mao. Por isso conta-se QUANTAS copias estao em cada
        # lugar, e nao se existe alguma.
        # Sucesso e o CAMPO CRESCER, medido pelo total - nao por contagem da
        # carta especifica. Contar por id foi uma correcao a um problema real
        # (copias repetidas davam falso negativo), mas trocou um erro por
        # outro: quando a carta invocada ja tinha uma copia em campo, a leitura
        # entrava em desacordo consigo mesma e a invocacao voltava False tendo
        # funcionado - medido, com o campo indo de 1 para 2.
        #
        # O tamanho do campo nao tem essa ambiguidade: entrou carta, cresceu.
        def contagem(s) -> tuple[int, int]:
            return (len(s.field),
                    sum(1 for r in s.hand if r.card_id == card_id))

        for _ in range(max_prompts):
            s = _st.read(self.bridge, self.domain)
            campo_agora, mao_agora = contagem(s)
            if campo_agora > campo_antes:
                self._sair_da_grade()
                return True
            # uma copia a menos na mao com o campo ainda igual = estamos no
            # meio da colocacao, entao ainda ha prompt para confirmar
            if mao_agora < mao_antes and guardian_star.lower() == "b":
                self.bridge.press("down", 3)
                self.bridge.frame_advance(self.settle_frames * 2)
            self.confirm()

            # ESPERA O EFEITO antes de decidir apertar de novo.
            #
            # Sem isto o laco relia a RAM cedo demais, ainda no meio da
            # animacao, concluia "a carta nao entrou" e mandava outro confirme.
            # Sobravam DOIS confirmes: uma pessoa jogando usou 3 apos desvirar,
            # o harness usava 5. E os dois que sobravam nao caiam no vazio -
            # caiam ja na visao de campo, ABRINDO A MIRA DE ATAQUE. A invocacao
            # terminava "certa" e o ataque seguinte comecava dessincronizado,
            # o que fez o ataque a monstro falhar por sessoes inteiras.
            esperou = 0
            while esperou < 150:
                self.bridge.frame_advance(self.settle_frames * 3)
                esperou += self.settle_frames * 3
                if contagem(_st.read(self.bridge, self.domain))[0] > campo_antes:
                    self._sair_da_grade()
                    return True

        campo_fim, _ = contagem(_st.read(self.bridge, self.domain))
        if campo_fim > campo_antes:
            self._sair_da_grade()
            return True
        # esgotou os prompts sem colocar a carta: nao deixa a mao aberta para
        # a proxima acao
        self.recover()
        return False

    # ------------------------------------------------------- em que tela estou

    # NAO EXISTE flag de "menu aberto" na RAM mapeada. O endereco que ocupava
    # esse papel (0x8009B0AC) e um bit de PARIDADE DE FRAME: alterna 1,0,1,0 a
    # cada frame, e so parecia estavel porque as leituras vinham de 4 em 4
    # frames - um aliasing perfeito. Ver a nota longa em state.py.
    #
    # O prejuizo nao era so ruido. `close_overlay()` decidia apertar START com
    # base nesse bit, e START na visao de campo ENCERRA O TURNO. Metade das
    # vezes, o harness passava o proprio turno no meio de uma jogada. Era essa
    # a causa das invocacoes e ataques que falhavam "sem motivo".
    #
    # A substituicao segue o mesmo caminho que resolveu o cursor: em vez de
    # procurar o endereco certo, PERGUNTAR AO JOGO. A pergunta "o cursor esta
    # sobre uma carta da minha mao?" se responde com dados que ja sao
    # confiaveis - o array de registros e o card id sob o cursor.

    def hand_ids(self) -> set[int]:
        from . import state as _st
        return {r.card_id for r in _st.read(self.bridge, self.domain).hand}

    def cursor_on_hand(self) -> bool:
        """O cursor esta sobre uma carta da nossa mao?

        E uma pergunta com resposta imperfeita: se a mesma carta estiver na mao
        e no campo, os dois casos dao True. Ainda assim e infinitamente melhor
        que o bit de paridade, porque erra so numa coincidencia especifica, e
        nao em metade das leituras.
        """
        return self.cursor_card() in self.hand_ids()

    def ensure_hand_view(self, tries: int = 4) -> bool:
        """Confere que o cursor esta na nossa mao, sem apertar START.

        NAO EXISTE "abrir a mao". No nosso turno a mao ja esta selecionavel: e
        a tela em que o duelo comeca. START nao abre nada - START ENCERRA O
        TURNO. A versao anterior desta funcao apertava START quando achava que
        a mao estava fechada, e o efeito era comico de tao ruim: o harness
        passava o turno, o oponente jogava, compravamos uma carta, e so entao a
        invocacao acontecia. Era isso, e nao uma regra do jogo, que produzia o
        padrao de "uma invocacao por turno".

        O falso negativo que disparava tudo isso: logo depois de carregar um
        savestate, SELECTED_CARD ainda mostra a carta de uma animacao anterior
        - normalmente um monstro do oponente. Nao e o cursor estar no lugar
        errado, e a leitura estar velha. A cura e esperar assentar e cutucar o
        cursor com um LEFT, que e inofensivo, em vez de apertar um botao que
        tem efeito de jogo.
        """
        for i in range(tries):
            self.wait_for_idle(stable_for=40)
            if self.cursor_on_hand():
                return True
            if i % 2 == 0:
                # CANCELAR sai da grade de campo, que e onde o jogo fica depois
                # de um ataque. Sem isto, a acao seguinte comeca com o cursor no
                # campo e a invocacao falha - era o padrao "a primeira acao do
                # turno funciona, as seguintes nao". Cancelar nao tem efeito de
                # jogo: no pior caso nao faz nada.
                self.cancel()
            else:
                # LEFT so move o cursor; no pior caso ele ja estava na borda.
                # Serve para forcar SELECTED_CARD a se atualizar.
                self.press_until_change("left", SELECTED_CARD)
        return self.cursor_on_hand()

    def cursor_on_our_field(self) -> bool:
        """O cursor esta sobre um monstro NOSSO que ja esta em campo?"""
        from . import state as _st
        cur = self.cursor_card()
        return any(r.card_id == cur
                   for r in _st.read(self.bridge, self.domain).field)

    def ensure_field_view(self, tries: int = 4) -> bool:
        """Leva o cursor da mao para a fileira do nosso campo.

        Sem isto o ataque nunca acontece: no comeco do turno o cursor esta na
        MAO, e o `cross` que deveria escolher o atacante comeca a jogar uma
        carta da mao.

        Duas rotas, nessa ordem, porque as duas foram observadas:

        1. **O jogo ja pode ter posto o cursor la.** Vendo uma pessoa jogar,
           logo depois de uma invocacao o proximo `cross` selecionou o
           atacante - ou seja, ao terminar de colocar uma carta o cursor fica
           no campo. Entao antes de apertar qualquer coisa, confira.
        2. **`up`**, quando ainda estamos na mao.

        A verificacao e semantica (o id sob o cursor esta no nosso campo?)
        porque nao existe endereco de posicao de cursor - e `press_until_change`
        nao serve aqui: na grade ha slots VAZIOS, onde o id nao muda e a funcao
        reportaria "nao andou" para um cursor que andou.
        """
        for _ in range(tries):
            self.wait_for_idle(stable_for=40)
            if self.cursor_on_our_field():
                return True
            self.bridge.press("up", 3)
            self.bridge.frame_advance(self.settle_frames * 3)
        self.wait_for_idle(stable_for=40)
        return self.cursor_on_our_field()

    def _sair_da_grade(self) -> None:
        """Sai da grade de campo de volta para a mao, DELIBERADAMENTE.

        Toda acao termina numa tela; a seguinte precisa saber qual. Ate aqui o
        harness tentava DESCOBRIR onde estava, e a descoberta falhava de um
        jeito traicoeiro: `cursor_on_hand()` compara o id sob o cursor com a
        nossa mao, e depois de invocar o cursor fica sobre a carta recem-posta
        - que, com copias no deck, tambem esta na mao. O teste dava "estou na
        mao" com o cursor no campo, `ensure_hand_view()` nao fazia nada, e a
        invocacao seguinte comecava na tela errada. Era o padrao "a primeira
        acao do turno funciona, as outras nao".

        E o mesmo problema do cursor por id (Notes/16 §20), voltando por outra
        porta. A saida e a mesma: parar de adivinhar a posicao e passar a
        DEIXAR o jogo num estado conhecido. Cancelar sai da grade e nao tem
        efeito de jogo nenhum - no pior caso nao faz nada.
        """
        self.wait_for_idle(stable_for=40)
        self.cancel()
        self.wait_for_idle(stable_for=30)

    def recover(self, tries: int = 3) -> bool:
        """Volta a um estado conhecido depois de uma sequencia que falhou.

        So usa CANCELAR. Cancelar sai de prompt e nao tem efeito de jogo - no
        pior caso nao faz nada. START faria o servico em algumas telas e
        ENCERRARIA O TURNO em outra, e nao ha como saber em qual estamos: e
        exatamente a aposta que quebrou o agente. Entre uma recuperacao
        incompleta e um turno perdido, a incompleta e barata.
        """
        for _ in range(tries):
            self.cancel()
            self.wait_for_idle(stable_for=20)
        return True

    # ------------------------------------------------------------- ataque

    def attack(self, field_slot: int, target_slot: int | None = None,
               card_id: int | None = None) -> bool:
        """Ataca com o monstro que esta no slot `field_slot` do nosso campo.

        Fluxo observado numa pessoa jogando devagar:
            1. cursor no NOSSO monstro, na visao de campo
            2. confirmar               -> escolhe o atacante
            3. andar ate o monstro do oponente
            4. confirmar               -> declara o ataque

        Endereça por SLOT, e nao por id: o oponente costuma ter varias copias
        da mesma carta em campo, e mirar por id parava na primeira encontrada,
        que nem sempre e a pretendida.

        Sucesso nao se assume pela sequencia: mede-se pelo efeito - LP do
        oponente, cartas no campo dele, ou o bit de "ja atacou" do atacante.
        """
        from . import state as _st

        # Espera a acao anterior terminar de verdade. A invocacao devolve assim
        # que a RAM mostra a carta em campo, mas a animacao ainda esta rodando -
        # e apertar no meio dela faz o cross ser engolido. Medido: com espera,
        # o ataque sai; sem espera, o mesmo codigo falha sempre.
        self.wait_for_idle(stable_for=60)
        antes = _st.read(self.bridge, self.domain)

        def chave(s):
            return (s.lp_opponent, s.lp_player,
                    tuple(sorted(r.card_id for r in s.opponent_field)),
                    tuple(sorted(r.card_id for r in s.field if r.has_attacked)))

        k = chave(antes)
        alvos = {r.card_id for r in antes.opponent_field}
        if not alvos and target_slot is not None:
            return False

        # O CAMPO E UMA TIRA HORIZONTAL UNICA.
        #
        # Isso e o que os screenshots de uma pessoa jogando mostraram, e muda
        # tudo. Nao existem "duas fileiras" com o nosso campo de um lado e o do
        # oponente do outro: existe uma faixa so, que rola para os lados. Os
        # nossos monstros ficam a ESQUERDA, os do oponente a DIREITA, e no meio
        # ha slots VAZIOS. Andar para a direita atravessa a faixa inteira.
        #
        # Duas consequencias que quebravam o ataque antes:
        #
        # 1. o numero de `right` ate o alvo e uma DISTANCIA, nao um indice -
        #    depende de quantos slots vazios existem no meio;
        # 2. `press_until_change` nao serve para andar aqui: passando por slot
        #    vazio o SELECTED_CARD nao muda, e ela conclui que o cursor travou.
        #    Por isso os apertos abaixo sao CRUS, e quem diz onde paramos e o
        #    id sob o cursor.
        self.confirm()                       # abre a mira, no nosso monstro
        self.wait_for_idle(stable_for=20)

        # Caminha ate pousar num monstro do oponente. E uma busca semantica:
        # nao se conta passos, olha-se onde o cursor esta.
        achou = False
        for _ in range(BOARD_SLOTS * 2 + 4):
            if self.cursor_card() in alvos:
                achou = True
                break
            self.bridge.press("right", 3)
            # 20 frames, nao 8: com espera curta a leitura sai antes de o
            # cursor assentar, o laco "nao ve" o alvo e passa direto por ele.
            # Foi medido - com 8 frames a busca falhava sempre; com 20 acha.
            self.bridge.frame_advance(20)
        if not achou:
            # nunca chegou no lado do oponente: a mira nao abriu, ou o cursor
            # nao estava onde imaginavamos. Nao declara nada as cegas.
            self.recover()
            return False

        # ja estamos no primeiro alvo; anda mais `target_slot` para escolher
        # outro monstro dele
        for _ in range(target_slot or 0):
            self.bridge.press("right", 3)
            self.bridge.frame_advance(self.settle_frames * 2)

        self.confirm()                       # declara

        # ESPERA o efeito aparecer, em vez de conferir uma vez so.
        #
        # O ataque tem animacao longa - o contador de LP desce aos poucos. Uma
        # unica leitura logo depois do confirme pega o estado ANTES do dano, e
        # o ataque e dado como falho tendo funcionado. Foi exatamente isso que
        # aconteceu na primeira vez que a sequencia certa rodou: o LP do
        # oponente caiu de 8000 para 7600 e o metodo devolveu False.
        for _ in range(10):
            self.wait_for_idle(stable_for=40)
            if chave(_st.read(self.bridge, self.domain)) != k:
                return True
        self.recover()
        return False

    # ---------------------------------------------------------- fim de turno

    def end_turn(self, max_presses: int = 3) -> bool:
        """Encerra o turno.

        START so encerra o turno numa das visoes; nas outras ele apenas troca
        de visao. Antes, o harness tentava adivinhar em qual estava, apertava
        uma vez e desistia - e o `end_turn` "falhava" tendo apenas trocado a
        camera de lugar.

        Agora nao adivinha: aperta, mede, e aperta de novo se nada aconteceu.
        Como cada aperto avanca o ciclo de visoes, em poucas tentativas um
        deles cai na tela onde START encerra mesmo. O criterio de sucesso e o
        efeito no duelo - o oponente jogar - nunca a sequencia de botoes.
        """
        from . import state as _st

        def chave(s):
            # o campo do oponente entra carta a carta: ele pode trocar um
            # monstro por outro sem mudar a contagem
            return (s.lp_player, s.lp_opponent, len(s.hand),
                    s.opponent_hand_size,
                    tuple(sorted(r.card_id for r in s.opponent_field)))

        k = chave(_st.read(self.bridge, self.domain))

        for _ in range(max_presses):
            self.bridge.press("start", 4)
            # O turno do oponente inclui compra, jogada e as vezes um ataque
            # com animacao inteira. Esperar pouco dava o fim de turno como
            # falho mesmo tendo funcionado.
            for _ in range(6):
                self.wait_for_idle(stable_for=40)
                if chave(_st.read(self.bridge, self.domain)) != k:
                    return True
        return False
