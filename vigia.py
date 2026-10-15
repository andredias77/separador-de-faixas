"""Vigia da fila noturna: mantém os dois trabalhadores (PC e Colab) rodando e destrava o que emperrar.

A cada minuto:
  - religa o trabalhador do PC ou do Colab se ele não estiver rodando (e ainda houver músicas);
  - se o PC passar TRAVA_PC minutos sem nenhum progresso na pasta temporária, mata e recomeça;
  - libera reservas velhas de músicas que não terminaram (trabalhador morreu no meio);
  - se o Colab falhar seguidamente, tenta recriar a sessão T4 grátis (nunca nada pago);
  - escreve uma linha de situação em vigia.log a cada 10 minutos.
Sai (o que me avisa) quando: a biblioteca inteira terminar, ou algo se repetir sem solução.

Uso:  .venv\\Scripts\\python vigia.py
"""
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import fila
import separar as S

RAIZ = Path(__file__).parent
LOG = RAIZ / "vigia.log"
PY = str(RAIZ / ".venv" / "Scripts" / "python.exe")
COLAB_SH = S.COLAB_SH
TRAVA_PC = 30 * 60          # s sem mexer em faixas/_tmp_roformer = PC travado
RESERVA_VELHA = 50 * 60     # s: reserva de música não terminada e sem dono vivo
SEM_JANELA = 0x08000000      # CREATE_NO_WINDOW: nenhum comando abre janela de terminal
MAX_RELIGAR_COLAB = 4       # religadas seguidas do Colab sem nenhuma música nova = desiste dele
RAM_PAUSA = 0.8             # GB livres: abaixo disso o PC pausa (o Colab quase não usa RAM daqui)
RAM_VOLTA = 2.5             # GB livres por 5 min seguidos para o PC voltar


def log(msg: str) -> None:
    linha = f"{datetime.now():%H:%M} {msg}"
    print(linha, flush=True)
    with open(LOG, "a", encoding="utf-8") as fp:
        fp.write(linha + "\n")


def processos(padrao: str) -> list[int]:
    r = subprocess.run(["powershell", "-NoProfile", "-c",
                        f"Get-CimInstance Win32_Process -Filter \"name='python.exe' or name='pythonw.exe'\" | "
                        f"Where-Object {{ $_.CommandLine -match '{padrao}' }} | ForEach-Object {{ $_.ProcessId }}"],
                       capture_output=True, creationflags=SEM_JANELA, text=True)
    return [int(x) for x in r.stdout.split()]


def matar(padrao: str) -> None:
    for pid in processos(padrao):
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, creationflags=SEM_JANELA)


def ligar(onde: str) -> None:
    saida = open(RAIZ / f"fila_{onde}.log", "a", encoding="utf-8")
    env = dict(os.environ, HF_HUB_DISABLE_SYMLINKS_WARNING="1", PYTHONUNBUFFERED="1")
    subprocess.Popen([PY, "fila.py", f"--{onde}"], cwd=RAIZ, stdout=saida, stderr=subprocess.STDOUT, env=env,
                     creationflags=SEM_JANELA | subprocess.CREATE_NEW_PROCESS_GROUP)
    log(f"liguei o trabalhador do {onde.upper()}")


def colab(*args, timeout=600) -> subprocess.CompletedProcess:
    return subprocess.run(["wsl.exe", "-d", "Ubuntu", "--", "bash", COLAB_SH, *args], capture_output=True, creationflags=SEM_JANELA, text=True,
                          timeout=timeout, env=dict(os.environ, MSYS_NO_PATHCONV="1"))


def recriar_colab() -> bool:
    """Sessão T4 grátis nova + dependências + código. Nunca usa nada pago."""
    log("recriando a sessão do Colab (T4 grátis)")
    try:
        subprocess.run(["wsl.exe", "-d", "Ubuntu", "--", "bash", "-lc", "$HOME/.local/bin/colab stop -s sep; $HOME/.local/bin/colab new -s sep --gpu T4"],
                       capture_output=True, creationflags=SEM_JANELA, text=True, timeout=600, env=dict(os.environ, MSYS_NO_PATHCONV="1"))
        colab("instalar", timeout=1200)
        colab("enviar")
        r = colab("ls", "/content/beatles/separar.py")
        ok = "separar.py" in r.stdout
        log("sessão do Colab recriada" if ok else f"falhou ao recriar o Colab: {r.stdout[-200:]} {r.stderr[-200:]}")
        return ok
    except Exception as e:
        log(f"falhou ao recriar o Colab: {e}")
        return False


def ram_livre_gb() -> float:
    import ctypes

    class MS(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
    m = MS(); m.dwLength = ctypes.sizeof(MS)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return m.ullAvailPhys / 1024 ** 3


def parar_pc(motivo: str) -> None:
    """Para o trabalhador do PC e devolve a música que ele fazia para a fila."""
    log(f"pausando o PC: {motivo}")
    matar("fila.py --pc")
    time.sleep(5)
    tmp = S.FAIXAS / "_tmp_roformer"
    em_andamento = {w.stem for w in tmp.glob("*.wav")} if tmp.exists() else set()
    for f in fila.todas():
        if f.stem in em_andamento:
            (fila.RESERVAS / (S.titulo(f) + ".txt")).unlink(missing_ok=True)
            log(f"  {S.titulo(f)} volta para a fila")
    subprocess.run(["cmd", "/c", "rmdir", "/s", "/q", str(tmp)], capture_output=True, creationflags=SEM_JANELA)


def garantir_mesa() -> None:
    """Mantém o servidor da mesa (mixer.py) no ar."""
    if not processos("mixer.py"):
        saida = open(RAIZ / "mixer.log", "a", encoding="utf-8")
        subprocess.Popen([PY, "mixer.py", "--sem-abrir"], cwd=RAIZ, stdout=saida, stderr=subprocess.STDOUT,
                         creationflags=SEM_JANELA | subprocess.CREATE_NEW_PROCESS_GROUP)
        log("liguei o servidor da mesa")


def prontas() -> int:
    return sum(1 for f in fila.todas() if fila.pronta(f))


def liberar_reservas_velhas() -> None:
    agora = time.time()
    for r in fila.RESERVAS.glob("*.txt"):
        titulo = r.stem
        pronta = (S.FAIXAS / titulo).exists() and len(list((S.FAIXAS / titulo).glob("*.flac"))) >= 6
        if not pronta and agora - r.stat().st_mtime > RESERVA_VELHA:
            r.unlink(missing_ok=True)
            log(f"reserva velha liberada: {titulo}")


def progresso_pc() -> float:
    """Momento da última mudança na pasta temporária do PC (0 se não existe)."""
    tmp = S.FAIXAS / "_tmp_roformer"
    if not tmp.exists():
        return 0
    return max([p.stat().st_mtime for p in tmp.rglob("*")] + [tmp.stat().st_mtime])


def manter_acordado() -> None:
    """Pede ao Windows para não suspender enquanto o vigia roda (não muda nenhuma configuração de energia;
    vale só para este processo e acaba quando ele termina)."""
    import ctypes
    ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
    ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)


def main() -> None:
    manter_acordado()
    log("vigia começou (PC mantido acordado enquanto eu rodo)")
    total = len(fila.todas())
    colab_ativo, religadas_colab, feitas_antes = True, 0, prontas()
    pc_pausado_desde = None
    colab_desligado_em = 0
    ultimo_relatorio = 0
    while True:
        feitas = prontas()
        if feitas >= total:
            log(f"FIM: as {total} músicas da biblioteca estão separadas")
            return
        if feitas > feitas_antes:
            religadas_colab = 0   # houve progresso: zera a contagem de problemas do Colab
        feitas_antes = feitas

        liberar_reservas_velhas()
        garantir_mesa()

        # memória: o PC é quem mais gasta; pausa antes de o sistema apertar
        livre = ram_livre_gb()
        if livre < RAM_PAUSA:
            if processos("fila.py --pc"):
                parar_pc(f"RAM livre baixa ({livre:.1f} GB)")
            pc_pausado_desde = time.time()
        elif livre < RAM_VOLTA and pc_pausado_desde:   # já pausado: só volta com folga sustentada
            pc_pausado_desde = time.time()

        # envio pela aba "enviar" da mesa tem prioridade: a fila grande do PC espera ele terminar
        envio_ocupado = (S.FAIXAS / "_envio_ocupado").exists()
        if envio_ocupado and processos("fila.py --pc"):
            parar_pc("envio pela mesa tem prioridade")

        # PC
        pc = processos("fila.py --pc")
        pc_liberado = pc_pausado_desde is None or (livre >= RAM_VOLTA and time.time() - pc_pausado_desde > 300)
        if pc_liberado:
            pc_pausado_desde = None
        if not pc and pc_liberado and not envio_ocupado and not processos("lote.py"):   # um lote avulso (ex.: Wings) usa a GPU: espera ele
            ligar("pc")
        else:
            ultimo = progresso_pc()
            if ultimo and time.time() - ultimo > TRAVA_PC:
                log(f"PC sem progresso há {int((time.time() - ultimo) / 60)} min: reiniciando")
                matar("fila.py --pc")
                time.sleep(5)
                subprocess.run(["cmd", "/c", "rmdir", "/s", "/q", str(S.FAIXAS / "_tmp_roformer")], capture_output=True, creationflags=SEM_JANELA)
                for r in fila.RESERVAS.glob("*.txt"):   # a música que estava no PC volta para a fila
                    t = r.stem
                    if not ((S.FAIXAS / t).exists() and len(list((S.FAIXAS / t).glob("*.flac"))) >= 6) and time.time() - r.stat().st_mtime > TRAVA_PC:
                        r.unlink(missing_ok=True)
                ligar("pc")

        # Colab: se a T4 grátis não estiver disponível, segue só com o PC e tenta de novo a cada 30 min (nunca para)
        if not colab_ativo and time.time() - colab_desligado_em > 30 * 60:
            colab_ativo, religadas_colab = True, 0
            log("tentando o Colab de novo")
            if not recriar_colab():
                colab_ativo, colab_desligado_em = False, time.time()
                log("Colab ainda indisponível; sigo só com o PC")
        if colab_ativo and not processos("fila.py --colab"):
            religadas_colab += 1
            ok = True
            if religadas_colab > MAX_RELIGAR_COLAB or (religadas_colab >= 2 and not recriar_colab()):
                ok = False
            if ok:
                ligar("colab")
            else:
                colab_ativo, colab_desligado_em = False, time.time()
                log("Colab indisponível (sessão grátis encerrada?); sigo só com o PC e tento de novo em 30 min")

        (RAIZ / "vigia.pulso").write_text(f"{datetime.now():%H:%M:%S}", encoding="utf-8")   # sinal de vida a cada minuto
        if time.time() - ultimo_relatorio > 600:
            reservas = sorted(r.stem for r in fila.RESERVAS.glob("*.txt")
                              if not ((S.FAIXAS / r.stem).exists() and len(list((S.FAIXAS / r.stem).glob("*.flac"))) >= 6))
            log(f"situação: {feitas}/{total} prontas · RAM livre {livre:.1f} GB{' · PC pausado' if pc_pausado_desde else ''} · em andamento: {', '.join(reservas) or '-'}")
            ultimo_relatorio = time.time()
        time.sleep(60)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"vigia caiu: {e!r}")
        sys.exit(1)
