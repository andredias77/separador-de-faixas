"""Separa todas as músicas da biblioteca em ordem de álbum, dividindo o trabalho entre o PC e o Colab.

Cada "trabalhador" percorre a lista (o Colab do começo, o PC do fim; Mono Masters por último) e reserva a próxima música livre criando um arquivo em
faixas/_reservas/ (criação exclusiva: dois trabalhadores nunca pegam a mesma). Músicas já separadas
(pasta em faixas/ com as 6 faixas) são puladas.

Uso:  .venv\\Scripts\\python ferramentas/fila.py --pc        (trabalhador na GPU local)
      .venv\\Scripts\\python ferramentas/fila.py --colab     (trabalhador na T4 grátis do Colab, via WSL)
      .venv\\Scripts\\python ferramentas/fila.py --lista     (mostra a ordem e o que falta)
"""
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # raiz do projeto (separar.py)
import separar as S

# ordem de lançamento (Sgt. Pepper saiu antes de Magical Mystery Tour)
ORDEM_ALBUNS = ["Please Please Me", "With the Beatles", "A Hard Day's Night", "Beatles for Sale", "Help",
                "Rubber Soul", "Revolver", "Sgt Pepper's", "Magical Mystery Tour", "The Beatles", "Abbey Road", "Mono Masters"]
RESERVAS = S.FAIXAS / "_reservas"


def posicao_album(pasta: str) -> int:
    for i, nome in enumerate(ORDEM_ALBUNS):
        if nome.lower() in pasta.lower():
            return i
    return len(ORDEM_ALBUNS)   # avulsas e outros por último


def ordem_faixa(nome: str):
    m = re.match(r"([A-Z]?)(\d+)", nome)   # "B10 - x" -> ("B", 10): ordem natural de lado e faixa
    return (m.group(1), int(m.group(2))) if m else ("~", 0)


def todas(de_tras: bool = False) -> list:
    """Ordem de álbum; com de_tras=True os álbuns vêm do último para o primeiro. Mono Masters sempre por último.
    O Colab (rápido) vai do começo para frente e o PC (lento) do fim para trás: os dois se encontram no meio."""
    arqs = [f for f in S.MUSICAS.rglob("*") if f.suffix.lower() in S.EXTENSOES and f.parent != S.MUSICAS / "Avulsas"]
    arqs.sort(key=lambda f: (posicao_album(f.parent.name), f.parent.name, ordem_faixa(f.name)))
    prioridade = [f for f in arqs if "Abbey Road" in f.parent.name]   # pedido do usuário: Abbey Road antes de tudo
    albuns = [f for f in arqs if "Mono Masters" not in f.parent.name and f not in prioridade]
    masters = [f for f in arqs if "Mono Masters" in f.parent.name]
    if de_tras:
        return prioridade[::-1] + albuns[::-1] + masters
    return prioridade + albuns + masters


def pronta(f) -> bool:
    d = S.FAIXAS / S.titulo(f)
    return d.exists() and len(list(d.glob("*.flac"))) >= 6


def reservar(f) -> bool:
    RESERVAS.mkdir(parents=True, exist_ok=True)
    try:
        os.close(os.open(RESERVAS / (S.titulo(f) + ".txt"), os.O_CREAT | os.O_EXCL | os.O_WRONLY))
        return True
    except FileExistsError:
        return False


def trabalhar(onde: str) -> None:
    feitas = 0
    for f in todas(de_tras=(onde == "pc")):
        if pronta(f) or not reservar(f):
            continue
        print(f"[{onde}] {f.parent.name} / {f.name}", flush=True)
        try:
            if onde == "pc":
                S.separar(f, refazer=False)
            else:
                rel = f.relative_to(S.MUSICAS).as_posix()
                for tentativa in (1, 2):   # o Colab às vezes trava num comando: tempo limite e mais uma tentativa
                    try:
                        subprocess.run(["wsl.exe", "-d", "Ubuntu", "--", "bash", S.COLAB_SH,
                                        "separar", rel, S.titulo(f), ""], check=True, env=dict(os.environ, MSYS_NO_PATHCONV="1"),
                                       stdout=subprocess.DEVNULL, timeout=15 * 60, creationflags=0x08000000)   # sem janela
                        break
                    except subprocess.TimeoutExpired:
                        print(f"[colab] tempo esgotado em {f.name} (tentativa {tentativa})", flush=True)
                        if tentativa == 2:
                            raise
            if not pronta(f):
                raise RuntimeError("as 6 faixas não apareceram")
            S.gerar_indice()   # a música já aparece na mesa
            feitas += 1
        except Exception as e:   # libera a reserva para o outro trabalhador tentar
            print(f"[{onde}] ERRO em {f.name}: {e}", flush=True)
            (RESERVAS / (S.titulo(f) + ".txt")).unlink(missing_ok=True)
            if onde == "colab":
                print("[colab] parando (sessão caiu ou cota acabou?) — o PC continua", flush=True)
                break
    print(f"[{onde}] fim: {feitas} música(s) separada(s)", flush=True)


if __name__ == "__main__":
    if "--lista" in sys.argv:
        for f in todas():
            print(("ok  " if pronta(f) else "    ") + f"{f.parent.name} / {f.name}")
    elif "--pc" in sys.argv:
        trabalhar("pc")
    elif "--colab" in sys.argv:
        trabalhar("colab")
    else:
        print(__doc__)
