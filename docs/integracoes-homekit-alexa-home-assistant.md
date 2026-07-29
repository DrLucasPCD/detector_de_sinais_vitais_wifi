# Integrações independentes

## Apple Casa / HomeKit direto

O processo RF Sense abre uma bridge HAP própria na rede local usando
HAP-python. Para cada ambiente, cria sensores nativos de ocupação e movimento:

```text
RF Sense -> HAP/Bonjour local -> app Casa
```

Instalação:

```bash
.venv/bin/pip install -e '.[homekit]'
export RF_HOMEKIT_ENABLED=1
export RF_HOMEKIT_PIN=031-45-154
.venv/bin/python -m rf_sense serve
```

O iPhone e o computador que executa RF Sense devem estar na mesma rede. No app
Casa, adicione um acessório e use o PIN configurado. O arquivo
`RF_HOMEKIT_PERSIST_FILE` guarda o pareamento; faça backup e não o publique.

O HomeKit não possui características padrão para mapa 3D, respiração ou
frequência cardíaca ambiental. A bridge expõe somente ocupação/movimento, que
o app Casa entende de forma nativa. O mapa e os vitais permanecem no painel RF
Sense. Para produto comercial, verifique os requisitos atuais de certificação
e licenciamento da Apple; esta bridge é uma implementação de protótipo.

## Alexa direta

A Alexa não acessa um endereço privado da LAN. O RF Sense publica seu estado,
com TLS mútuo, em um AWS IoT Thing Shadow. A Lambda incluída atende
`Alexa.Discovery`, `Alexa.ReportState` e os intents personalizados:

```text
RF Sense -> AWS IoT -> Lambda RF Sense -> Alexa
```

Não há Home Assistant nesse caminho.

Arquivos:

- `integrations/alexa/lambda_function.py`: Smart Home e consultas por voz;
- `integrations/alexa/template.yaml`: implantação AWS SAM;
- `integrations/alexa/interaction-model-pt-BR.json`: modelo pt-BR.

Etapas:

1. Crie um Thing no AWS IoT e baixe certificado, chave e CA.
2. Aplique uma policy limitada ao shadow desse Thing.
3. Instale o cliente MQTT: `.venv/bin/pip install -e '.[integrations]'`.
4. Configure `RF_AWS_IOT_ENDPOINT`, `RF_AWS_IOT_CERT`,
   `RF_AWS_IOT_KEY`, `RF_AWS_IOT_CA` e `RF_ALEXA_IOT_ENABLED=1`.
5. Em `integrations/alexa`, execute `sam build && sam deploy --guided`.
6. Crie a Smart Home Skill no Alexa Developer Console, selecione a Lambda e
   configure o account linking exigido pela Amazon.
7. Para vitais e contagem, crie também uma Custom Skill com a mesma Lambda e
   importe o modelo pt-BR.

Na Smart Home API, cada sala aparece como sensor de movimento. Consultas de
contagem e vitais usam a Custom Skill, porque não existem propriedades Smart
Home nativas para esses valores. A resposta verbal sempre qualifica vitais
como experimentais.

## Home Assistant independente

Este conector publica MQTT Discovery diretamente no broker configurado:

```text
RF Sense -> broker MQTT -> Home Assistant
```

Configuração:

```bash
.venv/bin/pip install -e '.[integrations]'
export RF_HOME_ASSISTANT_ENABLED=1
export RF_MQTT_HOST=192.168.1.10
export RF_MQTT_USERNAME=rf_sense
export RF_MQTT_PASSWORD='troque-esta-senha'
.venv/bin/python -m rf_sense serve
```

São publicados, por sala, ocupação, contagem, respiração e frequência
cardíaca. Os dois últimos são marcados no payload como experimentais. Use uma
conta MQTT exclusiva e ACL restrita aos tópicos `rf_sense/#` e aos tópicos de
discovery necessários.

## Independência verificável

`GET /api/v1/config` informa os modos:

- HomeKit: `direct_hap`;
- Alexa: `direct_aws_iot`;
- Home Assistant: `independent_mqtt_discovery`.

Cada integração tem sua própria chave `enabled`, credenciais e ciclo de vida.
Nenhuma classe de HomeKit ou Alexa importa código do Home Assistant.

