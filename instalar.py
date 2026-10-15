"""Instalador: mostra o que falta (com tamanhos), pede confirmação e instala tudo DENTRO da pasta do projeto.

Uso:  python instalar.py          (pergunta antes de baixar qualquer coisa)
      python instalar.py --sim    (não pergunta; use só depois que a pessoa já concordou)

O que pode ser baixado:
  - PyTorch: com CUDA (~2,5 GB) se houver placa NVIDIA; com DirectML (~250 MB) se houver placa AMD ou Intel
    no Windows; senão a versão só CPU (~200 MB)
  - audio-separator e bibliotecas de áudio (~300 MB)
  - 2 modelos de separação (~1,3 GB) em dados/modelos/
Tudo fica em .venv/ e dados/; para desinstalar, apague a pasta do projeto.
Python e ffmpeg são do sistema: o instalador só avisa se faltarem.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import verificar as V

RAIZ = V.RAIZ
TORCH_CUDA = ["torch==2.5.1", "torchaudio==2.5.1", "--index-url", "https://download.pytorch.org/whl/cu121"]
TORCH_CPU = ["torch==2.5.1", "torchaudio==2.5.1", "--index-url", "https://download.pytorch.org/whl/cpu"]
TORCH_DML = ["torch-directml", "torchaudio==2.4.1"]   # torch-directml exige torch 2.4.1 (vem junto)


def acelerador() -> str:
    """'cuda' (placa NVIDIA), 'dml' (placa AMD/Intel no Windows, via DirectML) ou 'cpu'."""
    if V.rodar(["nvidia-smi", "-L"])[0] == 0:
        return "cuda"
    if os.name == "nt" and V.placas_amd_intel():
        return "dml"
    return "cpu"


DESCRICAO = {"cuda": ("com CUDA (placa NVIDIA encontrada)", "~2,5 GB"),
             "dml": ("com DirectML (placa AMD/Intel encontrada)", "~250 MB"),
             "cpu": ("só CPU (nenhuma placa de vídeo compatível)", "~200 MB")}


def plano() -> list[tuple[str, str]]:
    passos = []
    if not V.PY_VENV.exists():
        passos.append(("criar o ambiente .venv", "~20 MB"))
    o_que, tamanho = DESCRICAO[acelerador()]
    passos.append((f"PyTorch {o_que}", tamanho))
    passos.append(("audio-separator e bibliotecas de áudio", "~300 MB"))
    falta = [n for n, mb in V.MODELOS.items() if not (RAIZ / "dados" / "modelos" / n).exists()]
    if falta:
        passos.append((f"{len(falta)} modelo(s) de separação em dados/modelos/", f"~{sum(V.MODELOS[n] for n in falta) / 1000:.1f} GB"))
    return passos


def pip(*args) -> None:
    subprocess.run([str(V.PY_VENV), "-m", "pip", "install", "--disable-pip-version-check", *args], check=True)


def main() -> None:
    if sys.version_info < (3, 10):
        sys.exit("É preciso Python 3.10 ou mais novo (recomendado: 3.12, em python.org).")
    if not shutil.which("ffmpeg"):
        print("Aviso: o ffmpeg não foi encontrado. Instale antes de separar músicas:\n"
              "  Windows: winget install Gyan.FFmpeg   ·   Mac: brew install ffmpeg   ·   Linux: sudo apt install ffmpeg\n")
    passos = plano()
    print("Vou instalar, tudo dentro de", RAIZ)
    for o_que, tamanho in passos:
        print(f"  - {o_que}  ({tamanho})")
    if "--sim" not in sys.argv and input("\nContinuar? (s/n) ").strip().lower() not in ("s", "sim", "y", "yes"):
        sys.exit("Nada foi instalado.")

    acel = acelerador()
    if not V.PY_VENV.exists():
        print("\n[1/4] criando .venv …"); subprocess.run([sys.executable, "-m", "venv", str(RAIZ / ".venv")], check=True)
    print("[2/4] PyTorch …"); pip(*{"cuda": TORCH_CUDA, "dml": TORCH_DML, "cpu": TORCH_CPU}[acel])
    print("[3/4] audio-separator e bibliotecas …")
    travas = ["-c", str(RAIZ / "restricoes.txt")] if acel != "dml" else []   # as travas fixam torch 2.5.1
    pip(*travas, f"audio-separator[{'gpu' if acel == 'cuda' else 'cpu'}]==0.47.0", "soundfile", "numpy", "audioread")
    print("[4/4] modelos de separação (só os que faltam) …")
    baixar = ("from audio_separator.separator import Separator\n"
              f"for m in {list(V.MODELOS)!r}:\n"
              "    s = Separator(model_file_dir='dados/modelos', log_level=30); s.load_model(m); print('  ok', m)\n")
    subprocess.run([str(V.PY_VENV), "-c", baixar], cwd=RAIZ, check=True)
    print("\nPronto. Conferindo:\n")
    os.execv(str(V.PY_VENV), [str(V.PY_VENV), str(RAIZ / "verificar.py")])


if __name__ == "__main__":
    main()
