# RF Sense

Protótipo local de sensoriamento Wi-Fi por CSI para ESP32-S3. A primeira
entrega implementa os níveis L0/P1 da ficha técnica: protocolo binário,
simulador determinístico, receptor UDP, calibração, processamento de sinais,
API e dashboard. No modo direto, a placa serve o app e transmite CSI por
WebSocket na rede local, permitindo que Safari processe os dados no próprio
dispositivo. Não usa Docker nem recursos externos no navegador.

O estimador v2 faz seleção e consenso entre subportadoras, combina domínio
espectral e autocorrelação para respiração, penaliza harmônicos respiratórios
na estimativa cardíaca e publica qualidade/validade separadas. Consulte a
[revisão técnica](docs/research/estado-da-arte-2026.md) e o
[protocolo de validação](docs/validation/protocolo-sinais-vitais.md).
O dashboard também inclui um
[mapa espacial 3D e contrato de expansão mesh](docs/arquitetura-mapa-mesh-integracoes.md).

> Este é um protótipo de engenharia. Presença e movimento dependem da
> calibração do ambiente. Respiração e frequência cardíaca são estimativas
> experimentais e não podem ser usadas para diagnóstico, emergência ou
> segurança de vida.

## Executar em dois comandos

Requisitos: macOS/Linux e Python 3.11 ou mais recente.

```bash
./scripts/bootstrap.sh
./scripts/run-demo.sh
```

Abra <http://127.0.0.1:8000>. O servidor inicia uma baseline de 600 quadros
(aproximadamente 30 segundos) e o simulador permanece no cenário vazio nesse
período. Depois ele alterna entre pessoa parada e movimento.

O script de bootstrap cria `.venv`, atualiza as ferramentas do ambiente
virtual e instala o projeto localmente nesse ambiente. A instalação não usa
arquivos `.pth`, evitando uma incompatibilidade do Python 3.14 com pastas
ocultas no macOS. Nenhuma dependência é instalada globalmente.

Para instalar o código na placa física, siga o [guia de instalação da
ESP32-S3](docs/instalacao-esp32-s3.md). Ele é separado do modo demonstração
Python e não exige Docker.

## Safari e placa separada por Wi-Fi

O modo de campo não usa USB:

1. A ESP32-S3 entra na mesma rede Wi-Fi do iPhone, iPad ou Mac.
2. A placa anuncia `rf-sense.local` por mDNS e serve este dashboard.
3. O Safari abre `http://rf-sense.local`.
4. A página abre `ws://rf-sense.local/ws/csi` na mesma origem.
5. O próprio navegador faz baseline, features e classificação; CSI bruto fica
   apenas em memória.

Servir página e WebSocket pela mesma origem evita a restrição de conteúdo misto
do Safari. A implantação Netlify funciona como demonstração e porta de entrada:
o botão **Abrir sensor na rede** navega para o endereço local da placa. O modo
ao vivo não tenta abrir `ws://` diretamente a partir da página HTTPS pública.

## Comandos úteis

```bash
# API + receptor UDP, sem simulador
.venv/bin/python -m rf_sense serve

# API + receptor UDP + simulador interno
.venv/bin/python -m rf_sense serve --simulate

# Simulador em outro terminal
.venv/bin/python -m rf_sense simulate --host 127.0.0.1 --port 5005

# Testes
.venv/bin/python -m pytest
```

As configurações também podem ser fornecidas por variáveis de ambiente. Copie
`.env.example` somente como referência; o programa não lê arquivos `.env`
automaticamente para evitar a inclusão acidental de segredos.

## Endpoints

| Método | Endpoint | Função |
|---|---|---|
| `GET` | `/health` | saúde, versão, origem e uptime |
| `GET` | `/api/v1/sensing/latest` | última interpretação |
| `GET` | `/api/v1/nodes` | inventário, FPS, perda e estado |
| `GET` | `/api/v1/vital-signs` | estimativas e validade |
| `GET` | `/api/v1/config` | configuração não secreta |
| `GET` | `/api/v1/spatial/map` | mapa, nós, salas, pessoas e validade |
| `POST` | `/api/v1/spatial/observations` | observações multi-nó para trilateração |
| `POST` | `/api/v1/calibration/start` | reinicia a baseline |
| `GET` | `/ws/sensing` | streaming WebSocket |
| `GET` | `/metrics` | métricas Prometheus sem payload CSI |

O bind HTTP padrão é apenas `127.0.0.1`. Para acesso na LAN, defina
`RF_HTTP_HOST=0.0.0.0` e obrigatoriamente `RF_API_TOKEN`. Nesse caso, envie o
token em `Authorization: Bearer ...`; o WebSocket aceita `?token=...`.

## Estrutura

```text
src/rf_sense/                 agregador, protocolo, DSP, API e UI
protocol/                     contrato wire v1 e vetores dourados
firmware/esp32-s3-node/       projeto ESP-IDF local, sem container
tests/                        protocolo, sequência e pipeline
docs/adr/                     decisões arquiteturais
docs/validation/              gates e roteiro do MVP
docs/privacy/                 classes e retenção de dados
datasets/                     ignorado pelo Git por padrão
```

## Conectar a placa

O receptor escuta UDP `5005`. Ajuste a allowlist para o IP reservado da placa:

```bash
export RF_ALLOWED_SENDERS=192.168.1.50
.venv/bin/python -m rf_sense serve
```

O firmware é compilado com uma instalação local do ESP-IDF v5.4; consulte
[o guia completo de instalação da ESP32-S3](docs/instalacao-esp32-s3.md) e o
[README do firmware](firmware/esp32-s3-node/README.md).

## HomeKit, Alexa e Home Assistant

As três integrações são independentes. HomeKit usa uma bridge HAP local
própria; Alexa usa AWS IoT/Lambda; Home Assistant usa MQTT Discovery. HomeKit e
Alexa não passam pelo Home Assistant. Veja o
[guia de instalação das integrações](docs/integracoes-homekit-alexa-home-assistant.md).

## Limites deliberados desta versão

- Um nó fornece apenas classificação grosseira e zona provável.
- Calibração por ambiente; mover AP, placa ou móveis exige recalibrar.
- CSI bruto só existe em memória e não é persistido.
- Vitals ficam ocultos quando há movimento, janela curta ou confiança baixa.
- O contrato aceita várias pessoas, mas contagem/localização só são marcadas
  válidas com observações de três ou mais nós; o firmware atual ainda exige
  pesquisa e validação multi-alvo antes de alegar essa capacidade em campo.
- Sem identidade biométrica, diagnóstico, queda operacional ou alerta de vida.
