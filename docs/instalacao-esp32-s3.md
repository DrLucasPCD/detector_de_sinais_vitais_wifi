# Instalação do firmware na ESP32-S3

Este guia grava o firmware RF Sense na **ESP32-S3-DevKitC-1 N8R8** usando um
Mac. A gravação acontece por USB; depois da gravação, o funcionamento normal
é separado do computador: a placa entra na rede Wi‑Fi e o Safari acessa o
dashboard pela rede local.

> O firmware deste projeto está fixado no ESP-IDF **v5.4.4**. Não misture
> comandos de instalações diferentes do ESP-IDF no mesmo terminal.

## O que você precisa

- ESP32-S3-DevKitC-1 N8R8;
- cabo USB-C **com dados**;
- Mac com acesso à Internet durante a instalação do ESP-IDF;
- rede Wi‑Fi 2,4 GHz (SSID e senha);
- Mac/iPhone/iPad conectado à mesma rede durante o teste;
- este repositório em `/Users/drlucasalbuquerque/Documents/Monitor vital wifi`.

Confirme a memória da placa antes de gravar. O projeto usa uma tabela para
8 MB; uma placa com outra configuração pode exigir outra tabela de partições.

## 1. Instalar o ESP-IDF

Abra o Terminal e execute:

```bash
mkdir -p "$HOME/esp"
cd "$HOME/esp"
git clone -b v5.4.4 --recursive \
  https://github.com/espressif/esp-idf.git
cd "$HOME/esp/esp-idf"
./install.sh esp32s3
source ./export.sh
idf.py --version
```

O último comando deve informar `ESP-IDF v5.4.4`. A documentação oficial
explica a instalação do toolchain e o fluxo de build para ESP32-S3:
[Get Started da Espressif](https://docs.espressif.com/projects/esp-idf/en/latest/esp32s3/get-started/index.html).

O comando `source ./export.sh` vale somente para o terminal atual. Sempre que
abrir um novo terminal antes de usar `idf.py`, execute:

```bash
source "$HOME/esp/esp-idf/export.sh"
```

## 2. Descobrir a porta USB

Com a placa desconectada:

```bash
ls /dev/cu.*
```

Conecte a placa e execute novamente:

```bash
ls /dev/cu.*
```

A porta nova é a porta da placa, por exemplo:

```text
/dev/cu.usbmodem1101
```

Algumas placas aparecem como `/dev/cu.SLAB_USBtoUART` ou
`/dev/cu.usbserial-*`. Use exatamente o nome que apareceu no seu Mac. A
Espressif recomenda comparar a lista antes e depois de conectar a placa:
[conexão serial oficial](https://docs.espressif.com/projects/esp-idf/en/latest/esp32s3/get-started/establish-serial-connection.html).

Se nenhuma porta nova aparecer, teste outro cabo USB, outra porta do Mac e,
se a placa usar conversor USB-UART, instale o driver correspondente.

## 3. Preparar o projeto

```bash
cd "/Users/drlucasalbuquerque/Documents/Monitor vital wifi/firmware/esp32-s3-node"
idf.py set-target esp32s3
```

Agora abra a configuração:

```bash
idf.py \
  -DSDKCONFIG_DEFAULTS="sdkconfig.defaults;sdkconfig.defaults.devkitc" \
  menuconfig
```

Dentro do menu, selecione **RF Sense** e preencha:

| Campo | Valor recomendado |
|---|---|
| SSID da rede 2,4 GHz | nome exato da rede |
| Senha | senha da rede |
| Identificador do nó | `1` |
| Hostname mDNS | `rf-sense` |
| Limite de quadros CSI | `20` |
| Enviar também por UDP | `No` para o primeiro teste |
| Display | `No` na DevKitC sem display |

Salve e saia do menu. A senha fica no `sdkconfig`, que está ignorado pelo
Git; não publique esse arquivo.

### Quando ativar UDP

Deixe UDP desativado no primeiro teste, pois o Safari direto não precisa de
agregador. Para enviar também ao computador/Raspberry Pi, ative **Enviar
wire v1 também por UDP**, informe o IP do agregador e mantenha a porta `5005`.

## 4. Compilar

Ainda na pasta do firmware:

```bash
idf.py \
  -DSDKCONFIG_DEFAULTS="sdkconfig.defaults;sdkconfig.defaults.devkitc" \
  build
```

O build compila o programa e prepara a partição `storage` com o dashboard
Web. Se aparecer erro de componente ou ferramenta ausente, confirme primeiro
que `source "$HOME/esp/esp-idf/export.sh"` foi executado no terminal atual.

## 5. Gravar pela primeira vez

Substitua a porta abaixo pela porta encontrada no seu Mac:

```bash
idf.py \
  -DSDKCONFIG_DEFAULTS="sdkconfig.defaults;sdkconfig.defaults.devkitc" \
  -p /dev/cu.usbmodem1101 \
  flash monitor
```

O comando `flash` grava bootloader, tabela de partições, firmware e dashboard;
`monitor` abre o log serial. O fluxo oficial também documenta a combinação
`idf.py -p PORT flash monitor`:
[build, flash e monitor da Espressif](https://docs.espressif.com/projects/esp-idf/en/latest/esp32s3/get-started/linux-macos-start-project.html).

Se aparecer `No serial data received`, coloque a placa em modo de download:

1. mantenha `BOOT` pressionado;
2. pressione `RESET` uma vez;
3. solte `BOOT`;
4. execute novamente o comando `flash monitor`.

## 6. Verificar o boot

No monitor serial, espere mensagens semelhantes a:

```text
IP obtido: 192.168.1.123
Dashboard: http://rf-sense.local
CSI wire v1 ativo em ws://rf-sense.local/ws/csi
```

A placa deve permanecer sem reinicializações e o log não deve exibir falha de
Wi‑Fi. Pressione `Ctrl+]` para sair do monitor sem apagar o firmware.

## 7. Abrir no Safari

1. Conecte o Mac, iPhone ou iPad à mesma rede 2,4 GHz da placa.
2. Abra no Safari:

   ```text
   http://rf-sense.local
   ```

3. Se o nome `.local` não resolver, use o IP exibido no monitor:

   ```text
   http://192.168.1.123
   ```

4. Aguarde a calibração da baseline com a área vazia.
5. Coloque uma única pessoa parada na posição de teste.
6. Aguarde a janela estável; movimento, ventilador, mudança de posição ou
   móveis novos exigem recalibração.

O navegador abre o WebSocket na mesma origem da página (`/ws/csi`). O CSI
bruto é processado em memória no Safari e não é enviado ao Netlify.

## 8. Gravações seguintes

Depois que o projeto já foi configurado, normalmente basta:

```bash
source "$HOME/esp/esp-idf/export.sh"
cd "/Users/drlucasalbuquerque/Documents/Monitor vital wifi/firmware/esp32-s3-node"
idf.py -p /dev/cu.usbmodem1101 flash monitor
```

Se você alterar SSID, senha, hostname ou opções de `menuconfig`, execute
`menuconfig` novamente antes do `flash`.

## Problemas comuns

| Sintoma | Causa provável | Ação |
|---|---|---|
| `idf.py: command not found` | ambiente não carregado | `source "$HOME/esp/esp-idf/export.sh"` |
| nenhuma `/dev/cu.*` nova | cabo sem dados ou driver | trocar cabo/porta e conferir driver |
| `No serial data received` | placa fora do modo download | sequência `BOOT` + `RESET` |
| Wi‑Fi não conecta | SSID/senha errados ou rede 5 GHz | revisar menuconfig e usar 2,4 GHz |
| `rf-sense.local` não abre | mDNS bloqueado na rede | usar o IP do log |
| dashboard abre, mas não há leitura | clientes isolados ou placa sem tráfego | mesma LAN, desativar isolamento e manter AP estável |
| muitos quadros perdidos | sinal fraco/interferência | aproximar AP/placa e testar canal 2,4 GHz menos congestionado |
| placa reinicia durante captura | alimentação/cabo ou fila saturada | fonte USB estável, cabo curto e reduzir interferência |

## Critério de aceite do primeiro teste

Considere a instalação concluída quando todos estes itens forem verdadeiros:

- `idf.py --version` retorna v5.4.4;
- `flash monitor` termina sem erro;
- o log mostra IP e `CSI wire v1 ativo`;
- `http://rf-sense.local` ou o IP abre no Safari;
- o painel mostra FPS próximo de 20 e perda UDP zero no modo direto;
- a calibração conclui com a sala vazia;
- a presença aparece somente após a pessoa entrar na zona monitorada;
- ao caminhar ou mudar de posição, as estimativas vitais ficam ocultas.

Respiração e frequência cardíaca continuam estimativas experimentais. O
procedimento para comparar os valores com cinta respiratória e ECG/PPG está em
[protocolo de validação](validation/protocolo-sinais-vitais.md).
