"""Monta o catálogo da mesa: álbuns em ordem, faixas de cada álbum e as versões já separadas de cada faixa.

- Álbuns com pasta em musicas/ usam as faixas reais da pasta (ordem de lado/faixa, duração do arquivo).
- Álbuns que ainda não temos (Yellow Submarine, Abbey Road, Let It Be) usam a lista de referência abaixo.
- Cada pasta em faixas/ vira uma "versão" da faixa de onde veio: a versão mono do álbum, " - nova"
  (técnica F), as avulsas (Something, Come Together...) encaixadas pelo título no álbum certo.
- "All Songs" reúne todas as músicas já separadas, de todos os álbuns, em ordem alfabética
  (avulsas sem álbum conhecido, como My Sweet Lord, ficam só lá).

O servidor da mesa (mixer.py) chama gerar() a cada pedido de /catalogo.json, então músicas recém-separadas
aparecem sem reiniciar nada.
"""
import re
import unicodedata
from pathlib import Path

import soundfile as sf

RAIZ = Path(__file__).parent
MUSICAS = RAIZ / "musicas"
FAIXAS = RAIZ / "faixas"
EXT = {".mp3", ".flac", ".wav", ".m4a", ".aac", ".ogg", ".webm", ".opus"}
STEMS = ["vocals", "guitar", "bass", "drums", "piano", "other"]

# (título exibido, ano, capa, trecho do nome da pasta em musicas/ ou None, faixas de referência se não houver pasta)
ALBUNS = [
    ("Please Please Me", 1963, "01-Please-Please-Me", "Please Please Me", None),
    ("With the Beatles", 1963, "02-With-the-Beatles", "With the Beatles", None),
    ("A Hard Day's Night", 1964, "03-A-Hard-Days-Night", "A Hard Day's Night", None),
    ("Beatles for Sale", 1964, "04-Beatles-for-Sale", "Beatles for Sale", None),
    ("Help!", 1965, "05-Help", "Help", None),
    ("Rubber Soul", 1965, "06-Rubber-Soul", "Rubber Soul", None),
    ("Revolver", 1966, "07-Revolver", "Revolver", None),
    ("Sgt. Pepper's Lonely Hearts Club Band", 1967, "08-Sgt-Pepper", "Sgt Pepper's Lonely Hearts Club Band", None),
    ("Magical Mystery Tour", 1967, "09-Magical-Mystery-Tour", "Magical Mystery Tour", None),
    ("The Beatles", 1968, "10-The-Beatles-White-Album", "The Beatles", None),
    ("Yellow Submarine", 1969, "11-Yellow-Submarine", None, [
        ("Yellow Submarine", "2:38"), ("Only a Northern Song", "3:24"), ("All Together Now", "2:10"),
        ("Hey Bulldog", "3:11"), ("It's All Too Much", "6:28"), ("All You Need Is Love", "3:47"),
        ("Pepperland", "2:18"), ("Sea of Time", "3:00"), ("Sea of Holes", "2:17"), ("Sea of Monsters", "3:37"),
        ("March of the Meanies", "2:16"), ("Pepperland Laid Waste", "2:15"), ("Yellow Submarine in Pepperland", "2:13")]),
    ("Abbey Road", 1969, "12-Abbey-Road", "Abbey Road", [   # pasta 1969 - Abbey Road (2019 Mix); a lista abaixo é só reserva
        ("Come Together", "4:20"), ("Something", "3:03"), ("Maxwell's Silver Hammer", "3:27"), ("Oh! Darling", "3:26"),
        ("Octopus's Garden", "2:51"), ("I Want You (She's So Heavy)", "7:47"), ("Here Comes the Sun", "3:05"),
        ("Because", "2:45"), ("You Never Give Me Your Money", "4:02"), ("Sun King", "2:26"), ("Mean Mr. Mustard", "1:06"),
        ("Polythene Pam", "1:12"), ("She Came In Through the Bathroom Window", "1:57"), ("Golden Slumbers", "1:31"),
        ("Carry That Weight", "1:36"), ("The End", "2:05"), ("Her Majesty", "0:23")]),
    ("Let It Be", 1970, "13-Let-It-Be", None, [
        ("Two of Us", "3:36"), ("Dig a Pony", "3:54"), ("Across the Universe", "3:48"), ("I Me Mine", "2:25"),
        ("Dig It", "0:50"), ("Let It Be", "4:03"), ("Maggie Mae", "0:40"), ("I've Got a Feeling", "3:37"),
        ("One After 909", "2:54"), ("The Long and Winding Road", "3:38"), ("For You Blue", "2:32"), ("Get Back", "3:09")]),
    ("Mono Masters", 2009, "14-Mono-Masters", "Mono Masters", None),
    ("All Songs", "", "16-All-Songs", None, []),
]


def simples(t: str) -> str:
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().lower()
    t = re.sub(r"['’]", "", t)
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def sem_parenteses(t: str) -> str:
    return re.sub(r"\s*\((mono|\d{4} (mix|remaster)|original single version)\)", "", t, flags=re.I).strip()


def nome_album(pasta: str) -> str:
    """'1968 - The Beatles (mono)' -> 'the beatles' (para comparar nomes de álbum exatos)."""
    return simples(re.sub(r"\s*\(mono\)", "", re.sub(r"^\d{4}\s*-\s*", "", pasta)))


def titulo_arquivo(f: Path) -> str:
    return re.sub(r"^[A-Z]?\d+\s*[-.]\s*", "", f.stem)


def ordem_faixa(f: Path):
    m = re.match(r"([A-Z]?)(\d+)", f.name)
    return (m.group(1), int(m.group(2))) if m else ("~", 0)


def duracao(f: Path) -> str:
    try:
        s = sf.info(str(f)).duration
    except Exception:   # webm/opus: o libsndfile não lê; pergunta ao ffprobe
        import subprocess
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)],
                           capture_output=True, text=True, creationflags=0x08000000)
        try:
            s = float(r.stdout.strip())
        except ValueError:
            return ""
    return f"{int(s // 60)}:{int(s % 60):02d}"


_durs: dict = {}


def duracao_cache(f: Path) -> str:
    k = (str(f), f.stat().st_mtime)
    if k not in _durs:
        _durs[k] = duracao(f)
    return _durs[k]


def titulo_separado(f: Path) -> str:
    """Mesmo nome de pasta que o separar.py dá à música (sem rótulo)."""
    t = titulo_arquivo(f)
    return f"{t} (mono)" if "(mono)" in f.parent.name else t


def gerar() -> dict:
    pastas = {p.name: p for p in FAIXAS.iterdir() if p.is_dir() and not p.name.startswith("_")} if FAIXAS.exists() else {}
    arquivos = [f for f in MUSICAS.rglob("*") if f.suffix.lower() in EXT] if MUSICAS.exists() else []

    def versoes_de(f: Path) -> list:
        base = titulo_separado(f)
        avulsa = f.parent.name == "Avulsas"
        m = re.search(r"\(([^)]*(mix|remaster)[^)]*)\)", f.stem, re.I)
        tipo = "mono" if "(mono)" in f.parent.name else (m.group(1) if m else "avulsa")
        out = []
        for nome, p in sorted(pastas.items()):
            if nome == base or nome.startswith(base + " - "):
                stems = [s for s in STEMS if (p / f"{s}.flac").exists()]
                if len(stems) < 6:
                    continue   # ainda sendo separada
                rot = nome[len(base) + 3:] if nome != base else ""
                out.append({"rotulo": tipo + (f" · {rot}" if rot else ""), "pasta": nome, "nova": bool(rot),
                            "avulsa": avulsa})
        return out

    albuns = []
    for titulo, ano, capa, pasta, ref in ALBUNS:
        faixas = []
        if pasta:
            dirs = [d for d in MUSICAS.iterdir() if d.is_dir() and nome_album(d.name) == simples(pasta)] if MUSICAS.exists() else []
            for f in sorted((f for d in dirs for f in d.iterdir() if f.suffix.lower() in EXT), key=ordem_faixa):
                faixas.append({"titulo": sem_parenteses(titulo_arquivo(f)) if "Mono Masters" not in titulo else titulo_arquivo(f),
                               "duracao": duracao_cache(f), "versoes": versoes_de(f)})
        else:
            faixas = [{"titulo": t, "duracao": d, "versoes": []} for t, d in (ref or [])]
        albuns.append({"titulo": titulo, "ano": ano, "capa": f"imagens/capas/web/{capa}.jpg", "faixas": faixas})

    sem_album = []
    # avulsas: encaixa pelo título no primeiro álbum que tiver a faixa; senão, "Músicas avulsas"
    for f in sorted(a for a in arquivos if a.parent.name == "Avulsas"):
        vs = versoes_de(f)
        if not vs:
            continue
        alvo = simples(sem_parenteses(titulo_arquivo(f)))
        achou = False
        for al in albuns[:-1]:
            for fx in al["faixas"]:
                if simples(sem_parenteses(fx["titulo"])) == alvo:
                    fx["versoes"] += [v for v in vs if v["pasta"] not in {x["pasta"] for x in fx["versoes"]}]   # sem repetir
                    if not fx["duracao"]:
                        fx["duracao"] = duracao_cache(f)
                    achou = True
                    break
            if achou:
                break
        if not achou:
            sem_album.append({"titulo": sem_parenteses(titulo_arquivo(f)), "duracao": duracao_cache(f), "versoes": vs, "album": ""})

    for al in albuns:   # a versão nova aparece primeiro
        for fx in al["faixas"]:
            fx["versoes"].sort(key=lambda v: (not v["nova"], v["avulsa"], v["rotulo"]))
    # All Songs: toda faixa com pelo menos uma versão separada, de qualquer álbum, em ordem alfabética
    todas = [dict(fx, album=al["titulo"]) for al in albuns[:-1] for fx in al["faixas"] if fx["versoes"]] + sem_album
    albuns[-1]["faixas"] = sorted(todas, key=lambda fx: simples(fx["titulo"]))
    return {"albuns": albuns}


if __name__ == "__main__":
    import json
    c = gerar()
    for al in c["albuns"]:
        prontas = sum(1 for f in al["faixas"] if f["versoes"])
        print(f"{al['titulo'][:30]:30s} {len(al['faixas']):3d} faixas, {prontas:3d} separadas")
    print(json.dumps([f for al in c["albuns"] for f in al["faixas"] if len(f["versoes"]) > 1][:3], ensure_ascii=False, indent=1))
