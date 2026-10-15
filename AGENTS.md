# AGENTS.md — roteiro para agentes de IA (Claude Code, Codex, GitHub Copilot, Cursor…)

Este arquivo é para você, agente. A pessoa que te abriu nesta pasta provavelmente quer **instalar e abrir a mesa**.
Leia tudo antes de agir. O README.md é a versão para humanos.

## O que é o projeto
Uma "mesa de volumes" no navegador para ouvir músicas separadas em 6 canais (voz, guitarra, baixo, bateria,
piano, outros) e mixar cada um. A separação usa modelos de IA (BS-Roformer) rodando **no computador da pessoa**.
O projeto **não inclui nenhuma música**: a pessoa usa os próprios arquivos de áudio.

## Regras (obrigatórias)
1. **Peça confirmação antes de baixar ou instalar qualquer coisa**, mostrando o quê e o tamanho aproximado.
   O instalador já mostra a lista; rode `python instalar.py --sim` só **depois** de a pessoa dizer "sim".
2. **Nunca envie áudio da pessoa para fora do computador** (nada de upload para serviços, APIs ou repositórios).
3. **Nunca use serviço pago.** O Colab (opcional, ver abaixo) só com a GPU T4 grátis.
4. **Nunca faça commit** de áudio, faixas e modelos (`dados/`) ou do ambiente (`.venv/`). O `.gitignore` já cobre.
5. Instale tudo **dentro da pasta do projeto** (`.venv/`, `dados/modelos/`). Python e ffmpeg são do sistema: se faltarem,
   explique como instalar e peça permissão antes de rodar qualquer instalador do sistema (ex.: `winget`).
6. Processamentos longos (separar músicas) devem rodar em segundo plano; não bloqueie a conversa.

## Instalar (passo a passo)
```text
1. python verificar.py            # diagnóstico: o que está pronto e o que falta (não instala nada)
2. mostre o resultado à pessoa e o plano:   python instalar.py   (ele lista o que vai baixar e pergunta s/n)
   - se a pessoa concordar, rode:           python instalar.py --sim
3. python verificar.py            # deve terminar com "Tudo pronto" (código de saída 0)
4. abra a mesa:                   iniciar.bat   (ou .venv\Scripts\python separador\servidor.py)  → http://127.0.0.1:8765/
```
Tamanhos aproximados: PyTorch com CUDA ~2,5 GB (DirectML ~250 MB; só CPU ~200 MB), bibliotecas ~300 MB, 2 modelos ~1,3 GB.
O instalador escolhe sozinho: placa NVIDIA → CUDA; placa AMD/Intel no Windows → DirectML (torch 2.4.1 + torch-directml,
experimental); sem placa → CPU (funciona, mas é bem mais lenta). `separar.py` usa a DirectML só quando não há CUDA.

Requisitos: **Windows 10/11** (o núcleo é Python puro e deve funcionar em Mac/Linux, mas não foi testado lá),
Python 3.10+ (recomendado 3.12), ffmpeg no PATH.

## Usar
- **Aba "enviar"** da mesa: soltar um arquivo de áudio → a separação roda no servidor local → a música aparece no
  disco certo (se o nome bater com uma faixa dos discos) ou em **All Songs**.
- **Pasta**: copiar arquivos de áudio para `dados/musicas/` (raiz) também funciona — o servidor percebe e separa sozinho.
- **Linha de comando**: `.venv\Scripts\python separador\separar.py "nome da música"` separa um arquivo de `dados/musicas/`.
- Formatos: mp3, wav, flac, m4a, ogg, webm, opus. Tempo por música: ~2–7 min com GPU NVIDIA; dezenas de minutos só com CPU; AMD/Intel (DirectML) fica no meio.

## Mapa do código
| Arquivo | Papel |
|---|---|
| `mesa/` | a página, sem dependências: `index.html` (estrutura), `mesa.css` (visual), `mesa.js` (discos, mesa de som, aba enviar), `imagens/` |
| `separador/servidor.py` | servidor local (127.0.0.1:8765): a página, `/faixas/…` (= `dados/faixas/`), `/catalogo.json`, `/enviar`, `/envios.json`, `/cancelar`, pasta vigiada |
| `separador/separar.py` | separação em 6 faixas (técnica "F": voz = média SW + Viperx; depois o SW separa o resto do instrumental) |
| `separador/catalogo.py` | monta os discos e as faixas; encaixa cada música separada no disco certo pelo nome |
| `separador/discos.json` | faixas de referência de cada disco (a estante fica completa mesmo sem músicas) |
| `verificar.py`, `instalar.py`, `*.bat` | diagnóstico, instalação e atalhos |
| `avaliacao/` | avaliação objetiva (SDR no MUSDB18) e otimização que escolheram a técnica atual |
| `ferramentas/` | infraestrutura pessoal do autor (fila em duas máquinas, vigia, Colab). **Não é necessária** para usar a mesa |

Dados gerados (fora do git), todos em `dados/`: `musicas/` (áudio da pessoa), `faixas/<música>/*.flac` (as 6 faixas), `modelos/`, `registros/` (logs). Além deles, `.venv/`.

## Verificação rápida depois de mudanças
- `python verificar.py` termina com "Tudo pronto".
- `curl http://127.0.0.1:8765/catalogo.json` responde com os discos.
- Na aba enviar, um trecho curto de áudio passa por: envio → preparo → voz → voz (2º modelo) → instrumentos → acabamento.

## Problemas comuns
- **"ffmpeg não encontrado"**: instale (Windows: `winget install Gyan.FFmpeg`) com a permissão da pessoa e abra um terminal novo.
- **Há placa NVIDIA mas o verificar diz CPU**: o PyTorch instalado é o de CPU → rode o instalador de novo.
- **Placa AMD/Intel com erro na separação**: a DirectML é experimental; para forçar a CPU, desinstale `torch-directml` da `.venv`.
- **Porta 8765 ocupada**: já existe uma mesa aberta; use-a ou feche o processo `separador/servidor.py`.
- **Engasgos no som / pouca RAM**: separar e ouvir ao mesmo tempo num PC com pouca memória pode engasgar; espere a separação terminar.

## Opcional: GPU grátis do Google Colab
Para quem não tem placa de vídeo. Exige WSL (Ubuntu) com o `colab` CLI e login Google feito **pela própria pessoa**.
Veja `avaliacao/colab.sh` e `separador/separar.py --colab`. Só a T4 grátis; quando a cota acaba, o Google recusa ("Service Unavailable").

## Este projeto não aceita contribuições
É um projeto pessoal de demonstração: sem suporte, issues ou pull requests. Quem quiser mudar algo deve fazer um fork.
