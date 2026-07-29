# Protocolo de validação de sinais vitais

## Regra de liberação

O simulador comprova software, não fisiologia. A leitura real só muda de
“experimental” para “validada no cenário testado” após comparação sincronizada
com referências e teste cego. Não usar para diagnóstico, emergência, apneia,
monitorização de paciente ou segurança de vida.

## Referências simultâneas

- Respiração: cinta respiratória ou pneumotacógrafo/fluxo nasal com timestamp.
- Frequência cardíaca: ECG idealmente; PPG de boa qualidade como referência
  secundária.
- Movimento: acelerômetro no tórax ou anotação sincronizada por protocolo.

Relógio e referência devem ser alinhados antes da sessão. Guardar CSI e
referência somente com consentimento, pseudônimo de sessão e prazo de retenção.

## Fases

### Bancada

- placa e AP fixos;
- 10 minutos sem pessoa para taxa de falso positivo;
- simulador físico periódico, se disponível, para repetibilidade;
- verificar 20–50 fps, perda <1%, jitter <20 ms e SNR >25 dB;
- repetir após reinício e em três canais 2,4 GHz não sobrepostos.

### Piloto humano

Mínimo de 12 adultos para desenvolvimento, sem alegação populacional:

- sentado e deitado; supino e lateral;
- 0,5 m, 1 m, 2 m e 3 m;
- respiração espontânea, lenta e rápida;
- 5 minutos por condição;
- blocos separados de fala, tosse, mudança de postura e caminhada para testar
  rejeição, nunca para produzir uma leitura;
- ventilador desligado/ligado e porta fechada/aberta.

### Teste cego

Congelar algoritmo e thresholds. Avaliar pessoas e pelo menos dois ambientes
que não participaram do desenvolvimento. Separar por participante e ambiente,
nunca embaralhar janelas da mesma pessoa entre treino e teste.

## Métricas obrigatórias

Por sinal e por condição:

- cobertura: fração de janelas em que o sistema publicou valor;
- MAE, RMSE e erro mediano;
- percentual dentro de ±2 rpm para respiração e ±5 bpm para coração;
- viés e limites de concordância de Bland–Altman;
- falso positivo em sala vazia;
- tempo para recuperar validade após movimento;
- curva erro × SQI e calibração do SQI em bins;
- intervalo de confiança por bootstrap agrupado por participante.

Não otimizar apenas MAE: um sistema que omite janelas difíceis pode parecer
preciso com cobertura muito baixa.

## Gates iniciais de engenharia

Estes gates servem para decidir se vale ampliar o estudo; não são critérios
clínicos:

| Métrica | Respiração | Coração |
|---|---:|---:|
| MAE em repouso | ≤ 2 rpm | ≤ 5 bpm |
| Cobertura em repouso | ≥ 85% | ≥ 70% |
| Falso valor durante movimento | ≤ 1% das janelas | ≤ 1% das janelas |
| Sala vazia | zero valores válidos em 8 h | zero valores válidos em 8 h |
| Recuperação pós-movimento | ≤ 60 s | ≤ 90 s |

Se o gate cardíaco falhar, o produto deve manter somente respiração e presença.

## Posicionamento

Começar com AP e receptor a 1–2 m, aproximadamente na altura do tórax, com a
pessoa dentro da primeira zona de Fresnel e sem objetos móveis entre os nós.
Marcar a posição dos equipamentos. Mover AP, receptor ou móveis invalida a
baseline e exige nova calibração.
