"""EXODIA-4B :: mapeia a navegacao do cursor no duelo.

Aperta um botao por vez, espera a animacao assentar, le o card id sob o cursor
e tira screenshot. Monta uma folha de contato rotulada com o que a RAM dizia
em cada parada, para conferir a leitura contra a tela.

Uso:
    python scripts/map_cursor.py --load mao_aberta
    python scripts/map_cursor.py --load saibau --open-hand
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

DEFAULT_SEQ = ("right,right,right,right,right,right,"
               "down,right,right,up,left,left")


def sheet(items: list[tuple[str, Path]], out: Path, cols: int = 4) -> Path | None:
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    if not items:
        return None
    thumbs = [(lbl, Image.open(p).convert("RGB")) for lbl, p in items]
    for _, im in thumbs:
        im.thumbnail((330, 248))
    w = max(im.width for _, im in thumbs)
    h = max(im.height for _, im in thumbs)
    rows = (len(thumbs) + cols - 1) // cols
    canvas = Image.new("RGB", (cols * w, rows * (h + 20)), (14, 14, 18))
    d = ImageDraw.Draw(canvas)
    for i, (lbl, im) in enumerate(thumbs):
        x, y = (i % cols) * w, (i // cols) * (h + 20)
        canvas.paste(im, (x, y))
        d.text((x + 4, y + h + 4), lbl, fill=(255, 214, 92))
    canvas.save(out)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--load", default="mao_aberta")
    ap.add_argument("--open-hand", action="store_true",
                    help="aperta Start antes de comecar")
    ap.add_argument("--seq", default=DEFAULT_SEQ)
    args = ap.parse_args()

    out = ROOT / "runs" / "cursor"
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
    try:
        b.start_after_listen(timeout=180)
        RAM = b.main_ram()
        b.speed(900)
        b.loadstate(str(ROOT / "runs" / "states" / f"{args.load}.State"))
        b.frame_advance(4)

        act = Actuator(b, RAM)
        if args.open_hand:
            act.open_hand()
        act.wait_stable(st.SELECTED_CARD)

        gs = st.read(b, RAM)
        print("mao lida da RAM:")
        for i, r in enumerate(gs.hand):
            print(f"  [{i}] id={r.card_id:4} idx={r.index:2}  "
                  f"{cards.name(r.card_id)}")
        print()

        shots: list[tuple[str, Path]] = []

        def snap(label: str, cur: int) -> None:
            p = out / f"{len(shots):02d}.png"
            b.screenshot(str(p))
            for _ in range(40):
                if p.exists() and p.stat().st_size > 0:
                    break
                time.sleep(0.05)
            shots.append((f"{label} -> {cur} {cards.name(cur)[:18]}", p))

        cur = b.read_u16(st.SELECTED_CARD, RAM)
        print(f"{'passo':>5} {'botao':>7} {'mudou':>6} {'cursor':>7}  carta")
        print(f"{'-':>5} {'inicio':>7} {'-':>6} {cur:7}  {cards.name(cur)}")
        snap("inicio", cur)

        for i, btn in enumerate(x.strip() for x in args.seq.split(",") if x.strip()):
            mudou = act.press_until_change(btn, st.SELECTED_CARD)
            cur = b.read_u16(st.SELECTED_CARD, RAM)
            print(f"{i:5} {btn:>7} {'sim' if mudou else 'NAO':>6} {cur:7}  "
                  f"{cards.name(cur)}")
            snap(btn, cur)

        s = sheet(shots, out / "_folha.png")
        if s:
            print("\nfolha de contato:", s)
        return 0
    except BridgeError as exc:
        print("ERRO:", exc)
        return 1
    finally:
        b.close()


if __name__ == "__main__":
    raise SystemExit(main())
