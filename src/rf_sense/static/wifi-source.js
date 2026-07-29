import { BrowserEngine, SerialFrameParser } from "./browser-engine.js";

export class DirectWiFiSource {
  constructor(callback, statusCallback) {
    this.callback = callback;
    this.statusCallback = statusCallback;
    this.socket = null;
    this.parser = new SerialFrameParser();
    this.engine = new BrowserEngine(600, "wifi-direct");
    this.reconnectTimer = null;
    this.manualClose = false;
  }

  get connected() {
    return this.socket?.readyState === WebSocket.OPEN;
  }

  connect(url = directSocketUrl()) {
    this.disconnect();
    this.manualClose = false;
    this.statusCallback("Conectando ao sensor pela rede local…");
    this.socket = new WebSocket(url);
    this.socket.binaryType = "arraybuffer";
    this.socket.addEventListener("open", () => {
      this.statusCallback("ESP32 conectada diretamente por Wi-Fi.");
    });
    this.socket.addEventListener("message", (event) => {
      if (!(event.data instanceof ArrayBuffer)) return;
      const frames = this.parser.push(new Uint8Array(event.data));
      frames.forEach((frame) => this.callback(this.engine.process(frame)));
    });
    this.socket.addEventListener("close", () => {
      if (this.manualClose) return;
      this.statusCallback("Sensor desconectado; nova tentativa em 2 segundos.");
      this.reconnectTimer = window.setTimeout(() => this.connect(url), 2000);
    });
    this.socket.addEventListener("error", () => {
      this.statusCallback("A ESP32 não respondeu em /ws/csi.");
    });
  }

  resetCalibration() {
    this.engine.reset();
  }

  disconnect() {
    this.manualClose = true;
    if (this.reconnectTimer) window.clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
    this.socket?.close();
    this.socket = null;
  }
}

export function directSocketUrl() {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws/csi`;
}

export function isPublicHostedPage() {
  const host = window.location.hostname;
  if (["localhost", "127.0.0.1"].includes(host)) return false;
  if (host.endsWith(".local")) return false;
  if (/^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)/.test(host)) return false;
  return window.location.protocol === "https:";
}

