# Mapa 3D, rede mesh e integrações

## Resultado arquitetural

O RF Sense mantém uma única fonte de verdade local (`SpatialEngine`) e possui
três adaptadores independentes:

```text
ESP32-S3 nós -> agregador RF Sense -> painel/mapa 3D (Safari)
                                  ├-> bridge HAP local -> Apple Casa/HomeKit
                                  ├-> AWS IoT Shadow -> Lambda -> Alexa
                                  └-> broker MQTT -> Home Assistant Discovery
```

Desligar ou remover Home Assistant não afeta HomeKit nem Alexa. O inverso
também é verdadeiro.

## Contrato espacial

O arquivo indicado por `RF_ENVIRONMENT_FILE` descreve:

- limites 3D do imóvel em metros;
- salas, posição e tamanho;
- posição fixa e raio de cobertura de cada nó;
- ligações lógicas da malha.

Use `config/environment.example.json` como base. Os IDs dos nós devem ser os
mesmos gravados no firmware.

O endpoint `GET /api/v1/spatial/map` retorna `rf-sense-spatial-v1`, com
ambiente, nós, pessoas anônimas, resumo por sala e validade. O endpoint
autenticado `POST /api/v1/spatial/observations` recebe observações:

```json
{
  "observations": [
    {
      "track_key": "anonymous-a",
      "node_id": 1,
      "distance_m": 2.14,
      "confidence": 0.88,
      "breathing_bpm": 16.2,
      "breathing_confidence": 0.74,
      "heart_bpm": 72,
      "heart_confidence": 0.61
    }
  ]
}
```

Um `track_key` não é identidade biométrica. É apenas uma chave efêmera para
associar observações do mesmo alvo no mesmo instante.

## O que já é calculado

Com três ou mais nós distintos e geometria não colinear, o servidor:

1. resolve a posição XY por mínimos quadrados;
2. calcula erro residual e penalização de geometria;
3. limita a posição às dimensões do mapa;
4. associa a sala;
5. combina sinais vitais ponderados por confiança;
6. expira a trilha após o tempo configurado.

O mapa usa Canvas 2D com projeção 3D, sem bibliotecas externas. Isso reduz
dependências, funciona no Safari e oferece órbita, zoom, seleção e detalhes.

## Limites que o software não pode esconder

Um único enlace Wi-Fi não separa várias pessoas nem fornece coordenadas
confiáveis. Nesse caso, o mapa mostra apenas uma **zona provável**, com
`position_valid=false` e `count_valid=false`.

Três distâncias também não aparecem automaticamente no CSI atual. Antes de
usar contagem/localização em campo, cada nó precisa produzir observações
coerentes do mesmo alvo, por exemplo com fingerprints calibrados por posição,
múltiplos enlaces TX/RX, associação temporal e supressão de multipercurso.

Para várias pessoas, o sistema ainda precisa de um separador multi-alvo
validado. A interface e o contrato já suportam várias trilhas, mas o firmware
atual não deve alegar que as extrai com confiança. Por isso o painel distingue
“confirmado” de “provável”.

## Critérios mínimos de campo

- três ou mais nós ativos para localização 2D;
- nós distribuídos em torno da área, não em linha;
- posições medidas em relação à mesma origem;
- relógios e janelas de observação alinhados;
- erro mediano e percentil 95 documentados por sala;
- testes específicos com 0, 1, 2 e mais pessoas;
- vitais comparados com dispositivo de referência sincronizado.

Os sinais vitais continuam experimentais mesmo quando a localização é válida.
Não são apropriados para diagnóstico, emergência ou decisão de segurança.

