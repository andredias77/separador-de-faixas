"""Avaliação objetiva da separação de faixas no MUSDB18 de amostra (trechos de 7 s, divisão "test").

Para cada trecho, gera a mistura em duas condições — estéreo (original) e mono ((L+R)/2 duplicado) —
e roda quatro técnicas:
  E          técnica de produção (separar.py): voz com MelBand Roformer Kim, SW no instrumental
  SW         BS-Roformer-SW direto na mistura (voz dele mesmo)
  ft         Demucs htdemucs_ft (--shifts 2) na mistura
  E+medio    igual à E, mas baixo = média(baixo da E, baixo do htdemucs_ft rodado no instrumental);
             a diferença vai para "other" (como no teste_baixo.py, versão 4)
Métrica: SDR global por faixa (nSDR do desafio MDX) e vazamento do baixo (ver vazamento_baixo).

Uso:  .venv\\Scripts\\python avaliacao\\avaliar.py                (todas as faixas, pula o que já está no cache)
      .venv\\Scripts\\python avaliacao\\avaliar.py --faixas 1     (só as N primeiras)
      .venv\\Scripts\\python avaliacao\\avaliar.py --so-relatorio (não usa a GPU; só recalcula CSV e relatório)
Resultado: avaliacao/resultados.csv + avaliacao/RELATORIO.md
"""
import csv
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parent
sys.path.insert(0, str(RAIZ))
from separar import MODELO, MODELO_VOZ, SOBREPOSICAO, MODELOS, SR, FOLGA  # noqa: E402

DADOS = AQUI / "dados"
TMP = AQUI / "_tmp"
CACHE = AQUI / "cache"
TEMPOS = CACHE / "tempos_gpu.json"
PYTHON = RAIZ / ".venv" / "Scripts" / "python.exe"

CONDICOES = ["estereo", "mono"]
TECNICAS = ["E", "SW", "ft", "E+medio"]
STEMS = ["vocals", "drums", "bass", "other"]
EPS = 1e-7                 # mesmo ε do nSDR do MDX
LIMIAR_SILENCIO = -40      # dB: stem de referência mais de 40 dB abaixo da mistura é considerado silencioso
BANDA_BAIXO = (40, 300)    # Hz
DURACAO_MIN = 12           # s: os Roformers recebem o trecho completado com silêncio até aqui (ver roformer())


# ---------------------------------------------------------------- dados

def carregar_faixas(limite: int | None) -> list[dict]:
    import musdb
    db = musdb.DB(root=str(DADOS), download=True, subsets="test")
    faixas = []
    for i, t in enumerate(db.tracks[:limite] if limite else db.tracks):
        refs = {s: t.targets[s].audio.astype(np.float32) for s in STEMS}
        faixas.append({"id": f"t{i:02d}", "nome": t.name, "mistura": t.audio.astype(np.float32), "refs": refs})
    return faixas


def condicao(x: np.ndarray, cond: str) -> np.ndarray:
    if cond == "mono":
        m = x.mean(axis=1, keepdims=True)
        return np.repeat(m, 2, axis=1)
    return x


def chave(f: dict, cond: str) -> str:
    return f"{f['id']}_{cond}"   # nome seguro para arquivo (os nomes do MUSDB têm parênteses)


def preparar(f: dict, cond: str) -> tuple[Path, np.ndarray, float]:
    """Mistura da condição, com pico em FOLGA (como o separar.py faz), gravada em _tmp/mist/."""
    x = condicao(f["mistura"], cond)
    ganho = FOLGA / float(np.abs(x).max())
    wav = TMP / "mist" / f"{chave(f, cond)}.wav"
    wav.parent.mkdir(parents=True, exist_ok=True)
    if not wav.exists():
        sf.write(wav, x * ganho, SR, subtype="FLOAT")
    return wav, x * ganho, ganho


# ---------------------------------------------------------------- cache (por faixa × condição × técnica)

def pasta_cache(f: dict, cond: str, tec: str) -> Path:
    return CACHE / tec / cond / f["id"]


def no_cache(f: dict, cond: str, tec: str) -> bool:
    p = pasta_cache(f, cond, tec)
    return all((p / f"{s}.flac").exists() for s in STEMS)


def salvar_cache(f: dict, cond: str, tec: str, stems: dict, n: int) -> None:
    """Grava as 4 faixas no domínio da entrada (pico 0,5), FLAC 24 bits, ajustadas ao tamanho n."""
    p = pasta_cache(f, cond, tec)
    p.mkdir(parents=True, exist_ok=True)
    for s in STEMS:
        a = ajustar(stems[s], n)
        if float(np.abs(a).max()) >= 1:
            print(f"  aviso: {tec}/{cond}/{f['id']}/{s} passou de 1 e foi cortada no cache")
        sf.write(p / f"{s}.flac", np.clip(a, -1, 1), SR, subtype="PCM_24")


def ler_cache(f: dict, cond: str, tec: str) -> dict:
    p = pasta_cache(f, cond, tec)
    return {s: sf.read(p / f"{s}.flac", dtype="float32", always_2d=True)[0] for s in STEMS}


def ajustar(a: np.ndarray, n: int) -> np.ndarray:
    """Corta ou completa com zeros até n amostras."""
    if len(a) >= n:
        return a[:n]
    return np.concatenate([a, np.zeros((n - len(a), a.shape[1]), dtype=a.dtype)])


def para_4(faixas: dict) -> dict:
    """6 faixas do SW -> 4 do MUSDB (guitar + piano + other viram other)."""
    outros = sum(faixas[k] for k in ("guitar", "piano", "other") if k in faixas)
    return {"vocals": faixas.get("vocals"), "drums": faixas["drums"], "bass": faixas["bass"], "other": outros}


# ---------------------------------------------------------------- GPU

def gpu_ocupada() -> str | None:
    if (RAIZ / "faixas" / "_tmp_roformer").exists():
        return "faixas/_tmp_roformer existe (separar.py rodando)"
    if shutil.which("powershell") is None:   # fora do Windows (ex.: Colab) não há fila de músicas
        return None
    r = subprocess.run(["powershell", "-NoProfile", "-c",
                        "Get-CimInstance Win32_Process -Filter \"name='python.exe'\" | "
                        "Where-Object { $_.CommandLine -match 'separar.py|teste_baixo.py' } | "
                        "ForEach-Object { $_.CommandLine }"], capture_output=True, text=True)
    return r.stdout.strip() or None


def checar_gpu() -> None:
    """Para (o cache do que já terminou fica) se a fila de separação do usuário estiver usando a GPU."""
    ocup = gpu_ocupada()
    if ocup:
        print(f"[parado] GPU ocupada: {ocup}")
        sys.exit(2)


def cronometrar(etapa: str, inicio: float, itens: int) -> None:
    t = json.loads(TEMPOS.read_text(encoding="utf-8")) if TEMPOS.exists() else {}
    seg = time.time() - inicio
    ant = t.get(etapa, {"segundos": 0, "itens": 0})
    t[etapa] = {"segundos": round(ant["segundos"] + seg, 1), "itens": ant["itens"] + itens}
    TEMPOS.parent.mkdir(parents=True, exist_ok=True)
    TEMPOS.write_text(json.dumps(t, indent=2), encoding="utf-8")
    print(f"  [{etapa}] {itens} item(ns) em {seg:.0f} s", flush=True)


def roformer(modelo: str, entradas: dict[str, Path], pasta: str) -> dict[str, dict]:
    """Roda um modelo do audio-separator (mesmos parâmetros do separar.py) em vários arquivos,
    carregando o modelo uma vez só. Devolve {chave: {stem: áudio}}."""
    from audio_separator.separator import Separator
    saida = TMP / pasta
    saida.mkdir(parents=True, exist_ok=True)
    sep = Separator(model_file_dir=str(MODELOS), output_dir=str(saida), output_format="WAV",
                    use_soundfile=True, normalization_threshold=1.0, log_level=30,
                    mdxc_params={"segment_size": 256, "override_model_segment_size": False,
                                 "batch_size": 1, "overlap": SOBREPOSICAO, "pitch_shift": 0})
    sep.load_model(modelo)
    res = {}
    for k, wav in entradas.items():
        if (RAIZ / "faixas" / "_tmp_roformer").exists():   # a fila do usuário começou: sai já (cache por bloco)
            print("[parado] GPU ocupada no meio da etapa: faixas/_tmp_roformer apareceu")
            sys.exit(2)
        # Com menos de 10 s o audio-separator troca sozinho o segmento do modelo por um bem menor
        # (SW: 9,3 s -> 3 s), o que não acontece numa música inteira. Completa com silêncio até
        # DURACAO_MIN para rodar exatamente como na produção, e corta a saída depois.
        x = sf.read(wav, dtype="float32", always_2d=True)[0]
        pad = TMP / "pad" / f"{k}.wav"
        pad.parent.mkdir(parents=True, exist_ok=True)
        sf.write(pad, ajustar(x, max(len(x), int(DURACAO_MIN * SR))), SR, subtype="FLOAT")
        r = {}
        for s in sep.separate(str(pad)):
            p = Path(s) if Path(s).is_absolute() else saida / s
            nome = p.stem.split("(")[-1].split(")")[0].lower()   # "t00_estereo_(Bass)_BS-Roformer-SW" -> "bass"
            r[nome] = sf.read(p, dtype="float32", always_2d=True)[0][: len(x)]
            p.unlink()
        res[k] = r
    return res


def demucs_ft(entradas: dict[str, Path], pasta: str) -> dict[str, dict]:
    """htdemucs_ft (--shifts 2) numa chamada só para todos os arquivos."""
    saida = TMP / pasta
    shutil.rmtree(saida, ignore_errors=True)
    subprocess.run([str(PYTHON), "-m", "demucs", "-n", "htdemucs_ft", "--shifts", "2", "--float32",
                    "-o", str(saida), "--filename", "{track}/{stem}.{ext}", *map(str, entradas.values())],
                   check=True, capture_output=True)
    res = {}
    for k, wav in entradas.items():
        d = saida / "htdemucs_ft" / wav.stem
        res[k] = {s: sf.read(d / f"{s}.wav", dtype="float32", always_2d=True)[0] for s in STEMS}
    shutil.rmtree(saida, ignore_errors=True)
    return res


def processar(faixas: list[dict]) -> None:
    pend = {tec: [(f, c) for f in faixas for c in CONDICOES if not no_cache(f, c, tec)] for tec in TECNICAS}
    if not any(pend.values()):
        print("[cache] tudo já processado")
        return
    checar_gpu()
    for tec, p in pend.items():
        print(f"[pendente] {tec}: {len(p)}")
    mist = {}
    for f in faixas:
        for c in CONDICOES:
            mist[chave(f, c)] = preparar(f, c)

    # E: voz com o Kim, depois SW no instrumental (mistura − voz); o "vocals" do SW é descartado
    if pend["E"]:
        t0 = time.time()
        voz = roformer(MODELO_VOZ, {chave(f, c): mist[chave(f, c)][0] for f, c in pend["E"]}, "voz")
        cronometrar("E: Kim (voz)", t0, len(pend["E"]))
        instr = {}
        for f, c in pend["E"]:
            k = chave(f, c)
            x = mist[k][1]
            v = voz[k]["vocals"][: len(x)]
            instr[k] = TMP / "instr" / f"{k}.wav"
            instr[k].parent.mkdir(parents=True, exist_ok=True)
            sf.write(instr[k], x[: len(v)] - v, SR, subtype="FLOAT")
        t0 = time.time()
        resto = roformer(MODELO, instr, "resto")
        cronometrar("E: SW (instrumental)", t0, len(pend["E"]))
        for f, c in pend["E"]:
            k = chave(f, c)
            r = dict(resto[k]); r.pop("vocals", None); r["vocals"] = voz[k]["vocals"]
            salvar_cache(f, c, "E", para_4(r), len(mist[k][1]))

    if pend["SW"]:
        checar_gpu()
        t0 = time.time()
        sw = roformer(MODELO, {chave(f, c): mist[chave(f, c)][0] for f, c in pend["SW"]}, "sw")
        cronometrar("SW direto", t0, len(pend["SW"]))
        for f, c in pend["SW"]:
            salvar_cache(f, c, "SW", para_4(sw[chave(f, c)]), len(mist[chave(f, c)][1]))

    if pend["ft"]:
        checar_gpu()
        t0 = time.time()
        ft = demucs_ft({chave(f, c): mist[chave(f, c)][0] for f, c in pend["ft"]}, "ft")
        cronometrar("Demucs ft (mistura)", t0, len(pend["ft"]))
        for f, c in pend["ft"]:
            salvar_cache(f, c, "ft", ft[chave(f, c)], len(mist[chave(f, c)][1]))

    # E+medio: usa a E do cache; instrumental = mistura − voz da E; ft roda no instrumental
    if pend["E+medio"]:
        instr, base = {}, {}
        for f, c in pend["E+medio"]:
            k = chave(f, c)
            base[k] = ler_cache(f, c, "E")
            instr[k] = TMP / "instr_ft" / f"{k}.wav"
            instr[k].parent.mkdir(parents=True, exist_ok=True)
            sf.write(instr[k], mist[k][1] - base[k]["vocals"], SR, subtype="FLOAT")
        checar_gpu()
        t0 = time.time()
        ft = demucs_ft(instr, "ft_instr")
        cronometrar("Demucs ft (instrumental, p/ E+medio)", t0, len(pend["E+medio"]))
        for f, c in pend["E+medio"]:
            k = chave(f, c)
            b = base[k]
            n = len(b["bass"])
            baixo = (b["bass"] + ajustar(ft[k]["bass"], n)) / 2
            r = dict(b, bass=baixo, other=b["other"] - (baixo - b["bass"]))
            salvar_cache(f, c, "E+medio", r, n)
    shutil.rmtree(TMP, ignore_errors=True)


# ---------------------------------------------------------------- métricas

def sdr(ref: np.ndarray, est: np.ndarray) -> float:
    """nSDR do MDX: 10·log10(Σs² / Σ(s−ŝ)²), sobre todo o trecho e os dois canais."""
    return float(10 * np.log10((np.sum(ref ** 2) + EPS) / (np.sum((ref - est) ** 2) + EPS)))


def banda(x: np.ndarray, lo: float, hi: float) -> np.ndarray:
    """Filtro passa-faixa ideal (FFT do trecho inteiro, por canal)."""
    X = np.fft.rfft(x, axis=0)
    fr = np.fft.rfftfreq(len(x), 1 / SR)
    X[(fr < lo) | (fr > hi)] = 0
    return np.fft.irfft(X, n=len(x), axis=0)


def vazamento_baixo(refs: dict, est: dict) -> dict:
    """Quanto do baixo verdadeiro (só 40–300 Hz) foi parar em cada faixa estimada.

    Projeção do erro de cada faixa no baixo: fração_k = <b, ŝ_k − s_k> / <b, b>, com tudo filtrado em
    40–300 Hz (b = baixo verdadeiro, s_k = faixa verdadeira k). Projetar o erro, e não ŝ_k, desconta o que
    a faixa k já tem de parecido com o baixo por natureza (guitarra dobrando a linha, bumbo junto): com a
    separação perfeita todas as frações dão 0. "vaz_baixo" é a soma nas faixas que não são o baixo (voz,
    bateria, outros/guitarra/piano); "baixo_capturado" = <b, ŝ_baixo>/<b, b> (ideal 1)."""
    b = banda(refs["bass"], *BANDA_BAIXO)
    e = float(np.sum(b * b)) + EPS
    fr = {s: float(np.sum(b * banda(est[s] - refs[s], *BANDA_BAIXO))) / e for s in STEMS}
    return {"baixo_capturado": 1 + fr["bass"], "vaz_baixo": sum(fr[s] for s in STEMS if s != "bass"),
            "baixo_em_vocals": fr["vocals"], "baixo_em_drums": fr["drums"], "baixo_em_other": fr["other"]}


def avaliar(faixas: list[dict]) -> list[dict]:
    linhas = []
    for f in faixas:
        for c in CONDICOES:
            x = condicao(f["mistura"], c)
            ganho = FOLGA / float(np.abs(x).max())
            e_mist = float(np.sum(x ** 2))
            refs = {s: condicao(f["refs"][s], c) for s in STEMS}
            for tec in TECNICAS:
                if not no_cache(f, c, tec):
                    continue
                est = {s: ajustar(a, len(x)) / ganho for s, a in ler_cache(f, c, tec).items()}
                vaz = vazamento_baixo(refs, est)
                for s in STEMS:
                    e_ref = float(np.sum(refs[s] ** 2))
                    rel = 10 * np.log10((e_ref + EPS) / (e_mist + EPS))
                    linha = {"faixa": f["nome"], "condicao": c, "tecnica": tec, "stem": s,
                             "sdr": round(sdr(refs[s], est[s]), 3), "ref_db_rel_mistura": round(rel, 1),
                             "valido": int(rel > LIMIAR_SILENCIO)}
                    for k in ("vaz_baixo", "baixo_capturado", "baixo_em_vocals", "baixo_em_drums", "baixo_em_other"):
                        linha[k] = round(vaz[k], 4) if s == "bass" else ""
                    linhas.append(linha)
    return linhas


# ---------------------------------------------------------------- saídas

def mediana(linhas, **filtro) -> tuple[float, int]:
    v = [l for l in linhas if l["valido"] and all(l[k] == x for k, x in filtro.items())]
    return (float(np.median([l["sdr"] for l in v])) if v else float("nan")), len(v)


def relatorio(linhas: list[dict], n_faixas: int) -> str:
    tempos = json.loads(TEMPOS.read_text(encoding="utf-8")) if TEMPOS.exists() else {}
    nomes = {"E": "E (produção)", "SW": "SW direto", "ft": "Demucs ft", "E+medio": "E + baixo médio"}
    r = ["# Avaliação da separação de faixas (MUSDB18 amostra)", "",
         f"Gerado por `avaliacao/avaliar.py`. {n_faixas} trechos de ~7 s da divisão *test*, "
         "cada um em duas condições: **estéreo** (original) e **mono** ((L+R)/2 duplicado, como o vinil mono). "
         "SDR = nSDR do desafio MDX (`10·log10(Σs²/Σ(s−ŝ)²)`, trecho inteiro), em dB, maior é melhor. "
         "Guitarra + piano + outros das saídas de 6 faixas foram somados em *other*. "
         f"Stems de referência mais de {-LIMIAR_SILENCIO} dB abaixo da mistura foram ignorados (n = trechos válidos).", ""]

    def tabela(stems):
        cab = "| técnica | " + " | ".join(f"{s} {c}" for s in stems for c in CONDICOES) + " |"
        r.extend([cab, "|" + "---|" * (1 + len(stems) * len(CONDICOES))])
        for tec in TECNICAS:
            cel = []
            for s in stems:
                for c in CONDICOES:
                    m, n = mediana(linhas, tecnica=tec, stem=s, condicao=c)
                    cel.append(f"{m:.2f} (n={n})")
            r.append(f"| {nomes[tec]} | " + " | ".join(cel) + " |")
        r.append("")

    r += ["## Voz e baixo (mediana do SDR, dB)", ""]
    tabela(["vocals", "bass"])
    r += ["## Bateria e outros (mediana do SDR, dB)", ""]
    tabela(["drums", "other"])

    r += ["## Vazamento do baixo (mediana)", "",
          "Fração da energia do baixo verdadeiro em 40–300 Hz que aparece em cada faixa estimada: projeção do "
          "erro da faixa no baixo, `<b, ŝ_k − s_k>/<b, b>`, tudo filtrado em 40–300 Hz (com separação perfeita dá 0; "
          "projetar o erro desconta o que guitarra ou bumbo verdadeiros já têm de parecido com o baixo). "
          "*vazamento* = soma nas faixas que não são o baixo; menor é melhor. *capturado* perto de 1 é o ideal.", "",
          "| técnica | condição | capturado | vazamento | → voz | → bateria | → other (guit./piano/outros) |",
          "|---|---|---|---|---|---|---|"]
    for tec in TECNICAS:
        for c in CONDICOES:
            v = [l for l in linhas if l["stem"] == "bass" and l["valido"] and l["tecnica"] == tec and l["condicao"] == c]
            if not v:
                continue
            md = {k: np.median([l[k] for l in v]) for k in ("baixo_capturado", "vaz_baixo", "baixo_em_vocals", "baixo_em_drums", "baixo_em_other")}
            r.append(f"| {nomes[tec]} | {c} | {md['baixo_capturado']:.1%} | {md['vaz_baixo']:.1%} | "
                     f"{md['baixo_em_vocals']:.1%} | {md['baixo_em_drums']:.1%} | {md['baixo_em_other']:.1%} |")
    r.append("")

    # quem ganha, trecho a trecho, no mono (o caso da biblioteca)
    r += ["## Vitórias trecho a trecho (mono)", "", "Em quantos trechos cada técnica teve o maior SDR.", "",
          "| stem | " + " | ".join(nomes[t] for t in TECNICAS) + " |", "|---|" + "---|" * len(TECNICAS)]
    for s in ("vocals", "bass"):
        cont = dict.fromkeys(TECNICAS, 0)
        for nome in sorted({l["faixa"] for l in linhas}):
            v = {l["tecnica"]: l["sdr"] for l in linhas
                 if l["faixa"] == nome and l["stem"] == s and l["condicao"] == "mono" and l["valido"]}
            if len(v) == len(TECNICAS):
                cont[max(v, key=v.get)] += 1
        r.append(f"| {s} | " + " | ".join(str(cont[t]) for t in TECNICAS) + " |")
    r.append("")

    if tempos:
        r += ["## Tempo de GPU", "", "| etapa | itens | segundos |", "|---|---|---|"]
        for k, v in tempos.items():
            r.append(f"| {k} | {v['itens']} | {v['segundos']:.0f} |")
        r += [f"| **total** | | **{sum(v['segundos'] for v in tempos.values()):.0f}** |", ""]
    return "\n".join(r)


def gravar(linhas: list[dict], n_faixas: int) -> None:
    with open(AQUI / "resultados.csv", "w", newline="", encoding="utf-8") as fp:
        w = csv.DictWriter(fp, fieldnames=list(linhas[0].keys()))
        w.writeheader()
        w.writerows(linhas)
    texto = relatorio(linhas, n_faixas)
    # a recomendação é escrita à mão, depois de ler os números; preserva o que já existir
    rel = AQUI / "RELATORIO.md"
    marca = "## Recomendação"
    if rel.exists() and marca in rel.read_text(encoding="utf-8"):
        texto += "\n" + marca + rel.read_text(encoding="utf-8").split(marca, 1)[1]
    rel.write_text(texto, encoding="utf-8")
    print(f"[ok] {len(linhas)} linhas em resultados.csv; RELATORIO.md atualizado")


if __name__ == "__main__":
    limite = int(sys.argv[sys.argv.index("--faixas") + 1]) if "--faixas" in sys.argv else None
    faixas = carregar_faixas(limite)
    print(f"[faixas] {len(faixas)} trecho(s) × {len(CONDICOES)} condições × {len(TECNICAS)} técnicas")
    if "--so-relatorio" not in sys.argv:
        processar(faixas)
    gravar(avaliar(faixas), len(faixas))
