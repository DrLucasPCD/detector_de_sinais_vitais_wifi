# RF Sense wire v1 — CSI bruto

Todos os inteiros multibyte usam little-endian. Cada datagrama UDP ou mensagem
WebSocket binária contém exatamente um quadro. Em transporte serial/stream, o
receptor pode ressincronizar pelo `magic` e calcular o tamanho pelo cabeçalho.

| Offset | Bytes | Campo | Regra |
|---:|---:|---|---|
| 0 | 4 | `magic` | `0xC5110001` |
| 4 | 1 | `node_id` | `u8` |
| 5 | 1 | `n_antennas` | 1–4 |
| 6 | 2 | `n_subcarriers` | 1–512 |
| 8 | 4 | `frequency_mhz` | 2400–2500 |
| 12 | 4 | `sequence` | `u32`, com wrap |
| 16 | 1 | `rssi_dbm` | `i8` |
| 17 | 1 | `noise_floor_dbm` | `i8` |
| 18 | 2 | `flags` | bit 0: primeiro word inválido removido |
| 20 | N×2 | I/Q | pares `i8` por subportadora |

Tamanho total:

```text
20 + n_antennas × n_subcarriers × 2
```

O ESP-IDF documenta CSI como byte imaginário seguido do real. No wire v1, esses
bytes são preservados e nomeados `I` e `Q` nessa ordem. Uma mudança futura de
ordem ou escala exige novo flag/schema e vetor dourado.

## Transportes

- `ws://rf-sense.local/ws/csi`: modo Safari, página e socket na mesma origem.
- UDP `5005`: agregador local opcional, com allowlist de IP.

O WebSocket não altera o payload. O parser Python e o parser JavaScript devem
aceitar os mesmos vetores dourados.

