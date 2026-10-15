# Avaliação da separação de faixas

Como a técnica usada pelo `separador/separar.py` foi escolhida. Foco em **voz** e **baixo**.

## Como foi medido
- **Dados:** os 50 trechos de ~7 s da divisão *test* do [MUSDB18](https://sigsep.github.io/datasets/musdb.html) de amostra,
  que tem as faixas originais separadas (gabarito). O áudio do dataset não está no repositório.
- **Mono:** cada trecho foi convertido para mono ((L+R)/2 duplicado), como os discos mono dos Beatles.
- **SDR** (dB, maior é melhor): `10·log10(Σs² / Σ(s−ŝ)²)` no trecho inteiro, como no desafio MDX. Os números são a **mediana** dos 50 trechos.
- **Vazamento do baixo** (menor é melhor): fração da energia do baixo verdadeiro (40–300 Hz) que aparece nas outras faixas.
- Saídas de 6 faixas foram comparadas com as 4 do MUSDB somando guitarra + piano + outros em *other*.
- Código: `avaliar.py` (métricas) e `otimizar.py` (receitas, com cache das saídas de cada modelo). Rodado na GPU T4 grátis do Colab.

## Resultado (50 trechos, mono)

| Técnica | Voz | Baixo | Vazamento do baixo |
|---|---|---|---|
| E — voz do MelBand Kim; o SW separa o resto (versão anterior) | 10,9 dB | 9,1 dB | 8,5% |
| SW direto na mistura | 11,8 dB | 8,9 dB | 8,4% |
| Voz do BS-Roformer Viperx; o SW separa o resto | 12,2 dB | 9,3 dB | 8,1% |
| **F — voz = média(SW, Viperx); o SW separa o resto (atual)** | **12,3 dB** | **9,3 dB** | **7,8%** |
| F + terceiro modelo de voz (BS Gabox) na média | 12,4 dB | 9,3 dB | 8,1% |

A técnica F ficou com o menor vazamento do baixo e praticamente empatada na voz com a variante de 3 modelos,
que é mais lenta. Por isso ela é a atual: **+1,4 dB na voz** e **menos baixo vazando** que a versão anterior.

## Triagem de modelos de voz (15 trechos, mono)

Antes da rodada final, cada modelo de voz foi testado sozinho (a voz dele, e o SW separando o resto):

| Modelo de voz | Voz (mediana) |
|---|---|
| BS-Roformer Gabox | 12,4 dB |
| BS-Roformer Viperx 1297 | 12,4 dB |
| Média Viperx 1297 + 1296 | 12,4 dB |
| BS-Roformer Viperx 1296 | 12,3 dB |
| BS-Roformer revive 3e (unwa) | 12,2 dB |
| MelBand Roformer Kim bleedless (unwa) | 12,0 dB |
| MelBand Roformer FV7b | 11,5 dB |
| MelBand Roformer Kim FT (unwa) | 11,5 dB |
| MelBand Roformer becruily | 11,4 dB |

Os BS-Roformer ficaram à frente dos MelBand na voz. No baixo, as tentativas de pós-processamento (média de passadas,
tirar a bateria antes, mais sobreposição) mudaram ~0,1 dB ou menos: o modelo SW já está perto do limite.

## Limites
- 50 trechos curtos de música pop/rock moderna, não de gravações dos anos 60; a escuta nos discos dos Beatles foi a checagem final.
- A primeira versão do projeto (Demucs) foi medida só num trecho de teste e ficou bem atrás no baixo.
