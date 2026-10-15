"""Separa várias músicas em sequência, sem janela (lançado fora da sessão). Uso: pythonw ferramentas/lote.py "busca 1" "busca 2" ..."""
import os
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent   # raiz do projeto
with open(RAIZ / "dados" / "registros" / "lote.log", "a", encoding="utf-8") as log:
    for busca in sys.argv[1:]:
        log.write(f"== {busca}\n"); log.flush()
        subprocess.run([str(RAIZ / ".venv" / "Scripts" / "python.exe"), str(RAIZ / "separador" / "separar.py"), busca], cwd=RAIZ, stdout=log, stderr=subprocess.STDOUT,
                       env=dict(os.environ, HF_HUB_DISABLE_SYMLINKS_WARNING="1"), creationflags=0x08000000)
    log.write("== fim\n")
