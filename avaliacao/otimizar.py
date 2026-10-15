"""Ciclo de otimização da separação, com foco em voz e baixo.

Cada "receita" é uma combinação de saídas brutas de modelos (voz com modelo X, instrumental = mistura − voz,
SW no instrumental, médias...). A saída bruta de cada modelo em cada entrada é guardada uma vez em
cache_bruto/, então receitas que compartilham etapas não reprocessam nada.

Uso:  .venv\\Scripts\\python avaliacao\\otimizar.py E SW voz_viperx          (receitas a comparar)
      .venv\\Scripts\\python avaliacao\\otimizar.py E --faixas 30 --cond estereo,mono
      .venv\\Scripts\\python avaliacao\\otimizar.py --lista                    (mostra as receitas)
Padrão: 15 primeiros trechos, só mono (a biblioteca do usuário é quase toda mono).
Resultado: uma linha JSON por receita em avaliacao/otimizacao.jsonl.
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent))
import avaliar as A  # noqa: E402

BRUTO = A.AQUI / "cache_bruto"
LOG = A.AQUI / "otimizacao.jsonl"
SW = A.MODELO
KIM = A.MODELO_VOZ
VIPERX = "model_bs_roformer_ep_317_sdr_12.9755.ckpt"
BLEEDLESS = "mel_band_roformer_kim_ft2_bleedless_unwa.ckpt"


# ---------------------------------------------------------------- saídas brutas com cache

def curto(modelo: str) -> str:
    return {SW: "sw", KIM: "kim", VIPERX: "viperx", BLEEDLESS: "bleedless"}.get(modelo, Path(modelo).stem)


def bruto(modelo: str, tag: str, entradas: dict[str, np.ndarray], overlap: int = 2, pitch: int = 0) -> dict:
    """Saída do modelo para cada entrada (áudio já na escala de pico 0,5). tag identifica a entrada
    (ex.: 'mist', 'instr-kim'). Devolve {k: {stem: áudio}}."""
    raiz = BRUTO / f"{curto(modelo)}_ov{overlap}_ps{pitch}" / tag
    falta = {k: x for k, x in entradas.items() if not (raiz / k / "_ok").exists()}
    if falta:
        A.checar_gpu()
        from audio_separator.separator import Separator
        saida = A.TMP / "otim"
        saida.mkdir(parents=True, exist_ok=True)
        sep = Separator(model_file_dir=str(A.MODELOS), output_dir=str(saida), output_format="WAV",
                        use_soundfile=True, normalization_threshold=1.0, log_level=30,
                        mdxc_params={"segment_size": 256, "override_model_segment_size": False,
                                     "batch_size": 1, "overlap": overlap, "pitch_shift": pitch})
        sep.load_model(modelo)
        t0 = time.time()
        for k, x in falta.items():
            if (A.FAIXAS / "_tmp_roformer").exists():
                print("[parado] a fila de músicas começou"); sys.exit(2)
            pad = saida / f"{k}.wav"   # completa até 12 s, como no avaliar.py (mesmo segmento da produção)
            sf.write(pad, A.ajustar(x, max(len(x), int(A.DURACAO_MIN * A.SR))), A.SR, subtype="FLOAT")
            d = raiz / k
            d.mkdir(parents=True, exist_ok=True)
            for s in sep.separate(str(pad)):
                p = Path(s) if Path(s).is_absolute() else saida / s
                nome = p.stem.split("(")[-1].split(")")[0].lower()
                a = sf.read(p, dtype="float32", always_2d=True)[0][: len(x)]
                sf.write(d / f"{nome}.flac", np.clip(a, -1, 1), A.SR, subtype="PCM_24")
                p.unlink()
            pad.unlink()
            (d / "_ok").touch()
        A.cronometrar(f"otim: {curto(modelo)} ov{overlap} ps{pitch} {tag}", t0, len(falta))
    return {k: {p.stem: sf.read(p, dtype="float32", always_2d=True)[0]
                for p in (raiz / k).glob("*.flac")} for k in entradas}


# ---------------------------------------------------------------- receitas

def voz_de(modelo, mist, **kw):
    return {k: v["vocals"] for k, v in bruto(modelo, "mist", mist, **kw).items()}


def cascata(mist, voz, tag, **kw):
    """Instrumental = mistura − voz; SW nele; a voz vem de fora. Devolve 4 faixas (MUSDB)."""
    instr = {k: mist[k][: len(voz[k])] - voz[k] for k in mist}
    resto = bruto(SW, tag, instr, **kw)
    out = {}
    for k in mist:
        r = dict(resto[k]); r.pop("vocals", None); r["vocals"] = voz[k]
        out[k] = A.para_4(r)
    return out


def trocar_baixo(base, baixo):
    """Troca o baixo e manda a diferença para 'other' (a soma das faixas não muda)."""
    out = {}
    for k, b in base.items():
        n = len(b["bass"]); nb = A.ajustar(baixo[k], n)
        out[k] = dict(b, bass=nb, other=b["other"] - (nb - b["bass"]))
    return out


def r_E(mist):                 # produção atual
    return cascata(mist, voz_de(KIM, mist), "instr-kim")


def r_SW(mist):                # SW direto na mistura
    return {k: A.para_4(v) for k, v in bruto(SW, "mist", mist).items()}


def r_voz_viperx(mist):
    return cascata(mist, voz_de(VIPERX, mist), "instr-viperx")


def r_voz_bleedless(mist):
    return cascata(mist, voz_de(BLEEDLESS, mist), "instr-bleedless")


def r_voz_media(mist):         # média Kim + Viperx
    a, b = voz_de(KIM, mist), voz_de(VIPERX, mist)
    return cascata(mist, {k: (a[k] + b[k]) / 2 for k in mist}, "instr-kim+viperx")


def r_baixo_media(mist):       # E, mas baixo = média(SW no instrumental, SW na mistura)
    base = r_E(mist)
    sw = bruto(SW, "mist", mist)
    return trocar_baixo(base, {k: (base[k]["bass"] + A.ajustar(sw[k]["bass"], len(base[k]["bass"]))) / 2 for k in mist})


def r_E_ov4(mist):
    return cascata(mist, voz_de(KIM, mist, overlap=4), "instr-kim-ov4", overlap=4)


DESLOC = 0.37   # s: deslocamento do "teste com deslocamento" (TTA); valor não múltiplo do segmento do modelo


def deslocado(entradas, s):
    """Atrasa cada entrada em s segundos (silêncio no começo)."""
    n = int(s * A.SR)
    return {k: np.concatenate([np.zeros((n, x.shape[1]), np.float32), x]) for k, x in entradas.items()}


def desfazer(saidas, s, tam):
    n = int(s * A.SR)
    return {k: {st: A.ajustar(a[n:], tam[k]) for st, a in v.items()} for k, v in saidas.items()}


def media_saidas(*todas):
    return {k: {st: sum(t[k][st] for t in todas) / len(todas) for st in todas[0][k]} for k in todas[0]}


def bruto_tta(modelo, tag, entradas):
    """Roda o modelo na entrada normal e na deslocada, e tira a média (como os 'shifts' do Demucs)."""
    tam = {k: len(x) for k, x in entradas.items()}
    a = {k: {st: A.ajustar(v, tam[k]) for st, v in d.items()} for k, d in bruto(modelo, tag, entradas).items()}
    b = desfazer(bruto(modelo, tag + "-desl", deslocado(entradas, DESLOC)), DESLOC, tam)
    return media_saidas(a, b)


def r_E_tta(mist):             # E com média de 2 passadas deslocadas, na voz e no SW
    voz = {k: v["vocals"] for k, v in bruto_tta(KIM, "mist", mist).items()}
    instr = {k: mist[k][: len(voz[k])] - voz[k] for k in mist}
    resto = bruto_tta(SW, "instr-kim-tta", instr)
    out = {}
    for k in mist:
        r = dict(resto[k]); r.pop("vocals", None); r["vocals"] = voz[k]
        out[k] = A.para_4(r)
    return out


def r_baixo_sem_bateria(mist):  # E; depois SW de novo em (mistura − voz − bateria) só para o baixo
    base = r_E(mist)
    entrada = {k: mist[k][: len(base[k]["bass"])] - base[k]["vocals"] - base[k]["drums"] for k in mist}
    sw2 = bruto(SW, "instr-kim-semdrums", entrada)
    return trocar_baixo(base, {k: sw2[k]["bass"] for k in mist})


def r_baixo_media3(mist):      # E; baixo = média(SW instrumental, SW mistura, SW sem bateria)
    base = r_E(mist)
    sw = bruto(SW, "mist", mist)
    entrada = {k: mist[k][: len(base[k]["bass"])] - base[k]["vocals"] - base[k]["drums"] for k in mist}
    sw2 = bruto(SW, "instr-kim-semdrums", entrada)
    n = {k: len(base[k]["bass"]) for k in mist}
    return trocar_baixo(base, {k: (base[k]["bass"] + A.ajustar(sw[k]["bass"], n[k]) + A.ajustar(sw2[k]["bass"], n[k])) / 3
                               for k in mist})


def r_baixo_sem_bat_ov4(mist):  # baixo_sem_bateria com sobreposição 4 só na segunda passada
    base = r_E(mist)
    entrada = {k: mist[k][: len(base[k]["bass"])] - base[k]["vocals"] - base[k]["drums"] for k in mist}
    sw2 = bruto(SW, "instr-kim-semdrums", entrada, overlap=4)
    return trocar_baixo(base, {k: sw2[k]["bass"] for k in mist})


def r_baixo_so_cordas(mist):   # SW de novo só com baixo + guitarra + piano + outros (sem voz/bateria), 2 vezes
    base = r_baixo_sem_bateria(mist)
    entrada = {k: mist[k][: len(base[k]["bass"])] - base[k]["vocals"] - base[k]["drums"] for k in mist}
    sw2 = bruto(SW, "instr-kim-semdrums", entrada)
    # terceira passada: tira também o que a segunda passada chamou de bateria/voz residual
    ent3 = {k: entrada[k] - A.ajustar(sw2[k]["drums"], len(entrada[k])) - A.ajustar(sw2[k]["vocals"], len(entrada[k]))
            for k in mist}
    sw3 = bruto(SW, "instr-kim-semdrums2", ent3)
    return trocar_baixo(base, {k: sw3[k]["bass"] for k in mist})


def r_viperx_sem_bat(mist):    # voz Viperx + SW no instrumental + baixo de uma 2ª passada sem voz e sem bateria
    base = r_voz_viperx(mist)
    entrada = {k: mist[k][: len(base[k]["bass"])] - base[k]["vocals"] - base[k]["drums"] for k in mist}
    sw2 = bruto(SW, "instr-viperx-semdrums", entrada)
    return trocar_baixo(base, {k: sw2[k]["bass"] for k in mist})


VOZES_NOVAS = {   # candidatos a modelo de voz; "so_voz_<nome>" troca só a voz da melhor receita (baixo inalterado)
    "viperx1296": "model_bs_roformer_ep_368_sdr_12.9628.ckpt",
    "revive3e": "bs_roformer_vocals_revive_v3e_unwa.ckpt",
    "bs_gabox": "bs_roformer_vocals_gabox.ckpt",
    "becruily": "mel_band_roformer_vocals_becruily.ckpt",
    "fv7b": "mel_band_roformer_vocals_fv7b_gabox.ckpt",
    "kimft": "mel_band_roformer_kim_ft_unwa.ckpt",
}


def so_voz(modelo):
    def r(mist):
        base = r_viperx_sem_bat(mist)
        voz = voz_de(modelo, mist)
        return {k: dict(b, vocals=A.ajustar(voz[k], len(b["vocals"]))) for k, b in base.items()}
    return r


def r_voz_media2(mist):       # voz = média(Viperx 1297, Viperx 1296), resto da viperx_sem_bat
    base = r_viperx_sem_bat(mist)
    a, b = voz_de(VIPERX, mist), voz_de(VOZES_NOVAS["viperx1296"], mist)
    return {k: dict(v, vocals=(A.ajustar(a[k], len(v["vocals"])) + A.ajustar(b[k], len(v["vocals"]))) / 2)
            for k, v in base.items()}


def r_voz_sw_viperx(mist):    # voz = média(voz do SW na mistura, Viperx); resto = SW no instrumental
    a = {k: v["vocals"] for k, v in bruto(SW, "mist", mist).items()}
    b = voz_de(VIPERX, mist)
    voz = {k: (A.ajustar(a[k], len(mist[k])) + A.ajustar(b[k], len(mist[k]))) / 2 for k in mist}
    return cascata(mist, voz, "instr-sw+viperx")


def r_voz_sw_viperx_gabox(mist):   # média de 3 vozes: SW, Viperx, BS Gabox
    a = {k: v["vocals"] for k, v in bruto(SW, "mist", mist).items()}
    b, c = voz_de(VIPERX, mist), voz_de(VOZES_NOVAS["bs_gabox"], mist)
    voz = {k: (A.ajustar(a[k], len(mist[k])) + A.ajustar(b[k], len(mist[k])) + A.ajustar(c[k], len(mist[k]))) / 3
           for k in mist}
    return cascata(mist, voz, "instr-sw+viperx+gabox")


RECEITAS = {**{f"so_voz_{n}": so_voz(m) for n, m in VOZES_NOVAS.items()}, "voz_media2": r_voz_media2,
            "voz_sw_viperx": r_voz_sw_viperx, "voz_sw_viperx_gabox": r_voz_sw_viperx_gabox,
            "viperx_sem_bat": r_viperx_sem_bat, "baixo_sem_bat_ov4": r_baixo_sem_bat_ov4, "baixo_so_cordas": r_baixo_so_cordas, "E": r_E, "SW": r_SW, "voz_viperx": r_voz_viperx, "voz_bleedless": r_voz_bleedless,
            "voz_media": r_voz_media, "baixo_media": r_baixo_media, "E_ov4": r_E_ov4,
            "E_tta": r_E_tta, "baixo_sem_bateria": r_baixo_sem_bateria, "baixo_media3": r_baixo_media3}


# ---------------------------------------------------------------- avaliação

def avaliar(nome, faixas, conds):
    linhas = []
    for c in conds:
        mist, info = {}, {}
        for f in faixas:
            wav, x, g = A.preparar(f, c)
            mist[A.chave(f, c)] = x; info[A.chave(f, c)] = (f, g)
        est_todas = RECEITAS[nome](mist)
        for k, est in est_todas.items():
            f, g = info[k]
            x = A.condicao(f["mistura"], c)
            refs = {s: A.condicao(f["refs"][s], c) for s in A.STEMS}
            est = {s: A.ajustar(a, len(x)) / g for s, a in est.items()}
            e_mist = float(np.sum(x ** 2))
            vaz = A.vazamento_baixo(refs, est)
            for s in ("vocals", "bass"):
                rel = 10 * np.log10((float(np.sum(refs[s] ** 2)) + A.EPS) / (e_mist + A.EPS))
                if rel > A.LIMIAR_SILENCIO:
                    linhas.append({"cond": c, "faixa": k, "stem": s, "sdr": A.sdr(refs[s], est[s]),
                                   "vaz": vaz["vaz_baixo"] if s == "bass" else np.nan})
    return linhas


def resumo(nome, linhas, n_faixas):
    r = {"receita": nome, "faixas": n_faixas}
    for c in sorted({l["cond"] for l in linhas}):
        for s in ("vocals", "bass"):
            v = [l["sdr"] for l in linhas if l["cond"] == c and l["stem"] == s]
            r[f"{s}_{c}_med"] = round(float(np.median(v)), 3)
            r[f"{s}_{c}_media"] = round(float(np.mean(v)), 3)
        vz = [l["vaz"] for l in linhas if l["cond"] == c and l["stem"] == "bass"]
        r[f"vaz_baixo_{c}"] = round(float(np.median(vz)), 4)
    return r


if __name__ == "__main__":
    if "--lista" in sys.argv:
        print("\n".join(f"{k:15s} {(v.__doc__ or '').strip()}" for k, v in RECEITAS.items())); sys.exit()
    arg = lambda nome, pad: sys.argv[sys.argv.index(nome) + 1] if nome in sys.argv else pad   # noqa: E731
    n = int(arg("--faixas", "15"))
    conds = arg("--cond", "mono").split(",")
    pulados = {sys.argv[i + 1] for i, a in enumerate(sys.argv) if a in ("--faixas", "--cond")}
    nomes = [a for a in sys.argv[1:] if not a.startswith("--") and a not in pulados]
    faixas = A.carregar_faixas(n)
    novos = []
    for nome in nomes:
        linhas = avaliar(nome, faixas, conds)
        r = resumo(nome, linhas, len(faixas))
        novos.append(r)
        print("[resultado]", r, flush=True)
    with open(LOG, "a", encoding="utf-8") as fp:
        for r in novos:
            fp.write(json.dumps(dict(r, quando=time.strftime("%H:%M")), ensure_ascii=False) + "\n")
