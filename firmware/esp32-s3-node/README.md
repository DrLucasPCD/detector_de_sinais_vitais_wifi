# Firmware ESP32-S3 — nó RF Sense

Alvo obrigatório: **ESP32-S3-DevKitC-1 N8R8**. Este projeto usa ESP-IDF v5.4
instalado localmente; Docker não é necessário.

Para o procedimento completo, incluindo porta USB, primeira gravação, modo
BOOT/RESET, verificação no Safari e solução de problemas, consulte o
[guia de instalação](../../docs/instalacao-esp32-s3.md).

## Instalar o ESP-IDF no macOS

Siga a instalação oficial da Espressif para v5.4 e carregue o ambiente:

```bash
source "$HOME/esp/esp-idf/export.sh"
idf.py --version
```

Se ainda não instalou o ESP-IDF, siga primeiro o
[guia de instalação](../../docs/instalacao-esp32-s3.md).

## Configurar, compilar e gravar

```bash
cd firmware/esp32-s3-node
idf.py set-target esp32s3
idf.py -DSDKCONFIG_DEFAULTS="sdkconfig.defaults;sdkconfig.defaults.devkitc" menuconfig
idf.py -DSDKCONFIG_DEFAULTS="sdkconfig.defaults;sdkconfig.defaults.devkitc" build
idf.py -DSDKCONFIG_DEFAULTS="sdkconfig.defaults;sdkconfig.defaults.devkitc" -p /dev/cu.SUA_PORTA flash monitor
```

Em `RF Sense`, configure SSID 2,4 GHz, senha, `node_id` e hostname. `sdkconfig`
é ignorado pelo Git porque contém a credencial. O build gera e grava também a
partição `storage` com o dashboard.

Após obter IP, o monitor serial mostra apenas:

```text
Dashboard: http://rf-sense.local
CSI wire v1 ativo em ws://rf-sense.local/ws/csi
```

Abra o primeiro endereço no Safari de um dispositivo na mesma rede. A placa
serve a UI e transmite quadros binários em `/ws/csi`; o navegador faz o
processamento. O CSI bruto não sai da LAN.

## Transporte opcional para agregador

Ative `RF_UDP_ENABLED` no menuconfig e configure o IP do computador/Raspberry
Pi para enviar simultaneamente wire v1 à porta UDP 5005. Isso é recomendado
para operação 24/7, retenção controlada e futura malha com vários nós.

## Segurança e limites

- Não exponha a porta HTTP da placa na Internet.
- Use uma rede local confiável e sem isolamento entre clientes.
- O HTTP local não oferece confidencialidade contra outros participantes da
  mesma LAN; uma versão de produto exige TLS/provisionamento e autenticação.
- A fila CSI e o pool WebSocket são limitados; saturação descarta quadros e
  incrementa métricas, nunca bloqueia o callback Wi-Fi.
- O callback usa somente LLTF para estabilizar o layout de subportadoras.
- Respiração e frequência cardíaca continuam experimentais e não médicas.
