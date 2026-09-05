"""Lista os nomes EXATOS de botao aceitos pelo core atual do BizHawk."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from exodia.bridge import Bridge  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
EMUHAWK = ROOT / "tools" / "BizHawk" / "EmuHawk.exe"
LUA = ROOT / "exodia" / "bridge.lua"
ISO = (ROOT / "[PS1]_Yu-Gi-Oh! Forbidden Memories (PT-BR)"
       / "Yu-Gi-Oh! Forbidden Memories (PT-BR).cue")
HOST, PORT = "127.0.0.1", 55355

b = Bridge(HOST, PORT)
b.listen()
subprocess.Popen(
    [str(EMUHAWK), f"--socket_ip={HOST}", f"--socket_port={PORT}",
     f"--lua={LUA}", str(ISO)],
    cwd=str(EMUHAWK.parent),
)
b.start_after_listen(timeout=180)
print("botoes aceitos por joypad.set neste core:\n")
for name in b.command("BUTTONS").split(","):
    print("  ", repr(name))
b.close()
