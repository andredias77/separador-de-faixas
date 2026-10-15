"""Separa as músicas da pasta musicas/ em 6 faixas (técnica F: voz = média da voz do BS-Roformer-SW
e do BS-Roformer Viperx; depois o SW separa o resto a partir do instrumental)
(voz, bateria, baixo, guitarra, piano, outros).

Uso:  .venv\\Scripts\\python separar.py                  (pula músicas já separadas)
      .venv\\Scripts\\python separar.py --refazer        (separa tudo de novo)
      .venv\\Scripts\\python separar.py --so "Something"  (só as músicas cujo nome contém o texto)
Resultado: faixas/<música>/*.flac (24 bits) + faixas/index.json (lido pelo mixer)
"""
import json
import re
import shutil
import unicodedata
import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

RAIZ = Path(__file__).parent
MUSICAS = RAIZ / "musicas"
FAIXAS = RAIZ / "faixas"
MODELOS = RAIZ / "modelos"
TMP = FAIXAS / "_tmp_roformer"
MODELO = "BS-Roformer-SW.ckpt"                 # 6 faixas, usado no instrumental
MODELO_VOZ = "model_bs_roformer_ep_317_sdr_12.9755.ckpt"   # voz (BS-Roformer Viperx 1297), em média com a voz do SW
SOBREPOSICAO = 2                               # 8 soa um pouco melhor, mas é ~4x mais lento
SR = 44100
EXTENSOES = {".mp3", ".flac", ".wav", ".m4a", ".aac", ".ogg", ".webm", ".opus"}


FOLGA = 0.5  # entrada a -6 dB: nenhuma faixa chega ao limite em que o audio-separator reescalaria só ela


def preparar_entrada(arquivo: Path) -> Path:
    """Converte para WAV float32, 44,1 kHz, estéreo (mono vira estéreo duplicado), sem a capa, com pico em FOLGA."""
    wav = TMP / f"{arquivo.stem}.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(arquivo), "-vn", "-ar", str(SR), "-ac", "2",
                    "-c:a", "pcm_f32le", str(wav)], check=True)
    dados, _ = sf.read(wav, dtype="float32", always_2d=True)
    ganho = FOLGA / float(np.abs(dados).max())
    sf.write(wav, dados * ganho, SR, subtype="FLOAT")
    return wav, ganho


def titulo(arquivo: Path) -> str:
    """'A7 - While My Guitar Gently Weeps' -> 'While My Guitar Gently Weeps'"""
    t = re.sub(r"^[A-Z]?\d+\s*[-.]\s*", "", arquivo.stem)   # "A7 - x" e "A1. x"
    t = f"{t} (mono)" if "(mono)" in arquivo.parent.name else t   # não confunde com versões estéreo
    return f"{t} - {ROTULO}" if ROTULO else t                       # --rotulo "v2" cria uma versão ao lado da antiga


def simplificar(t: str) -> str:
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().lower()
    t = re.sub(r"['’]", "", t)   # "I'm" -> "im"
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def procurar(busca: str) -> list[Path]:
    todas = sorted(f for f in MUSICAS.rglob("*") if f.suffix.lower() in EXTENSOES)
    b = simplificar(busca)
    # todas as versões que contêm o texto; se houver mais de uma, quem chama precisa escolher
    return [f for f in todas if b in simplificar(titulo(f))]


def caminho_wsl(p: Path) -> str:
    """Caminho do Windows (C:/pasta/x) -> caminho no WSL (/mnt/c/pasta/x), para chamar scripts lá dentro."""
    p = Path(p).resolve()
    return f"/mnt/{p.drive[0].lower()}" + p.as_posix()[2:]


COLAB_SH = caminho_wsl(RAIZ / "avaliacao" / "colab.sh")


def liberar(sep=None) -> None:
    """Solta o modelo da RAM e da GPU logo depois de usar (evita acumular 3 modelos numa música)."""
    import gc
    if sep is not None:
        for attr in ("model_instance", "model"):
            if hasattr(sep, attr):
                setattr(sep, attr, None)
    del sep
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


def separar(arquivo: Path, refazer: bool) -> None:
    from audio_separator.separator import Separator

    destino = FAIXAS / titulo(arquivo)
    if not refazer and destino.exists() and any(destino.glob("*.flac")):
        print(f"[pulando] {arquivo.name} já foi separada")
        return
    print(f"[separando] {arquivo.name} ...", flush=True)
    TMP.mkdir(parents=True, exist_ok=True)
    wav, ganho = preparar_entrada(arquivo)
    mistura, _ = sf.read(wav, dtype="float32", always_2d=True)

    def rodar(modelo: str, entrada: Path, pasta: str) -> dict:
        saida = TMP / pasta
        sep = Separator(model_file_dir=str(MODELOS), output_dir=str(saida), output_format="WAV",
                        use_soundfile=True, normalization_threshold=1.0,
                        mdxc_params={"segment_size": 256, "override_model_segment_size": False,
                                     "batch_size": 1, "overlap": SOBREPOSICAO, "pitch_shift": 0})
        sep.load_model(modelo)
        r = {}
        for s in sep.separate(str(entrada)):
            p = Path(s) if Path(s).is_absolute() else saida / s
            nome = p.stem.split("(")[-1].split(")")[0].lower()   # "x_(Bass)_BS-Roformer-SW" -> "bass"
            r[nome] = sf.read(p, dtype="float32", always_2d=True)[0]
            p.unlink(missing_ok=True)   # o WAV intermediário já está na memória
        liberar(sep)
        return r

    # 1) voz = média(voz do SW, voz do Viperx)  2) SW separa o resto a partir do instrumental (mistura − voz)
    #    (avaliacao/: +1,4 dB na voz e menos vazamento do baixo que a versão anterior, em 50 trechos mono)
    print("  [1/3] voz (SW)...", flush=True)
    voz_sw = rodar(MODELO, wav, "voz_sw")["vocals"][: len(mistura)]
    print("  [2/3] voz (Viperx)...", flush=True)
    voz_vx = rodar(MODELO_VOZ, wav, "voz_vx")["vocals"][: len(mistura)]
    n_voz = min(len(voz_sw), len(voz_vx))
    voz = (voz_sw[:n_voz] + voz_vx[:n_voz]) / 2
    instr = TMP / "instrumental.wav"
    sf.write(instr, mistura[: len(voz)] - voz, SR, subtype="FLOAT")
    print("  [3/3] baixo, bateria, guitarra, piano, outros...", flush=True)
    faixas = rodar(MODELO, instr, "resto")
    faixas.pop("vocals", None)   # sobra de voz que o SW ainda achou fica fora (já está na faixa de voz)
    faixas["vocals"] = voz
    n = min(len(a) for a in faixas.values())

    if destino.exists():
        shutil.rmtree(destino)
    destino.mkdir(parents=True)
    for nome, dados in faixas.items():
        if float(np.abs(dados[:n]).max()) >= 1:
            print(f"  aviso: {nome} foi reescalada pelo audio-separator (equilíbrio pode ter mudado)")
    # volta ao volume original; se alguma faixa passar de 0 dBFS, baixa todas por igual (sem cortar, sem mudar o equilíbrio)
    pico = max(float(np.abs(d[:n]).max()) for d in faixas.values()) / ganho
    ajuste = 1 / ganho / max(1.0, pico / 0.99)
    if pico > 0.99:
        print(f"  todas as faixas baixadas {20 * np.log10(pico / 0.99):.1f} dB para não cortar picos")
    for nome, dados in faixas.items():
        sf.write(destino / f"{nome}.flac", dados[:n] * ajuste, SR, subtype="PCM_24")
    shutil.rmtree(TMP)
    print(f"[ok] {arquivo.name} → {destino}", flush=True)


def gerar_indice() -> None:
    musicas = []
    for pasta in sorted(p for p in FAIXAS.iterdir() if p.is_dir() and not p.name.startswith("_")):
        stems = sorted(f.stem for f in pasta.glob("*.flac"))
        if stems:
            musicas.append({"nome": pasta.name, "faixas": stems})
    (FAIXAS / "index.json").write_text(json.dumps(musicas, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ok] {len(musicas)} música(s) prontas no mixer")


ROTULO = ""

if __name__ == "__main__":
    ROTULO = sys.argv[sys.argv.index("--rotulo") + 1] if "--rotulo" in sys.argv else ""
    args = [a for a in sys.argv[1:] if not a.startswith("--") and a != ROTULO]
    refazer = "--refazer" in sys.argv
    MUSICAS.mkdir(exist_ok=True)
    FAIXAS.mkdir(exist_ok=True)
    if "--todas" in sys.argv:
        arquivos = sorted(f for f in MUSICAS.rglob("*") if f.suffix.lower() in EXTENSOES)
    elif args and "--exato" in sys.argv:   # nome do arquivo sem extensão (usado pelo modo --colab)
        arquivos = [f for f in MUSICAS.rglob("*") if f.suffix.lower() in EXTENSOES and f.stem == " ".join(args)]
    elif args:
        arquivos = procurar(" ".join(args))
        if len(arquivos) > 1:
            print("Mais de uma música combina, seja mais específico:")
            for f in arquivos:
                print(f"  {f.relative_to(MUSICAS)}")
            sys.exit(1)
    else:
        print(__doc__); sys.exit(1)
    if not arquivos:
        print("Nenhuma música encontrada com esse nome."); sys.exit(1)
    for a in arquivos:
        if "--colab" in sys.argv:   # separa na GPU T4 grátis do Colab (avaliacao/colab.sh, via WSL)
            rel = a.relative_to(MUSICAS).as_posix()
            env = dict(__import__("os").environ, MSYS_NO_PATHCONV="1")
            subprocess.run(["wsl.exe", "-d", "Ubuntu", "--", "bash", COLAB_SH,
                            "separar", rel, titulo(a), ROTULO], check=True, env=env)
        else:
            separar(a, refazer)
    gerar_indice()
