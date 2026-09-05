"""EXODIA-4B :: tenta invocar um monstro e observar o resultado.

Abre a mao, pousa o cursor num monstro, confirma e entao anda pela sequencia
de colocacao fotografando cada passo. A cada passo checa se alguma carta NOSSA
ganhou a flag de campo; quando isso acontece, despeja os 28 bytes do registro
para localizar a guardian star.

Uso:
    python scripts/summon.py --load saibau
    python scripts/summon.py --load saibau --after "cross,cross,cross,cross"
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
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


def sheet(items, out: Path, cols: int = 4):
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    if not items:
        return None
    th = [(l, Image.open(p).convert("RGB")) for l, p in items]
    for _, im in th:
        im.thumbnail((330, 248))
    w = max(i.width for _, i in th)
    h = max(i.height for _, i in th)
    rows = (len(th) + cols - 1) // cols
    c = Image.new("RGB", (cols * w, rows * (h + 20)), (14, 14, 18))
    d = ImageDraw.Draw(c)
    for i, (l, im) in enumerate(th):
        x, y = (i % cols) * w, (i // cols) * (h + 20)
        c.paste(im, (x, y))
        d.text((x + 4, y + h + 4), l, fill=(255, 214, 92))
    c.save(out)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--load", default="saibau")
    ap.add_argument("--after", default="cross,none,cross,none,cross,none,cross,none",
                    help="sequencia depois de confirmar a carta")
    ap.add_argument("--save", default="pos_invocacao")
    args = ap.parse_args()

    out = ROOT / "runs" / "summon"
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.png"):
        old.unlink()

    b = Bridge(HOST, PORT)
    b.listen()
    subprocess.Popen(
        [str(EMUHAWK), f"--socket_ip={HOST}", f"--socket_port={PORT}",
         f"--lua={LUA}", str(ISO)],
        cwd=str(EMUHAWK.parent),
    )
    shots: list[tuple[str, Path]] = []
    try:
        b.start_after_listen(timeout=180)
        RAM = b.main_ram()
        b.speed(900)
        b.loadstate(str(ROOT / "runs" / "states" / f"{args.load}.State"))
        b.frame_advance(4)

        act = Actuator(b, RAM)
        act.wait_for_idle()
        act.open_hand()
        act.wait_for_idle()

        gs = st.read(b, RAM)
        mao = gs.hand
        monstros = [r for r in mao
                    if (c := cards.get(r.card_id)) and c.is_monster]
        if not monstros:
            print("nenhum monstro na mao")
            return 1
        alvo = max(monstros, key=lambda r: r.attack)
        c = cards.get(alvo.card_id)
        print(f"mao: {[cards.name(r.card_id) for r in mao]}")
        print(f"alvo: {c.short()} (id {alvo.card_id})\n")

        validos = {r.card_id for r in mao}
        if not act.move_cursor_to_card(alvo.card_id, valid_ids=validos):
            print("nao consegui pousar o cursor no alvo")
            return 1
        print(f"cursor no alvo: {act.cursor_card()}")

        def snap(label: str) -> None:
            p = out / f"{len(shots):02d}.png"
            b.screenshot(str(p))
            for _ in range(40):
                if p.exists() and p.stat().st_size > 0:
                    break
                time.sleep(0.05)
            shots.append((label, p))

        snap("cursor no alvo")

        print("\nconfirmando e seguindo a sequencia:")
        print(f"{'passo':>5} {'botao':>7} {'lp':>6} {'campo_meu':>10} "
              f"{'campo_op':>9}  cursor")
        seq = ["cross"] + [x.strip() for x in args.after.split(",") if x.strip()]
        achou = False
        for i, btn in enumerate(seq):
            if btn != "none":
                b.press(btn, 3)
            b.frame_advance(45)
            act.wait_for_idle(stable_for=20)

            g = st.read(b, RAM)
            meu = g.field
            print(f"{i:5} {btn:>7} {g.lp_player:6} {len(meu):10} "
                  f"{len(g.opponent_field):9}  {g.selected_card}")
            snap(f"{btn} campo={len(meu)}")

            if meu and not achou:
                achou = True
                print("\n*** MONSTRO NOSSO EM CAMPO ***")
                for r in meu:
                    cc = cards.get(r.card_id)
                    print(f"  {cc.short() if cc else r.card_id}")
                    print(f"  guardian stars do banco: "
                          f"A={cc.guardian_a} B={cc.guardian_b}")
                    print(f"  raw: {r.raw.hex(' ')}")
                    nz = {o: r.raw[o] for o in range(6, 28) if r.raw[o]}
                    print(f"  bytes nao-zero: {nz}")
                b.savestate(str(ROOT / "runs" / "states" / f"{args.save}.State"))
                time.sleep(0.5)
                print(f"  savestate '{args.save}' gravado")

        s = sheet(shots, out / "_folha.png")
        if s:
            print("\nfolha:", s)
        if not achou:
            print("\nnenhum monstro nosso chegou ao campo nesta sequencia")
        return 0
    except BridgeError as exc:
        print("ERRO:", exc)
        return 1
    finally:
        b.close()


if __name__ == "__main__":
    raise SystemExit(main())
