"""Abre a mesa no navegador.  Uso:  .venv\\Scripts\\python mixer.py  [--sem-abrir]"""
import functools
import http.server
import importlib
import json
import sys
import webbrowser
from pathlib import Path

import catalogo

PORTA = 8765


class Mesa(http.server.SimpleHTTPRequestHandler):
    """Arquivos do projeto sem cache, e /catalogo.json gerado na hora (músicas novas aparecem sozinhas)."""
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):
        if self.path.split("?")[0] == "/catalogo.json":
            importlib.reload(catalogo)   # mudanças no catalogo.py valem sem reiniciar o servidor
            corpo = json.dumps(catalogo.gerar(), ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)
            return
        super().do_GET()

    def log_message(self, *a):   # sem poluir o terminal a cada arquivo de áudio
        pass


handler = functools.partial(Mesa, directory=str(Path(__file__).parent))
servidor = http.server.ThreadingHTTPServer(("127.0.0.1", PORTA), handler)
url = f"http://127.0.0.1:{PORTA}/mixer.html"
print(f"Mesa em {url}  (Ctrl+C para fechar)")
if "--sem-abrir" not in sys.argv:
    webbrowser.open(url)
servidor.serve_forever()
