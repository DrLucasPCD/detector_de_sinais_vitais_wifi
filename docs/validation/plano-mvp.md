# Plano de validação do MVP

## Gate L0 — Simulador

- Parser aceita o vetor dourado e rejeita truncamento, magic desconhecido,
  contagens impossíveis e tamanho divergente.
- Uma lacuna em `sequence` incrementa perda sem retransmitir UDP.
- O simulador é determinístico para `seed`, cenário e timestamp equivalentes.
- API, WebSocket e dashboard recebem dados pelo socket UDP real.
- Nenhum payload I/Q é persistido.

## Gate P1 — Backend simulado

1. Iniciar com `./scripts/run-demo.sh`.
2. Confirmar `CALIBRATING` e progresso até 600 quadros.
3. Confirmar origem `simulator` visível no dashboard.
4. Após a baseline, observar presença, pessoa parada e movimento no ciclo.
5. Confirmar que vitals ficam inválidos durante movimento ou confiança baixa.
6. Interromper o simulador e confirmar `STALE` depois de 10 segundos.
7. Executar `pytest` e guardar a versão do ambiente.

## Gate P2/P3 — Placa

- ESP32-S3-DevKitC-1 N8R8 confirmado pela gravação do módulo.
- ESP-IDF v5.4 local e build DevKitC sem display.
- Pelo menos 15 quadros/s medianos, menos de 1% de perda na LAN e 24 horas sem
  reset.
- Baseline de pelo menos 600 quadros na posição final.
- Campanha rotulada antes de alterar thresholds do produto.

As metas de acurácia exigem dataset, protocolo, tamanho amostral e intervalo de
confiança próprios. O simulador testa contratos e comportamento do sistema, não
valida desempenho fisiológico.

