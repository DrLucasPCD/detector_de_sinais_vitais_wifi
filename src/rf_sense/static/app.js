import { BrowserSimulator } from "./browser-engine.js";
import { DirectWiFiSource, isPublicHostedPage } from "./wifi-source.js";

const $ = (selector) => document.querySelector(selector);
const history = { confidence: [], motion: [] };
let currentMode = "waiting";
let latest = null;
let backendSocket = null;

const directWiFi = new DirectWiFiSource(handleUpdate, setSourceMessage);
const browserSimulator = new BrowserSimulator(handleUpdate);

$("#sensorButton").addEventListener("click", () => {
  if (isPublicHostedPage()) {
    const address = window.prompt(
      "Endereço local informado pela placa",
      "http://rf-sense.local",
    );
    if (address) {
      const value = address.trim();
      window.location.assign(
        /^https?:\/\//i.test(value) ? value : `http://${value}`,
      );
    }
    return;
  }
  browserSimulator.stop();
  backendSocket?.close();
  currentMode = "wifi-direct";
  directWiFi.connect();
});

$("#demoButton").addEventListener("click", () => {
  backendSocket?.close();
  browserSimulator.reset();
  browserSimulator.start();
  currentMode = "browser-demo";
  setSourceMessage("Demonstração sintética processada neste navegador.");
});

$("#calibrateButton").addEventListener("click", async () => {
  if (currentMode === "wifi-direct") {
    directWiFi.resetCalibration();
    return;
  }
  if (currentMode === "browser-demo") {
    browserSimulator.reset();
    return;
  }
  try {
    await fetch("/api/v1/calibration/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ frames: 600 }),
    });
  } catch {
    setSourceMessage("Não foi possível reiniciar a calibração.");
  }
});

function handleUpdate(update) {
  latest = update;
  render(update);
}

function render(update) {
  const node = update.nodes?.[0];
  const classification = update.classification ?? {};
  const vitals = update.vital_signs ?? {};
  const calibration = node?.calibration ?? {
    progress: 0,
    frames: 0,
    target_frames: 600,
    valid: false,
  };
  const state = node?.state ?? "AGUARDANDO";
  $("#operationalState").textContent = state;
  $("#statusPanel").dataset.state = state.toLowerCase();
  $("#sourceLabel").textContent = sourceText(update.source, state);

  const presence = classification.presence;
  $("#presenceValue").textContent =
    presence === null || presence === undefined ? "CALIBRANDO" : presence ? "PRESENTE" : "VAZIO";
  $("#presenceDot").classList.toggle("active", presence === true);
  $("#presenceConfidence").textContent =
    presence === null || presence === undefined
      ? "Baseline em captura"
      : `${Math.round((classification.confidence ?? 0) * 100)}% de confiança`;

  const motionLabels = { moving: "MOVIMENTO", still: "PARADO", empty: "VAZIO", unknown: "—" };
  $("#motionValue").textContent = motionLabels[classification.motion_state] ?? "—";
  $("#motionPower").textContent = update.features?.motion_power == null
    ? "Aguardando baseline"
    : `Potência ${Number(update.features.motion_power).toFixed(3)}`;

  const showVitals = vitals.valid === true;
  $("#breathingValue").textContent = showVitals ? vitals.breathing_bpm ?? "—" : "—";
  $("#heartValue").textContent = showVitals ? vitals.heart_bpm ?? "—" : "—";
  $("#breathingConfidence").textContent = showVitals
    ? `${Math.round((vitals.confidence ?? 0) * 100)}% de confiança`
    : classification.motion_state === "moving"
      ? "Oculto durante movimento"
      : "Aguardando janela estável";
  $("#heartConfidence").textContent = showVitals
    ? "Estimativa experimental"
    : "Não é medição médica";

  const percent = Math.round((calibration.progress ?? 0) * 100);
  $("#calibrationPercent").textContent = `${percent}%`;
  $("#calibrationProgress").style.width = `${percent}%`;
  $("#calibrationRing").style.setProperty("--progress", `${percent * 3.6}deg`);
  $("#calibrationFrames").textContent =
    `${calibration.frames ?? 0} de ${calibration.target_frames ?? 600} quadros`;
  $("#calibrationMessage").textContent = calibration.valid
    ? `Baseline ${calibration.id ?? ""} ativa. Recalibre após mover AP, placa ou móveis.`
    : "Esvazie a área e mantenha ventiladores no estado estável.";

  $("#nodeBadge").textContent = node ? `NÓ ${node.node_id}` : "NÓ —";
  $("#fpsValue").textContent = format(node?.fps, 1);
  $("#lossValue").textContent =
    node?.packet_loss == null ? "—" : `${(node.packet_loss * 100).toFixed(2)}%`;
  $("#rssiValue").textContent = format(node?.rssi_dbm, 0);
  $("#snrValue").textContent = format(node?.snr_db, 0);
  $("#jitterValue").textContent = format(node?.jitter_ms, 1);
  $("#frequencyValue").textContent = format(node?.frequency_mhz, 0);

  history.confidence.push(classification.confidence ?? 0);
  history.motion.push(Math.min(1, (update.features?.motion_power ?? 0) * 2));
  if (history.confidence.length > 120) {
    history.confidence.shift();
    history.motion.shift();
  }
  drawChart();
}

function drawChart() {
  const canvas = $("#signalChart");
  const ratio = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  canvas.width = Math.max(1, rect.width * ratio);
  canvas.height = 230 * ratio;
  const context = canvas.getContext("2d");
  context.scale(ratio, ratio);
  const width = rect.width;
  const height = 230;
  context.clearRect(0, 0, width, height);
  context.strokeStyle = "rgba(142, 185, 168, .11)";
  context.lineWidth = 1;
  for (let y = 20; y < height; y += 42) {
    context.beginPath();
    context.moveTo(0, y);
    context.lineTo(width, y);
    context.stroke();
  }
  drawSeries(context, history.confidence, width, height, "#65efb1", 2.4);
  drawSeries(context, history.motion, width, height, "#f0b96b", 1.8);
}

function drawSeries(context, values, width, height, color, lineWidth) {
  if (values.length < 2) return;
  context.beginPath();
  values.forEach((value, index) => {
    const x = (index / Math.max(1, values.length - 1)) * width;
    const y = height - 18 - value * (height - 40);
    if (index === 0) context.moveTo(x, y);
    else context.lineTo(x, y);
  });
  context.strokeStyle = color;
  context.lineWidth = lineWidth;
  context.shadowBlur = 14;
  context.shadowColor = color;
  context.stroke();
  context.shadowBlur = 0;
}

function setSourceMessage(message) {
  $("#sourceLabel").textContent = message;
}

function sourceText(source, state) {
  if (source === "wifi-direct") return "ESP32 conectada diretamente por Wi-Fi.";
  if (source === "browser-demo") return "Demonstração sintética; alertas reais bloqueados.";
  if (source === "simulator") return "Simulador UDP local; alertas reais bloqueados.";
  if (source === "esp32") return "ESP32 recebida pelo agregador UDP local.";
  return state === "CALIBRATING" ? "Capturando baseline." : "Aguardando fonte.";
}

function format(value, digits) {
  return value === null || value === undefined ? "—" : Number(value).toFixed(digits);
}

async function connectBackend() {
  const isLocal = ["localhost", "127.0.0.1"].includes(window.location.hostname);
  if (!isLocal) return;
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  backendSocket = new WebSocket(`${protocol}//${window.location.host}/ws/sensing`);
  backendSocket.addEventListener("open", () => {
    currentMode = "backend";
    setSourceMessage("Agregador local conectado.");
  });
  backendSocket.addEventListener("message", (event) => {
    handleUpdate(JSON.parse(event.data));
  });
  backendSocket.addEventListener("close", () => {
    if (currentMode === "backend") setSourceMessage("Agregador local desconectado.");
  });
}

window.addEventListener("resize", drawChart);
connectBackend();
if (
  !isPublicHostedPage() &&
  !["localhost", "127.0.0.1"].includes(window.location.hostname)
) {
  currentMode = "wifi-direct";
  directWiFi.connect();
}
render({
  source: "none",
  nodes: [],
  classification: { presence: null, motion_state: "unknown", confidence: 0 },
  features: {},
  vital_signs: { valid: false, confidence: 0 },
});
