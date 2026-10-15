#!/usr/bin/env bash
# Atalhos para rodar a avaliação numa GPU do Colab (rodar dentro do WSL/Ubuntu).
#   bash avaliacao/colab.sh enviar              -> manda o código para o Colab
#   bash avaliacao/colab.sh instalar            -> instala dependências lá
#   bash avaliacao/colab.sh rodar RECEITAS...   -> roda otimizar.py lá (args repassados)
#   bash avaliacao/colab.sh trazer              -> traz otimizacao.jsonl de volta
set -euo pipefail
COLAB="$HOME/.local/bin/colab"
S=sep
LOCAL="$(cd "$(dirname "$0")/.." && pwd)"   # raiz do projeto, vista de dentro do WSL
REMOTO=/content/beatles
TMPPY=$(mktemp --suffix=.py)
trap 'rm -f "$TMPPY"' EXIT
cd "$LOCAL"

executar() {   # executar SEGUNDOS  (código python vem pela entrada padrão)
  cat > "$TMPPY"
  timeout $(( $1 + 60 )) "$COLAB" exec -s "$S" --timeout "$1" -f "$TMPPY"   # limite também do lado de cá (conexão caída)
}

case "${1:-}" in
  enviar)
    echo "import os; os.makedirs('$REMOTO/avaliacao', exist_ok=True); os.makedirs('$REMOTO/separador', exist_ok=True)" | executar 60
    for f in separador/separar.py avaliacao/avaliar.py avaliacao/otimizar.py; do
      "$COLAB" upload -s "$S" "$f" "$REMOTO/$f"
    done ;;
  instalar)
    executar 900 <<EOF
import subprocess
r = subprocess.run('pip -q install "audio-separator[gpu]" musdb soundfile 2>&1 | tail -3; nvidia-smi --query-gpu=name,memory.total --format=csv,noheader; python -c "import torch; print(torch.__version__, torch.cuda.is_available())"', shell=True, capture_output=True, text=True)
print(r.stdout[-3000:], r.stderr[-2000:])
EOF
    ;;
  rodar)
    shift
    executar 7200 <<EOF
import subprocess, os
env = dict(os.environ, PYTHONUNBUFFERED='1', HF_HUB_DISABLE_SYMLINKS_WARNING='1')
r = subprocess.run(['python', '$REMOTO/avaliacao/otimizar.py', *'$*'.split()], capture_output=True, text=True, cwd='$REMOTO', env=env)
linhas = [l for l in (r.stdout + r.stderr).splitlines() if l.startswith(('[', '  [otim', 'Traceback', '  File')) or 'Error' in l]
print('\n'.join(linhas[-60:]))
EOF
    ;;
  monitorar)   # não usa o kernel (que está ocupado rodando): só lista arquivos do cache
    for d in $("$COLAB" ls -s "$S" "$REMOTO/avaliacao/cache_bruto" 2>/dev/null); do
      for t in $("$COLAB" ls -s "$S" "$REMOTO/avaliacao/cache_bruto/$d" 2>/dev/null); do
        echo "$d/$t: $("$COLAB" ls -s "$S" "$REMOTO/avaliacao/cache_bruto/$d/$t" 2>/dev/null | wc -w) trechos"
      done
    done ;;
  separar)     # separar "REL/arquivo.flac" "TITULO": envia a música, separa na T4 e traz as faixas
    REL="$2"; TITULO="$3"; ROT="${4:-}"
    timeout 180 "$COLAB" upload -s "$S" separador/separar.py "$REMOTO/separador/separar.py" >/dev/null
    echo "import os; os.makedirs(os.path.dirname('''$REMOTO/dados/musicas/$REL'''), exist_ok=True)" | executar 60 >/dev/null   # ''' aguenta o apóstrofo de "Don't"
    timeout 300 "$COLAB" upload -s "$S" "dados/musicas/$REL" "$REMOTO/dados/musicas/$REL" >/dev/null
    executar 780 <<EOF
import subprocess, os
env = dict(os.environ, PYTHONUNBUFFERED='1', HF_HUB_DISABLE_SYMLINKS_WARNING='1')
busca = os.path.splitext(os.path.basename('''$REL'''))[0]
rot = '''$ROT'''
r = subprocess.run(['python', 'separador/separar.py', busca, '--exato', '--refazer'] + (['--rotulo', rot] if rot else []), capture_output=True, text=True, cwd='$REMOTO', env=env)
print('\n'.join(l for l in (r.stdout + r.stderr).splitlines() if l.startswith(('[', '  ')) or 'Error' in l))
EOF
    mkdir -p "dados/faixas/$TITULO"
    for st in vocals guitar bass drums piano other; do
      timeout 300 "$COLAB" download -s "$S" "$REMOTO/dados/faixas/$TITULO/$st.flac" "dados/faixas/$TITULO/$st.flac" >/dev/null
    done
    ls "dados/faixas/$TITULO" ;;
  ls)   # ls CAMINHO_REMOTO
    "$COLAB" ls -s "$S" "$2" ;;
  trazer)
    "$COLAB" download -s "$S" "$REMOTO/avaliacao/otimizacao.jsonl" "$LOCAL/avaliacao/otimizacao_colab.jsonl" ;;
  *) echo "uso: enviar | instalar | rodar RECEITAS... | trazer"; exit 1 ;;
esac
