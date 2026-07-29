# ADR 0001 — Execução local sem Docker

- Estado: aceito
- Data: 2026-07-28

## Contexto

A ficha técnica recomenda Python/FastAPI para o protótipo e Docker para
empacotamento. O projeto precisa funcionar sem Docker em macOS e Linux, sem
perder isolamento nem reprodutibilidade suficiente para o MVP.

## Decisão

Usar Python 3.11+ com `venv`, dependências declaradas em `pyproject.toml` e
scripts POSIX pequenos. O dashboard é empacotado no próprio pacote e servido
pelo FastAPI. A mesma aplicação estática é gravada na partição de arquivos da
ESP32, que a serve em `rf-sense.local` e publica wire v1 em `/ws/csi`. Assim o
Safari recebe a página e o WebSocket pela mesma origem. O simulador envia o wire
v1 pelo socket UDP real, exercitando também o caminho do agregador.

O firmware usa uma instalação local congelada do ESP-IDF v5.4. A versão será
verificada por `idf.py --version`; não haverá imagem de container.

## Consequências

- Instalação inicial depende de Python e acesso ao índice de pacotes.
- O `.venv` isola pacotes, mas não congela o sistema operacional.
- A reprodução exata deve registrar Python, ESP-IDF, firmware, protocolo e
  configuração em cada sessão.
- Uma futura distribuição poderá usar binários nativos/instaladores sem mudar o
  contrato UDP ou a API.
