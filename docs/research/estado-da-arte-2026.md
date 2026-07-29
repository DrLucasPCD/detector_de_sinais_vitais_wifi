# Estado da arte aplicado — sinais vitais por Wi‑Fi CSI

Revisão técnica: 28 de julho de 2026.

## Conclusão

Respiração é o alvo mais viável com ESP32 e Wi‑Fi comum. Frequência cardíaca
também pode aparecer no CSI, mas a deformação mecânica é menor, a relação
sinal/ruído é pior e a validação publicada ainda é menos generalizável.
Nenhum número de acurácia de outro laboratório deve ser transferido para este
produto sem campanha própria.

## Evidência usada

- **VitalCSI (Sensors, 2026)**: 15 voluntários, referência por fluxo nasal,
  faixa de 6–33 rpm, MAE de 1,20 rpm. Combina PCA, estimativa espectral,
  contagem temporal, SQI e filtro de Kalman. O desenho do nosso estimador segue
  a ideia de estimadores independentes + qualidade + fusão, mas não copia o
  modelo treinado.
  <https://doi.org/10.3390/s26010225>
- **WiRM (2025/IEEE 2026)**: multiplicação conjugada para saneamento de fase,
  rastreamento adaptativo e seleção de forma de onda; relata redução média de
  38% no RMSE de frequência respiratória frente a comparadores.
  <https://arxiv.org/abs/2507.23419>
- **SA‑WiSense (2025)**: razão entre subportadoras para cancelar deslocamentos
  de fase e mitigar pontos cegos em dispositivo de antena única; validado com
  ESP32. Isso motivou as features de razão entre subportadoras deste projeto.
  <https://arxiv.org/abs/2507.17623>
- **RespirFi (preprint, 2026)**: seleção adaptativa, alinhamento de tendência e
  diferenças entre subportadoras para robustez à posição. É evidência recente,
  ainda não suficiente para alegação clínica.
  <https://arxiv.org/abs/2604.20397>
- **BreatheSmart — NIST/FDA (IEEE Access, 2022)**: caracteriza efeitos de
  posição, orientação, atenuação, taxa de quadros e AGC; reforça que resultados
  controlados não garantem desempenho em casas.
  <https://doi.org/10.1109/ACCESS.2022.3230003>
- **Monitor cardíaco por CSI (Sensors, 2024)**: demonstra viabilidade e seleção
  de subportadoras para frequência cardíaca, mas não elimina a necessidade de
  validação externa por ambiente e pessoa.
  <https://doi.org/10.3390/s24072111>
- **ESP‑IDF / ESP32‑S3**: o CSI contém I/Q por subportadora; a primeira palavra
  pode ser inválida por limitação do hardware, e o callback executa na tarefa
  de Wi‑Fi. O firmware remove sempre essa palavra, filtra pelo BSSID e delega
  transmissão a uma fila.
  <https://docs.espressif.com/projects/esp-idf/en/v5.4.4/esp32s3/api-guides/wifi.html>

## Solução implementada

O estimador `spectral-consensus-v2` usa:

1. baseline vazio por subportadora;
2. amplitude normalizada e razões entre subportadoras para reduzir AGC e
   deslocamentos comuns;
3. supressão robusta de outliers por mediana/MAD e remoção de deriva linear;
4. pré-seleção das 48 séries mais coerentes;
5. respiração por consenso entre Goertzel/FFT, autocorrelação e múltiplas
   subportadoras;
6. frequência cardíaca por consenso espectral, com penalidade — não remoção
   cega — para harmônicos da respiração;
7. rejeição de movimento;
8. gates de duração, FPS, perda, jitter, SNR, consenso e continuidade temporal;
9. validade e incerteza separadas para respiração e coração.

O número mostrado como `confidence` é um **índice de qualidade do sinal (SQI)
heurístico**, não uma probabilidade calibrada de estar correto. Ele só poderá
ser apresentado como probabilidade depois de calibração em dataset separado,
com pessoas e ambientes nunca vistos no ajuste.

## Topologia recomendada

Para o primeiro protótipo, a ESP32‑S3 receptora usa o roteador como transmissor
e filtra quadros pelo BSSID. Para a maior repetibilidade, a evolução indicada é
usar um segundo nó Wi‑Fi como transmissor dedicado, em canal HT20 fixo e taxa
controlada. O iPhone/iPad/Mac continua sendo apenas a interface Safari; não
participa do enlace de sensoriamento.

Um único indivíduo deve permanecer na zona monitorada. Multiusuário exige
antenas/canais adicionais ou separação espacial e está fora da validade deste
estimador.
