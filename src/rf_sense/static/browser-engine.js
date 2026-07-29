const MAGIC = [0x01, 0x00, 0x11, 0xc5];
const HEADER_SIZE = 20;
const MAX_FRAME_SIZE = 4116;

const clamp = (value, low = 0, high = 1) =>
  Math.max(low, Math.min(high, value));

export class SerialFrameParser {
  constructor() {
    this.buffer = new Uint8Array(0);
  }

  push(chunk) {
    const merged = new Uint8Array(this.buffer.length + chunk.length);
    merged.set(this.buffer);
    merged.set(chunk, this.buffer.length);
    this.buffer = merged;
    const frames = [];

    while (this.buffer.length >= HEADER_SIZE) {
      const offset = findMagic(this.buffer);
      if (offset < 0) {
        this.buffer = this.buffer.slice(Math.max(0, this.buffer.length - 3));
        break;
      }
      if (offset > 0) this.buffer = this.buffer.slice(offset);
      if (this.buffer.length < HEADER_SIZE) break;

      const view = new DataView(
        this.buffer.buffer,
        this.buffer.byteOffset,
        this.buffer.byteLength,
      );
      const antennas = view.getUint8(5);
      const subcarriers = view.getUint16(6, true);
      if (antennas < 1 || antennas > 4 || subcarriers < 1 || subcarriers > 512) {
        this.buffer = this.buffer.slice(1);
        continue;
      }
      const frameSize = HEADER_SIZE + antennas * subcarriers * 2;
      if (frameSize > MAX_FRAME_SIZE) {
        this.buffer = this.buffer.slice(1);
        continue;
      }
      if (this.buffer.length < frameSize) break;
      frames.push(parseFrame(this.buffer.slice(0, frameSize)));
      this.buffer = this.buffer.slice(frameSize);
    }
    return frames;
  }
}

function findMagic(buffer) {
  outer: for (let index = 0; index <= buffer.length - MAGIC.length; index += 1) {
    for (let byte = 0; byte < MAGIC.length; byte += 1) {
      if (buffer[index + byte] !== MAGIC[byte]) continue outer;
    }
    return index;
  }
  return -1;
}

function parseFrame(bytes) {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const antennas = view.getUint8(5);
  const subcarriers = view.getUint16(6, true);
  const iq = [];
  for (let offset = HEADER_SIZE; offset < bytes.length; offset += 2) {
    iq.push([view.getInt8(offset), view.getInt8(offset + 1)]);
  }
  return {
    nodeId: view.getUint8(4),
    antennas,
    subcarriers,
    frequencyMhz: view.getUint32(8, true),
    sequence: view.getUint32(12, true),
    rssiDbm: view.getInt8(16),
    noiseFloorDbm: view.getInt8(17),
    flags: view.getUint16(18, true),
    iq,
    receivedAt: performance.now() / 1000,
  };
}

export class BrowserEngine {
  constructor(calibrationFrames = 600, source = "wifi-direct") {
    this.source = source;
    this.calibrationFrames = calibrationFrames;
    this.reset();
  }

  reset() {
    this.calibration = {
      count: 0,
      sums: [],
      squares: [],
      means: null,
      stds: null,
      id: null,
      completedAt: null,
    };
    this.firstAt = null;
    this.lastAt = null;
    this.lastSequence = null;
    this.received = 0;
    this.lost = 0;
    this.timestamps = [];
    this.signal = [];
    this.motionHistory = [];
    this.vitals = {
      breathing_bpm: null,
      heart_bpm: null,
      confidence: 0,
      valid: false,
      experimental: true,
    };
    this.lastVitalUpdate = 0;
  }

  process(frame) {
    const now = frame.receivedAt;
    const amplitudes = frame.iq.map(([i, q]) => Math.hypot(i, q));
    this.firstAt ??= now;
    this.lastAt = now;
    this.received += 1;
    this.timestamps.push(now);
    if (this.timestamps.length > 200) this.timestamps.shift();
    if (this.lastSequence !== null) {
      const forward = (frame.sequence - this.lastSequence) >>> 0;
      if (forward > 0 && forward < 0x80000000) this.lost += Math.max(0, forward - 1);
    }
    this.lastSequence = frame.sequence;

    let presence = null;
    let presenceConfidence = 0;
    let motionState = "unknown";
    let motionPower = 0;
    let variance = 0;
    const reasons = [];

    if (!this.calibration.means) {
      this.observeCalibration(amplitudes, now);
      reasons.push("baseline_em_captura");
    } else if (amplitudes.length === this.calibration.means.length) {
      const zscores = amplitudes.map(
        (value, index) =>
          (value - this.calibration.means[index]) / this.calibration.stds[index],
      );
      variance =
        zscores.reduce((total, value) => total + Math.abs(value), 0) /
        zscores.length;
      const projection =
        zscores.reduce((total, value) => total + value, 0) / zscores.length;
      const previous = this.signal.at(-1)?.value ?? projection;
      this.signal.push({ time: now, value: projection });
      if (this.signal.length > 600) this.signal.shift();
      const delta = projection - previous;
      this.motionHistory.push(delta * delta);
      if (this.motionHistory.length > 80) this.motionHistory.shift();
      motionPower =
        this.motionHistory.reduce((total, value) => total + value, 0) /
        this.motionHistory.length;
      presenceConfidence = clamp((variance - 1.1) / 4);
      presence = presenceConfidence >= 0.52;
      const motionScore = clamp((motionPower - 0.02) / 0.45);
      motionState = presence ? (motionScore >= 0.5 ? "moving" : "still") : "empty";
      if (presence) reasons.push("desvio_da_baseline");
      if (motionState === "moving") reasons.push("energia_temporal_alta");
      if (now - this.lastVitalUpdate >= 1) {
        this.lastVitalUpdate = now;
        this.vitals = estimateVitals(
          this.signal,
          presence,
          motionState,
          presenceConfidence,
        );
      }
    } else {
      reasons.push("layout_csi_mudou");
    }

    const duration =
      this.timestamps.length > 1
        ? this.timestamps.at(-1) - this.timestamps[0]
        : 0;
    const fps = duration > 0 ? (this.timestamps.length - 1) / duration : 0;
    const progress = clamp(this.calibration.count / this.calibrationFrames);
    const state = this.calibration.means ? "BROWSER/LIVE" : "CALIBRATING";

    return {
      source: this.source,
      timestamp_host_ms: Date.now(),
      nodes: [
        {
          node_id: frame.nodeId,
          source: this.source,
          state,
          stale: false,
          frequency_mhz: frame.frequencyMhz,
          rssi_dbm: frame.rssiDbm,
          noise_floor_dbm: frame.noiseFloorDbm,
          snr_db: frame.rssiDbm - frame.noiseFloorDbm,
          fps: round(fps, 2),
          packet_loss: round(this.lost / Math.max(1, this.received + this.lost), 5),
          jitter_ms: round(jitter(this.timestamps) * 1000, 2),
          received: this.received,
          lost: this.lost,
          calibration: {
            id: this.calibration.id,
            frames: this.calibration.count,
            target_frames: this.calibrationFrames,
            progress: round(progress, 3),
            age_s: this.calibration.completedAt
              ? round(now - this.calibration.completedAt, 1)
              : null,
            valid: Boolean(this.calibration.means),
          },
        },
      ],
      features: {
        variance: round(variance, 3),
        motion_power: round(motionPower, 3),
      },
      classification: {
        presence,
        motion_state: motionState,
        confidence: round(presenceConfidence, 3),
        reasons,
      },
      vital_signs: this.vitals,
      alerts: [],
    };
  }

  observeCalibration(amplitudes, now) {
    if (!this.calibration.sums.length) {
      this.calibration.sums = Array(amplitudes.length).fill(0);
      this.calibration.squares = Array(amplitudes.length).fill(0);
    }
    if (amplitudes.length !== this.calibration.sums.length) return;
    amplitudes.forEach((value, index) => {
      this.calibration.sums[index] += value;
      this.calibration.squares[index] += value * value;
    });
    this.calibration.count += 1;
    if (this.calibration.count < this.calibrationFrames) return;
    this.calibration.means = this.calibration.sums.map(
      (value) => value / this.calibration.count,
    );
    this.calibration.stds = this.calibration.squares.map((value, index) => {
      const mean = this.calibration.means[index];
      return Math.max(0.35, Math.sqrt(Math.max(0, value / this.calibration.count - mean * mean)));
    });
    this.calibration.id = crypto.randomUUID().slice(0, 12);
    this.calibration.completedAt = now;
  }
}

function estimateVitals(signal, presence, motionState, presenceConfidence) {
  const empty = {
    breathing_bpm: null,
    heart_bpm: null,
    confidence: 0,
    valid: false,
    experimental: true,
  };
  if (!presence || motionState === "moving" || signal.length < 200) return empty;
  const duration = signal.at(-1).time - signal[0].time;
  if (duration < 10) return empty;
  const sampleRate = (signal.length - 1) / duration;
  const values = signal.map((item) => item.value);
  const breathing = spectralPeak(values, sampleRate, 0.1, 0.5);
  const heart = spectralPeak(values, sampleRate, 0.8, 2);
  const confidence = clamp(
    Math.min(breathing.quality, heart.quality) * presenceConfidence,
  );
  return {
    breathing_bpm: breathing.frequency ? round(breathing.frequency * 60, 1) : null,
    heart_bpm: heart.frequency ? round(heart.frequency * 60, 1) : null,
    confidence: round(confidence, 3),
    valid: confidence >= 0.35,
    experimental: true,
    window_seconds: round(duration, 1),
  };
}

function spectralPeak(input, sampleRate, low, high) {
  const values = input.slice(-600);
  const mean = values.reduce((total, value) => total + value, 0) / values.length;
  const data = values.map(
    (value, index) =>
      (value - mean) *
      (0.54 - 0.46 * Math.cos((2 * Math.PI * index) / Math.max(1, values.length - 1))),
  );
  const duration = data.length / sampleRate;
  const resolution = Math.max(1 / duration, 0.025);
  const samples = [];
  for (
    let frequency = Math.ceil(low / resolution) * resolution;
    frequency <= high + 1e-9;
    frequency += resolution
  ) {
    let real = 0;
    let imaginary = 0;
    const omega = (2 * Math.PI * frequency) / sampleRate;
    data.forEach((value, index) => {
      real += value * Math.cos(omega * index);
      imaginary -= value * Math.sin(omega * index);
    });
    samples.push({ frequency, power: real * real + imaginary * imaginary });
  }
  const peak = samples.reduce(
    (best, sample) => (sample.power > best.power ? sample : best),
    { frequency: null, power: 0 },
  );
  const background =
    samples
      .filter((sample) => sample !== peak)
      .reduce((total, sample) => total + sample.power, 0) /
    Math.max(1, samples.length - 1);
  const ratio = peak.power / Math.max(background, 1e-9);
  return {
    frequency: peak.frequency,
    quality: clamp((ratio - 1.2) / 8),
  };
}

function jitter(timestamps) {
  if (timestamps.length < 3) return 0;
  const intervals = timestamps.slice(1).map((value, index) => value - timestamps[index]);
  const mean = intervals.reduce((total, value) => total + value, 0) / intervals.length;
  const variance =
    intervals.reduce((total, value) => total + (value - mean) ** 2, 0) /
    intervals.length;
  return Math.sqrt(variance);
}

function round(value, digits = 3) {
  return Number(value.toFixed(digits));
}

export class BrowserSimulator {
  constructor(callback) {
    this.callback = callback;
    this.engine = new BrowserEngine(600, "browser-demo");
    this.startedAt = performance.now() / 1000;
    this.sequence = 0;
    this.timer = null;
    this.seed = 42;
    this.phases = Array.from({ length: 64 }, (_, index) => index * 0.43 - 1.7);
    this.base = Array.from({ length: 64 }, (_, index) => 42 + (index % 11) * 1.3);
  }

  start() {
    this.stop();
    this.timer = window.setInterval(() => {
      const now = performance.now() / 1000;
      const elapsed = now - this.startedAt;
      const phase = elapsed < 35 ? -1 : (elapsed - 35) % 60;
      const mode = phase < 0 ? "empty" : phase < 30 || phase >= 45 ? "still" : "moving";
      const frame = this.frame(now, mode);
      this.callback(this.engine.process(frame));
    }, 50);
  }

  stop() {
    if (this.timer) window.clearInterval(this.timer);
    this.timer = null;
  }

  reset() {
    this.engine.reset();
    this.startedAt = performance.now() / 1000;
  }

  frame(now, mode) {
    const breathing = Math.sin(2 * Math.PI * 0.25 * now);
    const heart = Math.sin(2 * Math.PI * 1.2 * now);
    const iq = this.base.map((base, index) => {
      const noise = (this.random() - 0.5) * 0.6;
      let amplitude = base + noise;
      let shift = 0;
      if (mode === "still") {
        amplitude += 3.5 + 1.65 * breathing * (0.75 + (index % 9) / 12) + 0.42 * heart;
        shift = 0.035 * breathing + 0.008 * heart;
      } else if (mode === "moving") {
        amplitude +=
          4 + 6 * Math.sin(2 * Math.PI * 1.7 * now + index * 0.19) +
          (this.random() - 0.5) * 4.4;
        shift = 0.25 * Math.sin(2 * Math.PI * 0.9 * now + index);
      }
      const angle = this.phases[index] + shift;
      return [
        clampInt8(amplitude * Math.cos(angle)),
        clampInt8(amplitude * Math.sin(angle)),
      ];
    });
    const frame = {
      nodeId: 1,
      antennas: 1,
      subcarriers: 64,
      frequencyMhz: 2437,
      sequence: this.sequence,
      rssiDbm: -48,
      noiseFloorDbm: -94,
      flags: 0,
      iq,
      receivedAt: now,
    };
    this.sequence = (this.sequence + 1) >>> 0;
    return frame;
  }

  random() {
    this.seed = (1664525 * this.seed + 1013904223) >>> 0;
    return this.seed / 2 ** 32;
  }
}

function clampInt8(value) {
  return Math.max(-128, Math.min(127, Math.round(value)));
}
