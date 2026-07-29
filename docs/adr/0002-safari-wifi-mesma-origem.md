# ADR 0002 — Safari e comunicação Wi-Fi na mesma origem

- Estado: aceito
- Data: 2026-07-28

## Contexto

A placa deve ficar separada do telefone/computador e comunicar apenas por
Wi-Fi. O app precisa funcionar no Safari. Uma página pública HTTPS não pode
abrir com confiabilidade um WebSocket inseguro `ws://` em um endereço privado,
pois isso é conteúdo misto ativo.

## Decisão

A ESP32-S3 anuncia `rf-sense.local` por mDNS e serve:

- a aplicação estática em `http://rf-sense.local/`;
- o fluxo binário wire v1 em `ws://rf-sense.local/ws/csi`;
- diagnóstico não sensível em `http://rf-sense.local/health`.

O Safari navega para o endereço local, portanto documento e WebSocket têm a
mesma origem e o mesmo nível de transporte. O JavaScript processa CSI em memória
e não envia I/Q para a Internet.

O agregador Python continua disponível para operação contínua e malha: recebe
UDP das placas e serve o mesmo dashboard em um endereço local. Netlify hospeda
a demonstração e pode conduzir o usuário por navegação de topo até o endereço
local, mas não participa do fluxo CSI ao vivo.

## Consequências

- Safari no iPhone/iPad/Mac é suportado sem Web Serial ou cabo.
- O dispositivo e a placa precisam estar na mesma rede e sem isolamento de
  clientes Wi-Fi.
- O endereço `.local` depende de mDNS; o IP da placa é o fallback.
- Fechar a aba interrompe o processamento no navegador.
- Multi-nó e automação 24/7 continuam sendo responsabilidade do agregador local.

