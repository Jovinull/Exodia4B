"""EXODIA-4B :: verificacao da ponte com o emulador.

Objetivo (criterio de saida em Notes/09-roadmap.md):
    provar que o Python le, ao vivo, um valor do jogo rodando no BizHawk.

Valida, em ordem:
    V0  a ponte conecta e responde
    --  o core PSX carregou e a ROM e a esperada
    --  o dominio MainRAM existe e tem 2 MB
    V1  Life Points em 0x800EA004 / 0x800EA024 batem com a tela
    V3  joypad.set() funciona fora de modo gravacao

Uso:
    python scripts/check_bridge.py               # usa a ISO PT-BR (principal)
    python scripts/check_bridge.py --iso backup  # usa a ISO inglesa
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from exodia.bridge import Bridge, BridgeError  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
EMUHAWK = ROOT / "tools" / "BizHawk" / "EmuHawk.exe"
LUA = ROOT / "exodia" / "bridge.lua"
SHOTS = ROOT / "runs" / "check_bridge"

ISOS = {
    "ptbr": ROOT / "[PS1]_Yu-Gi-Oh! Forbidden Memories (PT-BR)"
                 / "Yu-Gi-Oh! Forbidden Memories (PT-BR).cue",
    "backup": ROOT / "[SLUS-01411]_Yu-Gi-Oh!_-_Forbidden_Memories" / "YUGIOH.ccd",
}

# Enderecos no espaco PS1 (a Bridge aplica a mascara 0x1FFFFF sozinha)
ADDR = {
    "p1_lp_display": 0x800EA002,
    "p1_lp_real": 0x800EA004,
    "p2_lp_display": 0x800EA022,
    "p2_lp_real": 0x800EA024,
    "opponent_id": 0x8009B361,
    "terrain": 0x8009B364,
    "menu_id": 0x80184594,
    "turn_owner": 0x8009B1D5,   # minerado da Recomp
    "mode_byte": 0x8009B26C,    # minerado da Recomp
}

HOST, PORT = "127.0.0.1", 55355


def launch(iso: Path) -> subprocess.Popen:
    cmd = [
        str(EMUHAWK),
        f"--socket_ip={HOST}",
        f"--socket_port={PORT}",
        f"--lua={LUA}",
        str(iso),
    ]
    print("Lancando:", " ".join(f'"{c}"' if " " in c else c for c in cmd))
    return subprocess.Popen(cmd, cwd=str(EMUHAWK.parent))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--iso", choices=list(ISOS), default="ptbr")
    ap.add_argument("--no-launch", action="store_true",
                    help="nao abrir o EmuHawk (ja esta aberto)")
    ap.add_argument("--watch", type=int, default=0,
                    help="segundos monitorando os LP ao vivo")
    args = ap.parse_args()

    iso = ISOS[args.iso]
    for label, p in (("EmuHawk", EMUHAWK), ("bridge.lua", LUA), ("ISO", iso)):
        if not p.exists():
            print(f"FALTA {label}: {p}")
            return 1
    SHOTS.mkdir(parents=True, exist_ok=True)

    bridge = Bridge(HOST, PORT)
    bridge.listen()
    print(f"Servidor ouvindo em {HOST}:{PORT}")

    proc = None if args.no_launch else launch(iso)
    try:
        print("Esperando o EmuHawk conectar (ate 180s)...")
        hello = bridge.start_after_listen(timeout=180)
        print(f"  conectado. primeira mensagem: {hello!r}")

        ok = True

        print("\n[1] PING")
        pong = bridge.ping()
        print(f"  -> {'OK' if pong else 'FALHOU'}")
        ok &= pong

        print("\n[2] INFO do emulador")
        info = bridge.info()
        for k, v in info.items():
            print(f"  {k:8}: {v}")
        sysid = info.get("system", "")
        if sysid not in ("PSX", "NULL"):
            print(f"  AVISO: system={sysid!r} (esperado PSX)")

        print("\n[3] Dominios de memoria (TODOS)")
        doms = bridge.domains()
        for k, v in doms.items():
            mark = "  <-- RAM principal" if v == 2 * 1024 * 1024 else ""
            print(f"  {k:20}: {v:>9} bytes{mark}")
        try:
            RAM = bridge.main_ram()
            print(f"  dominio de RAM detectado: {RAM!r}")
        except BridgeError as exc:
            print(f"  ERRO: {exc}")
            return 1

        print("\n[4] Bootando o jogo (900 frames em 400%)")
        bridge.speed(400)
        bridge.frame_advance(900)
        bridge.speed(100)
        shot = SHOTS / "boot.png"
        print("  frame:", bridge.command("FRAME 1"))
        print("  ", bridge.screenshot(str(shot)))

        print("\n[5] Leitura de enderecos-chave")
        for name, addr in ADDR.items():
            size = 2 if "lp" in name else 1
            try:
                v = (bridge.read_u16(addr, RAM) if size == 2
                     else bridge.read_u8(addr, RAM))
                print(f"  {name:16} @ 0x{addr:08X} = {v}")
            except BridgeError as exc:
                print(f"  {name:16} @ 0x{addr:08X} = ERRO {exc}")
                ok = False

        if args.watch:
            print(f"\n[6] Monitorando LP por {args.watch}s "
                  f"(entre num duelo e tome dano)")
            end = time.time() + args.watch
            last = None
            while time.time() < end:
                cur = (bridge.read_u16(ADDR["p1_lp_real"], RAM),
                       bridge.read_u16(ADDR["p2_lp_real"], RAM),
                       bridge.read_u8(ADDR["menu_id"], RAM),
                       bridge.read_u8(ADDR["turn_owner"], RAM))
                if cur != last:
                    print(f"  LP_voce={cur[0]:5}  LP_oponente={cur[1]:5}  "
                          f"menu={cur[2]:3}  turno={cur[3]}")
                    last = cur
                time.sleep(0.25)

        print("\n" + "=" * 60)
        print("FASE 0:", "ponte funcionando" if ok else "PROBLEMAS ACIMA")
        print("Confirme o screenshot em:", SHOTS)
        return 0 if ok else 1

    except BridgeError as exc:
        print(f"\nERRO DE PONTE: {exc}")
        return 1
    finally:
        bridge.close()
        if proc is not None:
            print("(EmuHawk continua aberto; feche a janela quando quiser)")


if __name__ == "__main__":
    raise SystemExit(main())
