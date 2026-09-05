"""EXODIA-4B :: explorador de estado.

Avanca o jogo em blocos, apertando botoes, e registra a cada bloco:
    - os enderecos-chave da RAM
    - um screenshot

So guarda screenshot quando a TELA MUDA de verdade (hash do arquivo), para nao
gerar centenas de imagens iguais. No fim monta uma folha de contato (grade) com
as telas distintas, numeradas, para inspecao rapida.

Uso:
    python scripts/explore_screens.py --steps 40 --press Cross --frames 90
    python scripts/explore_screens.py --steps 20 --press Start --frames 120 --speed 800
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from exodia.bridge import Bridge, BridgeError  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
EMUHAWK = ROOT / "tools" / "BizHawk" / "EmuHawk.exe"
LUA = ROOT / "exodia" / "bridge.lua"

ISOS = {
    "ptbr": ROOT / "[PS1]_Yu-Gi-Oh! Forbidden Memories (PT-BR)"
                 / "Yu-Gi-Oh! Forbidden Memories (PT-BR).cue",
    "backup": ROOT / "[SLUS-01411]_Yu-Gi-Oh!_-_Forbidden_Memories" / "YUGIOH.ccd",
}

ADDR = {
    "lp1": (0x800EA004, 2),
    "lp2": (0x800EA024, 2),
    "menu": (0x80184594, 1),
    "mode": (0x8009B26C, 1),
    "opp": (0x8009B361, 1),
    "turn": (0x8009B1D5, 1),
}

HOST, PORT = "127.0.0.1", 55355


def contact_sheet(images: list[Path], out: Path, cols: int = 4) -> Path | None:
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    if not images:
        return None
    thumbs = []
    for p in images:
        im = Image.open(p).convert("RGB")
        im.thumbnail((320, 240))
        thumbs.append((p.stem, im))
    w = max(t.width for _, t in thumbs)
    h = max(t.height for _, t in thumbs)
    rows = (len(thumbs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * w, rows * (h + 16)), (18, 18, 22))
    d = ImageDraw.Draw(sheet)
    for i, (name, t) in enumerate(thumbs):
        x, y = (i % cols) * w, (i // cols) * (h + 16)
        sheet.paste(t, (x, y))
        d.text((x + 4, y + h + 2), name, fill=(230, 230, 120))
    sheet.save(out)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--iso", choices=list(ISOS), default="ptbr")
    ap.add_argument("--steps", type=int, default=30)
    ap.add_argument("--frames", type=int, default=90, help="frames por bloco")
    ap.add_argument("--press", default="Cross", help="botao a apertar por bloco")
    ap.add_argument("--speed", type=int, default=800)
    ap.add_argument("--boot", type=int, default=900, help="frames de boot antes de comecar")
    ap.add_argument("--tag", default="explore")
    ap.add_argument("--load", default=None,
                    help="carrega um savestate logo apos conectar (pula o boot)")
    ap.add_argument("--save", default=None,
                    help="salva um savestate ao final")
    args = ap.parse_args()

    outdir = ROOT / "runs" / args.tag
    outdir.mkdir(parents=True, exist_ok=True)
    for old in outdir.glob("*.png"):
        old.unlink()

    bridge = Bridge(HOST, PORT)
    bridge.listen()
    proc = subprocess.Popen(
        [str(EMUHAWK), f"--socket_ip={HOST}", f"--socket_port={PORT}",
         f"--lua={LUA}", str(ISOS[args.iso])],
        cwd=str(EMUHAWK.parent),
    )
    try:
        bridge.start_after_listen(timeout=180)
        RAM = bridge.main_ram()
        print(f"conectado; RAM={RAM!r}")

        bridge.speed(args.speed)
        states = ROOT / "runs" / "states"
        states.mkdir(parents=True, exist_ok=True)
        if args.load:
            sp = states / f"{args.load}.State"
            if not sp.exists():
                print(f"savestate nao existe: {sp}")
                return 1
            bridge.loadstate(str(sp))
            bridge.frame_advance(2)
            print(f"savestate carregado: {sp.name} (boot pulado)")
        else:
            bridge.frame_advance(args.boot)

        seen: dict[str, int] = {}
        kept: list[Path] = []
        print(f"\n{'passo':>5} {'frame':>7} {'lp1':>6} {'lp2':>6} "
              f"{'menu':>5} {'mode':>5} {'opp':>4} {'turn':>4}  tela")
        # --press aceita um botao unico ("Cross") ou uma sequencia separada por
        # virgula ("Right,Right,Cross"); nesse caso cada passo usa um item.
        seq = [b.strip() for b in args.press.split(",") if b.strip()]
        if len(seq) > 1:
            args.steps = len(seq)
            print(f"sequencia de {len(seq)} botoes: {seq}")

        for step in range(args.steps):
            btn = seq[step] if len(seq) > 1 else seq[0]
            if btn.lower() != "none":
                bridge.press(btn, 3)
            bridge.frame_advance(args.frames)

            vals = {}
            for k, (addr, size) in ADDR.items():
                vals[k] = (bridge.read_u16(addr, RAM) if size == 2
                           else bridge.read_u8(addr, RAM))
            frame = int(bridge.command("FRAME 1"))

            tmp = outdir / f"s{step:03d}.png"
            bridge.screenshot(str(tmp))
            # espera o arquivo materializar
            for _ in range(40):
                if tmp.exists() and tmp.stat().st_size > 0:
                    break
                time.sleep(0.05)

            note = ""
            if tmp.exists():
                h = hashlib.md5(tmp.read_bytes()).hexdigest()
                if h in seen:
                    tmp.unlink()
                    note = f"= igual ao passo {seen[h]}"
                else:
                    seen[h] = step
                    kept.append(tmp)
                    note = "NOVA"
            print(f"{step:5} {frame:7} {vals['lp1']:6} {vals['lp2']:6} "
                  f"{vals['menu']:5} {vals['mode']:5} {vals['opp']:4} "
                  f"{vals['turn']:4}  {btn:8} {note}")

        if args.save:
            sp = states / f"{args.save}.State"
            bridge.savestate(str(sp))
            time.sleep(0.6)
            print(f"savestate salvo: {sp} "
                  f"({sp.stat().st_size if sp.exists() else 0} bytes)")

        sheet = contact_sheet(kept, outdir / "_folha.png")
        print(f"\ntelas distintas: {len(kept)}")
        if sheet:
            print("folha de contato:", sheet)
        return 0
    except BridgeError as exc:
        print("ERRO:", exc)
        return 1
    finally:
        bridge.close()


if __name__ == "__main__":
    raise SystemExit(main())
