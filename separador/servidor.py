"""Servidor da mesa.  Uso:  .venv\\Scripts\\python separador\\servidor.py  [--sem-abrir] [--porta N]

- Página (mesa/) e faixas separadas (/faixas/… = dados/faixas/) sem cache; /catalogo.json gerado na hora (músicas novas aparecem sozinhas).
- Aba "enviar": POST /enviar recebe um arquivo de áudio, salva em dados/musicas/Avulsas/ e põe na fila de envios.
  Um trabalhador separa um envio por vez (a GPU é uma só) e grava o andamento; /envios.json mostra a fila,
  POST /cancelar?id=… cancela. A fila fica em dados/faixas/_envios/ e sobrevive a reinícios do servidor.
- Pasta vigiada: arquivos de áudio novos em dados/musicas/ (raiz) ou dados/musicas/Avulsas/ entram sozinhos na mesma fila.
- Enquanto há envio sendo separado existe dados/faixas/_envio_ocupado: o vigia pausa a fila grande do PC (prioridade).
"""
import functools
import http.server
import importlib
import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import catalogo

PORTA = int(sys.argv[sys.argv.index("--porta") + 1]) if "--porta" in sys.argv else 8765
AQUI = Path(__file__).resolve().parent
MESA = AQUI.parent / "mesa"                # a página
MUSICAS = catalogo.MUSICAS                 # dados/musicas
FAIXAS = catalogo.FAIXAS                   # dados/faixas
AVULSAS = MUSICAS / "Avulsas"
ENVIOS = FAIXAS / "_envios"
OCUPADO = FAIXAS / "_envio_ocupado"
PY = sys.executable   # o mesmo Python que roda o servidor (o da .venv)
EXT_OK = {".mp3", ".flac", ".wav", ".m4a", ".aac", ".ogg", ".webm", ".opus"}
MAX_BYTES = 400 * 1024 * 1024
SEM_JANELA = getattr(subprocess, "CREATE_NO_WINDOW", 0)

trava = threading.Lock()
acordar = threading.Event()
envios: list[dict] = []
processo_atual: dict = {}   # {"id": …, "proc": Popen}


# ---------------------------------------------------------------- fila de envios (persistida em disco)

def salvar_fila() -> None:
    ENVIOS.mkdir(parents=True, exist_ok=True)
    tmp = ENVIOS / "fila.json.tmp"
    tmp.write_text(json.dumps(envios, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(ENVIOS / "fila.json")


def carregar_fila() -> None:
    global envios
    try:
        envios = json.loads((ENVIOS / "fila.json").read_text(encoding="utf-8"))
    except Exception:
        envios = []
    for e in envios:   # o servidor caiu no meio: volta para a espera
        if e["estado"] == "separando":
            e.update(estado="espera", etapa="", total=0.0)
    OCUPADO.unlink(missing_ok=True)


def limpar_nome(t: str) -> str:
    t = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", t).strip().strip(".")
    return re.sub(r"\s+", " ", t)[:120] or "Sem título"


def destino_de(titulo: str) -> str:
    """Para onde a música vai na estante: o disco com uma faixa de mesmo nome, ou All Songs."""
    alvo = catalogo.simples(catalogo.sem_parenteses(titulo))
    for al in catalogo.gerar()["albuns"][:-1]:
        if any(catalogo.simples(catalogo.sem_parenteses(f["titulo"])) == alvo for f in al["faixas"]):
            return al["titulo"]
    return "All Songs"


def novo_envio(titulo: str, nome_original: str, corpo: bytes) -> dict:
    ext = Path(nome_original).suffix.lower()
    if ext not in EXT_OK:
        raise ValueError(f"formato não aceito ({ext or 'sem extensão'}); use mp3, wav, flac, m4a, ogg ou webm")
    titulo = limpar_nome(titulo or Path(nome_original).stem)
    AVULSAS.mkdir(parents=True, exist_ok=True)
    for velho in AVULSAS.glob(f"{glob_escape(titulo)}.*"):   # mesmo nome, outro formato: troca pelo novo arquivo
        if velho.suffix.lower() in EXT_OK and velho.suffix.lower() != ext:
            velho.unlink()
    with trava:   # grava dentro da trava: a pasta vigiada não pode pegar o arquivo antes de ele entrar na fila
        (AVULSAS / f"{titulo}{ext}").write_bytes(corpo)
        return _enfileirar(titulo, nome_original)


def _enfileirar(titulo: str, nome_original: str, origem: str = "envio") -> dict:
    """Põe na fila (chamar com a trava pega)."""
    # já existe uma separação desta música? então esta vira uma versão nova ("envio 2", "envio 3"…)
    base = FAIXAS / titulo
    rotulo = ""
    if base.exists():
        k = 2
        while (FAIXAS / f"{titulo} - envio {k}").exists() or any(
                e["titulo"] == titulo and e.get("rotulo") == f"envio {k}" and e["estado"] in ("espera", "separando") for e in envios):
            k += 1
        rotulo = f"envio {k}"
    e = {"id": uuid.uuid4().hex[:10], "titulo": titulo, "arquivo": nome_original, "rotulo": rotulo, "origem": origem,
         "pasta": f"{titulo} - {rotulo}" if rotulo else titulo, "destino": destino_de(titulo),
         "estado": "espera", "etapa": "", "total": 0.0, "criado": time.time(), "inicio": None, "fim": None, "erro": ""}
    envios.append(e)
    salvar_fila()
    acordar.set()
    return e


def vigiar_pasta() -> None:
    """A cada 15 s: áudio novo em musicas/ (raiz) ou musicas/Avulsas/, ainda não separado e fora da fila, entra na fila.
    Espera o arquivo parar de crescer (cópia terminada). As pastas de álbum ficam com o separar.py/fila do usuário."""
    musicas = MUSICAS
    while True:
        try:
            for f in [*musicas.glob("*"), *AVULSAS.glob("*")]:
                if not f.is_file() or f.suffix.lower() not in EXT_OK or time.time() - f.stat().st_mtime < 5:
                    continue
                titulo = f.stem
                if (FAIXAS / titulo).exists():
                    continue
                with trava:
                    if any(e["titulo"] == titulo and e["estado"] in ("espera", "separando", "pronta", "erro") for e in envios):
                        continue
                    _enfileirar(titulo, f.name, "pasta")
        except Exception:
            pass
        time.sleep(15)


def glob_escape(t: str) -> str:
    return re.sub(r"([\[\]*?])", r"[\1]", t)


def trabalhador() -> None:
    """Separa os envios em espera, um por vez, chamando o separar.py com progresso e pasta temporária própria."""
    while True:
        with trava:
            e = next((x for x in envios if x["estado"] == "espera"), None)
            if e:
                e.update(estado="separando", inicio=time.time(), etapa="preparo", total=0.0)
                salvar_fila()
        if not e:
            OCUPADO.unlink(missing_ok=True)
            acordar.wait(5)
            acordar.clear()
            continue
        OCUPADO.write_text(e["id"], encoding="utf-8")
        prog = ENVIOS / f"{e['id']}.json"
        tmp = f"_tmp_envio_{e['id']}"
        cmd = [PY, str(AQUI / "separar.py"), e["titulo"], "--exato", "--refazer", "--progresso", str(prog), "--tmp", tmp]
        if e["rotulo"]:
            cmd += ["--rotulo", e["rotulo"]]
        log = open(ENVIOS / f"{e['id']}.log", "w", encoding="utf-8")
        proc = subprocess.Popen(cmd, cwd=AQUI.parent, stdout=log, stderr=subprocess.STDOUT, creationflags=SEM_JANELA,
                                env=dict(os.environ, HF_HUB_DISABLE_SYMLINKS_WARNING="1", PYTHONUNBUFFERED="1"))
        processo_atual.update(id=e["id"], proc=proc)
        while proc.poll() is None:
            try:
                p = json.loads(prog.read_text(encoding="utf-8"))
                with trava:
                    e.update(etapa=p["etapa"], total=p["total"])
            except Exception:
                pass
            time.sleep(0.5)
        log.close()
        processo_atual.clear()
        pasta = FAIXAS / e["pasta"]
        with trava:
            if e["estado"] == "cancelada":
                pass
            elif proc.returncode == 0 and len(list(pasta.glob("*.flac"))) >= 6:
                e.update(estado="pronta", total=1.0, etapa="acabamento", fim=time.time())
            else:
                fim_log = (ENVIOS / f"{e['id']}.log").read_text(encoding="utf-8", errors="replace").strip().splitlines()[-3:]
                e.update(estado="erro", fim=time.time(), erro=" · ".join(fim_log)[-300:] or f"código {proc.returncode}")
            salvar_fila()
        prog.unlink(missing_ok=True)
        subprocess.run(["cmd", "/c", "rmdir", "/s", "/q", str(FAIXAS / tmp)], capture_output=True, creationflags=SEM_JANELA)


def cancelar(id_: str) -> bool:
    with trava:
        e = next((x for x in envios if x["id"] == id_), None)
        if not e or e["estado"] not in ("espera", "separando"):
            return False
        e.update(estado="cancelada", fim=time.time())
        salvar_fila()
    if processo_atual.get("id") == id_:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(processo_atual["proc"].pid)], capture_output=True, creationflags=SEM_JANELA)
    return True


# ---------------------------------------------------------------- HTTP

class Mesa(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def json(self, obj, codigo=200):
        corpo = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def translate_path(self, path):
        """/faixas/… vem de dados/faixas/; o resto, da pasta mesa/."""
        p = urlparse(path).path
        if p.startswith("/faixas/"):
            alvo = (FAIXAS / unquote(p[len("/faixas/"):])).resolve()
            return str(alvo) if alvo.is_relative_to(FAIXAS.resolve()) else str(FAIXAS / "_nada")
        return super().translate_path(path)

    def do_GET(self):
        caminho = urlparse(self.path).path
        if caminho == "/mixer.html":   # endereço antigo
            self.send_response(301)
            self.send_header("Location", "/")
            self.end_headers()
            return
        if caminho == "/catalogo.json":
            importlib.reload(catalogo)   # mudanças no catalogo.py valem sem reiniciar o servidor
            return self.json(catalogo.gerar())
        if caminho == "/envios.json":
            with trava:
                lista = [dict(e) for e in envios if e["estado"] != "cancelada" or time.time() - (e["fim"] or 0) < 60]
            return self.json({"envios": lista[-30:]})
        super().do_GET()

    def do_POST(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path == "/enviar":
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0 or n > MAX_BYTES:
                return self.json({"erro": "arquivo vazio ou maior que 400 MB"}, 400)
            corpo = self.rfile.read(n)
            try:
                e = novo_envio(unquote(q.get("titulo", "")), unquote(q.get("arquivo", "audio")), corpo)
            except ValueError as err:
                return self.json({"erro": str(err)}, 400)
            return self.json(e)
        if u.path == "/cancelar":
            return self.json({"ok": cancelar(q.get("id", ""))})
        self.send_error(404)

    def log_message(self, *a):   # sem poluir o terminal a cada arquivo de áudio
        pass


if __name__ == "__main__":
    carregar_fila()
    threading.Thread(target=trabalhador, daemon=True).start()
    threading.Thread(target=vigiar_pasta, daemon=True).start()
    handler = functools.partial(Mesa, directory=str(MESA))
    servidor = http.server.ThreadingHTTPServer(("127.0.0.1", PORTA), handler)   # só o próprio computador acessa
    url = f"http://127.0.0.1:{PORTA}/"
    print(f"Mesa em {url}  (Ctrl+C para fechar)")
    if "--sem-abrir" not in sys.argv:
        webbrowser.open(url)
    servidor.serve_forever()
