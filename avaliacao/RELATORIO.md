# Avaliação da separação de faixas (MUSDB18 amostra)

Gerado por `avaliacao/avaliar.py`. 1 trechos de ~7 s da divisão *test*, cada um em duas condições: **estéreo** (original) e **mono** ((L+R)/2 duplicado, como o vinil mono). SDR = nSDR do desafio MDX (`10·log10(Σs²/Σ(s−ŝ)²)`, trecho inteiro), em dB, maior é melhor. Guitarra + piano + outros das saídas de 6 faixas foram somados em *other*. Stems de referência mais de 40 dB abaixo da mistura foram ignorados (n = trechos válidos).

## Voz e baixo (mediana do SDR, dB)

| técnica | vocals estereo | vocals mono | bass estereo | bass mono |
|---|---|---|---|---|
| E (produção) | 13.19 (n=1) | 13.14 (n=1) | 3.34 (n=1) | 3.71 (n=1) |
| SW direto | 13.72 (n=1) | 13.82 (n=1) | 3.29 (n=1) | 3.69 (n=1) |
| Demucs ft | 11.11 (n=1) | 11.82 (n=1) | 3.37 (n=1) | 2.93 (n=1) |
| E + baixo médio | 13.19 (n=1) | 13.14 (n=1) | 3.75 (n=1) | 3.85 (n=1) |

## Bateria e outros (mediana do SDR, dB)

| técnica | drums estereo | drums mono | other estereo | other mono |
|---|---|---|---|---|
| E (produção) | 11.87 (n=1) | 11.22 (n=1) | 0.41 (n=1) | 0.33 (n=1) |
| SW direto | 11.91 (n=1) | 11.36 (n=1) | 0.41 (n=1) | 0.32 (n=1) |
| Demucs ft | 7.33 (n=1) | 6.12 (n=1) | 0.95 (n=1) | 0.64 (n=1) |
| E + baixo médio | 11.87 (n=1) | 11.22 (n=1) | 0.75 (n=1) | 0.45 (n=1) |

## Vazamento do baixo (mediana)

Fração da energia do baixo verdadeiro em 40–300 Hz que aparece em cada faixa estimada: projeção do erro da faixa no baixo, `<b, ŝ_k − s_k>/<b, b>`, tudo filtrado em 40–300 Hz (com separação perfeita dá 0; projetar o erro desconta o que guitarra ou bumbo verdadeiros já têm de parecido com o baixo). *vazamento* = soma nas faixas que não são o baixo; menor é melhor. *capturado* perto de 1 é o ideal.

| técnica | condição | capturado | vazamento | → voz | → bateria | → other (guit./piano/outros) |
|---|---|---|---|---|---|---|
| E (produção) | estereo | 92.5% | 7.3% | 0.0% | 1.6% | 5.7% |
| E (produção) | mono | 89.7% | 9.7% | -0.0% | 4.0% | 5.8% |
| SW direto | estereo | 92.5% | 7.3% | 0.1% | 1.5% | 5.7% |
| SW direto | mono | 90.3% | 9.1% | 0.1% | 3.3% | 5.8% |
| Demucs ft | estereo | 75.2% | 24.5% | 0.1% | 11.4% | 13.0% |
| Demucs ft | mono | 73.1% | 21.1% | 0.1% | 14.3% | 6.7% |
| E + baixo médio | estereo | 85.3% | 14.4% | 0.0% | 1.6% | 12.8% |
| E + baixo médio | mono | 81.7% | 17.8% | -0.0% | 4.0% | 13.8% |

## Vitórias trecho a trecho (mono)

Em quantos trechos cada técnica teve o maior SDR.

| stem | E (produção) | SW direto | Demucs ft | E + baixo médio |
|---|---|---|---|---|
| vocals | 0 | 1 | 0 | 0 |
| bass | 0 | 0 | 0 | 1 |

## Tempo de GPU

| etapa | itens | segundos |
|---|---|---|
| E: Kim (voz) | 2 | 26 |
| E: SW (instrumental) | 2 | 19 |
| SW direto | 2 | 18 |
| Demucs ft (mistura) | 2 | 24 |
| Demucs ft (instrumental, p/ E+medio) | 2 | 34 |
| **total** | | **122** |
