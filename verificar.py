"""Diz o que está pronto e o que falta para usar a mesa. Não instala nem baixa nada.

Uso:  python verificar.py          (qualquer Python 3.10+; usa só a biblioteca padrão)
Sai com código 0 quando está tudo pronto, 1 quando falta algo.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
VENV = RAIZ / ".venv"
PY_VENV = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
MODELOS = {"BS-Roformer-SW.ckpt": 699, "model_bs_roformer_ep_317_sdr_12.9755.ckpt": 639}   # MB aproximados


def rodar(cmd, timeout=60):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)


def checar() -> list[tuple[str, bool, str]]:
    itens = []
    ok_py = sys.version_info >= (3, 10)
    itens.append(("Python 3.10+", ok_py, f"{sys.version.split()[0]}" if ok_py else "instale o Python 3.12 (python.org)"))
    itens.append(("ffmpeg", bool(shutil.which("ffmpeg")), "no PATH" if shutil.which("ffmpeg") else
                  "instale (Windows: winget install Gyan.FFmpeg; Mac: brew install ffmpeg; Linux: apt install ffmpeg)"))
    cod, saida = rodar(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"])
    gpu = saida.splitlines()[0] if cod == 0 and saida else ""
    itens.append(("Placa NVIDIA (opcional)", True, gpu or "não encontrada: a separação roda na CPU, bem mais devagar"))
    itens.append(("Ambiente .venv", PY_VENV.exists(), str(VENV) if PY_VENV.exists() else "rode o instalador"))
    if PY_VENV.exists():
        teste = ("import json,torch,soundfile,numpy;import audio_separator;"
                 "print(json.dumps({'torch':torch.__version__,'cuda':torch.cuda.is_available()}))")
        cod, saida = rodar([str(PY_VENV), "-c", teste], timeout=120)
        try:
            info = json.loads(saida.splitlines()[-1])
            itens.append(("Bibliotecas (PyTorch, audio-separator)", True,
                          f"torch {info['torch']} · {'GPU (CUDA)' if info['cuda'] else 'CPU'}"))
            if gpu and not info["cuda"]:
                itens.append(("PyTorch com CUDA", False, "há placa NVIDIA, mas o PyTorch instalado é só CPU: rode o instalador de novo"))
        except Exception:
            itens.append(("Bibliotecas (PyTorch, audio-separator)", False, "faltando ou quebradas: rode o instalador"))
    for nome, mb in MODELOS.items():
        f = RAIZ / "modelos" / nome
        itens.append((f"Modelo {nome}", f.exists() and f.stat().st_size > mb * 0.9e6,
                      f"{f.stat().st_size / 1e6:.0f} MB" if f.exists() else f"falta (~{mb} MB; o instalador baixa)"))
    return itens


if __name__ == "__main__":
    itens = checar()
    largura = max(len(n) for n, _, _ in itens)
    for nome, ok, nota in itens:
        print(f"  {'✓' if ok else '✗'}  {nome.ljust(largura)}  {nota}")
    falta = [n for n, ok, _ in itens if not ok]
    if falta:
        print("\nFalta: " + ", ".join(falta) + ".\nPróximo passo: rode  instalar.bat  (Windows)  ou  python instalar.py")
        sys.exit(1)
    print("\nTudo pronto. Abra a mesa com  iniciar.bat  (ou  .venv/Scripts/python mixer.py)")
