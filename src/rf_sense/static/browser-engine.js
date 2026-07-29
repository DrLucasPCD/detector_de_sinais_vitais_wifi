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
    this.csiHistory = [];
    this.motionHistory = [];
    this.vitals = vitalPayload(emptyRate(), emptyRate());
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
      const referenceIndex = this.calibration.means.reduce(
        (best, mean, index) =>
          this.calibration.stds[index] / Math.max(mean, 1e-6) <
          this.calibration.stds[best] / Math.max(this.calibration.means[best], 1e-6)
            ? index
            : best,
        0,
      );
      const referenceAmplitude = Math.max(amplitudes[referenceIndex], 1e-6);
      const referenceMean = Math.max(this.calibration.means[referenceIndex], 1e-6);
      const referenceNoise =
        this.calibration.stds[referenceIndex] / referenceMean;
      const ratioFeatures = amplitudes.flatMap((amplitude, index) => {
        if (index === referenceIndex) return [];
        const mean = Math.max(this.calibration.means[index], 1e-6);
        const baselineRatio = Math.log(mean / referenceMean);
        const currentRatio = Math.log(Math.max(amplitude, 1e-6) / referenceAmplitude);
        const ratioNoise = Math.hypot(
          this.calibration.stds[index] / mean,
          referenceNoise,
        );
        return [(currentRatio - baselineRatio) / Math.max(0.015, ratioNoise)];
      });
      variance =
        zscores.reduce((total, value) => total + Math.abs(value), 0) /
        zscores.length;
      const projection =
        zscores.reduce((total, value) => total + value, 0) / zscores.length;
      const previous = this.signal.at(-1)?.value ?? projection;
      this.signal.push({ time: now, value: projection });
      if (this.signal.length > 1200) this.signal.shift();
      this.csiHistory.push({ time: now, values: [...zscores, ...ratioFeatures] });
      if (this.csiHistory.length > 1200) this.csiHistory.shift();
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
      if (now - this.lastVitalUpdate >= 5) {
        this.lastVitalUpdate = now;
        this.vitals = estimateVitals(
          this.csiHistory,
          presence,
          motionState,
          presenceConfidence,
          motionScore,
          this.lost / Math.max(1, this.received + this.lost),
          jitter(this.timestamps) * 1000,
          frame.rssiDbm - frame.noiseFloorDbm,
          this.vitals,
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
        motion_score: round(
          clamp((motionPower - 0.02) / 0.45),
          3,
        ),
        breathing_power: this.vitals.breathing?.quality?.source ?? null,
        heart_power: this.vitals.heart?.quality?.source ?? null,
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

function emptyRate(method = "spectral-consensus-v2", quality = {}) {
  return {
    value_bpm: null,
    confidence: 0,
    valid: false,
    uncertainty_bpm: null,
    method,
    traces_used: 0,
    quality,
  };
}

function vitalPayload(breathing, heart, duration = 0, motionRejected = false) {
  return {
    breathing_bpm: breathing.value_bpm,
    heart_bpm: heart.value_bpm,
    confidence: breathing.confidence,
    valid: breathing.valid,
    breathing,
    heart,
    motion_rejected: motionRejected,
    experimental: true,
    window_seconds: round(duration, 1),
  };
}

function estimateVitals(
  samples,
  presence,
  motionState,
  presenceConfidence,
  motionScore,
  packetLoss,
  jitterMs,
  radioSnrDb,
  previous,
) {
  const empty = vitalPayload(emptyRate(), emptyRate());
  if (!presence || samples.length < 200) return empty;
  const fullDuration = samples.at(-1).time - samples[0].time;
  if (motionState === "moving" || motionScore >= 0.55) {
    return vitalPayload(emptyRate(), emptyRate(), fullDuration, true);
  }
  if (fullDuration < 10) return empty;

  const cutoff = samples.at(-1).time - 60;
  const windowedSamples = samples.filter((sample) => sample.time >= cutoff);
  const timestamps = windowedSamples.map((sample) => sample.time);
  const duration = timestamps.at(-1) - timestamps[0];
  const width = Math.min(...windowedSamples.map((sample) => sample.values.length));
  let traces = Array.from({ length: width }, (_, index) =>
    prepareTrace(windowedSamples.map((sample) => Number(sample.values[index]))),
  );
  if (traces.length > 48) {
    traces = traces
      .map((trace) => ({ trace, score: smoothnessProxy(trace) }))
      .sort((left, right) => right.score - left.score)
      .slice(0, 48)
      .map((item) => item.trace);
  }

  const fps = (timestamps.length - 1) / Math.max(duration, 1e-9);
  const capture = captureQuality(
    duration,
    fps,
    packetLoss,
    jitterMs,
    radioSnrDb,
  );
  const stillness = clamp(1 - motionScore / 0.9);
  const commonGate =
    clamp(presenceConfidence) * capture * (0.55 + 0.45 * stillness);
  const breathing = estimateRespiration(
    timestamps,
    traces,
    commonGate,
    previous?.breathing?.value_bpm,
  );
  const heart = estimateHeart(
    timestamps,
    traces,
    commonGate,
    breathing.value_bpm,
    previous?.heart?.value_bpm,
  );
  return vitalPayload(breathing, heart, duration);
}

function prepareTrace(input) {
  const center = median(input);
  const mad = median(input.map((value) => Math.abs(value - center)));
  const sigma = Math.max(1e-6, 1.4826 * mad);
  const limit = 4.5 * sigma;
  const clipped = input.map((value) =>
    Math.max(center - limit, Math.min(center + limit, value)),
  );
  const count = clipped.length;
  const indexCenter = (count - 1) / 2;
  const denominator = clipped.reduce(
    (total, _, index) => total + (index - indexCenter) ** 2,
    0,
  );
  const slope =
    clipped.reduce(
      (total, value, index) =>
        total + (index - indexCenter) * (value - center),
      0,
    ) / Math.max(denominator, 1e-9);
  const detrended = clipped.map(
    (value, index) => value - (center + slope * (index - indexCenter)),
  );
  const scale = Math.sqrt(
    detrended.reduce((total, value) => total + value * value, 0) /
      Math.max(1, count),
  );
  return scale <= 1e-8
    ? Array(count).fill(0)
    : detrended.map((value) => value / scale);
}

function smoothnessProxy(values) {
  if (values.length < 3) return 0;
  let numerator = 0;
  let denominator = 0;
  values.forEach((value, index) => {
    denominator += value * value;
    if (index > 0) numerator += value * values[index - 1];
  });
  return numerator / Math.max(denominator, 1e-9);
}

function captureQuality(duration, fps, packetLoss, jitterMs, radioSnrDb) {
  const durationScore = clamp((duration - 12) / 28);
  const fpsScore = clamp((fps - 8) / 12);
  const lossScore = clamp(1 - packetLoss / 0.05);
  const jitterScore = clamp(1 - jitterMs / 35);
  const radioScore = clamp((radioSnrDb - 12) / 22);
  return (
    durationScore ** 0.3 *
    fpsScore ** 0.15 *
    lossScore ** 0.2 *
    jitterScore ** 0.15 *
    radioScore ** 0.2
  );
}

function estimateRespiration(timestamps, traces, commonGate, previousBpm) {
  const duration = timestamps.at(-1) - timestamps[0];
  if (duration < 18) return emptyRate("spectral-consensus-v2", {
    capture: round(commonGate, 3),
  });
  const spectralCandidates = traces
    .map((trace, index) => ({
      index,
      trace,
      spectral: spectralPeak(timestamps, trace, 0.1, 0.55),
    }))
    .filter((item) => item.spectral.frequency !== null && item.spectral.quality >= 0.08)
    .sort((left, right) => right.spectral.quality - left.spectral.quality)
    .slice(0, 16);
  const candidates = spectralCandidates.map((item) => {
    const acf = autocorrelationPeak(timestamps, item.trace, 0.1, 0.55);
    const agreement =
      acf.frequency === null
        ? 0
        : Math.exp(
            (-Math.abs(item.spectral.frequency - acf.frequency) * 60) / 3,
          );
    const frequency =
      acf.frequency !== null && agreement > 0.35
        ? 0.68 * item.spectral.frequency + 0.32 * acf.frequency
        : item.spectral.frequency;
    return {
      bpm: frequency * 60,
      score:
        0.58 * item.spectral.quality +
        0.24 * acf.quality +
        0.18 * agreement,
    };
  });
  return fuseCandidates(
    candidates.filter((candidate) => candidate.score >= 0.12),
    commonGate,
    previousBpm,
    0.52,
    2.5,
    "fft+acf+subcarrier-consensus-v2",
    duration,
  );
}

function estimateHeart(
  timestamps,
  traces,
  commonGate,
  respirationBpm,
  previousBpm,
) {
  const duration = timestamps.at(-1) - timestamps[0];
  if (duration < 35) return emptyRate("spectral-consensus-v2", {
    capture: round(commonGate, 3),
  });
  const respirationHz = respirationBpm ? respirationBpm / 60 : null;
  const candidates = traces.flatMap((trace) => {
    const spectral = spectralPeak(timestamps, trace, 0.8, 2.2);
    if (spectral.frequency === null) return [];
    let harmonicPenalty = 1;
    if (respirationHz) {
      let distance = Infinity;
      for (let harmonic = 2; harmonic <= 8; harmonic += 1) {
        distance = Math.min(
          distance,
          Math.abs(spectral.frequency - respirationHz * harmonic),
        );
      }
      harmonicPenalty = 0.45 + 0.55 * clamp(distance / 0.065);
    }
    let score = spectral.quality * harmonicPenalty;
    if (spectral.ratio < 2) score *= 0.65;
    return score >= 0.15
      ? [{ bpm: spectral.frequency * 60, score }]
      : [];
  });
  return fuseCandidates(
    candidates,
    commonGate * 0.88,
    previousBpm,
    0.62,
    4.5,
    "cardiac-spectral-consensus-v2",
    duration,
  );
}

function fuseCandidates(
  candidates,
  commonGate,
  previousBpm,
  minimumConfidence,
  toleranceBpm,
  method,
  duration,
) {
  if (candidates.length < 3) {
    return emptyRate(method, {
      capture: round(commonGate, 3),
      consensus: 0,
    });
  }
  const selected = [...candidates]
    .sort((left, right) => right.score - left.score)
    .slice(0, Math.min(12, Math.max(4, Math.floor(candidates.length / 3))));
  let center = weightedMedian(
    selected.map((item) => item.bpm),
    selected.map((item) => item.score),
  );
  let dispersion = weightedMedian(
    selected.map((item) => Math.abs(item.bpm - center)),
    selected.map((item) => item.score),
  );
  let inliers = selected.filter(
    (item) =>
      Math.abs(item.bpm - center) <=
      Math.max(toleranceBpm * 1.8, 2.5 * dispersion),
  );
  if (inliers.length >= 3) {
    const weight = inliers.reduce((total, item) => total + item.score, 0);
    center =
      inliers.reduce((total, item) => total + item.bpm * item.score, 0) /
      weight;
    dispersion = weightedMedian(
      inliers.map((item) => Math.abs(item.bpm - center)),
      inliers.map((item) => item.score),
    );
  } else {
    inliers = selected;
  }
  const consensus = Math.exp(-dispersion / toleranceBpm);
  const coverage = clamp((inliers.length - 2) / 6);
  const source =
    inliers.reduce((total, item) => total + item.score, 0) / inliers.length;
  const temporal =
    previousBpm === null || previousBpm === undefined
      ? 1
      : 0.45 +
        0.55 *
          Math.exp(
            -Math.abs(center - previousBpm) / (toleranceBpm * 2.5),
          );
  const confidence = clamp(
    commonGate *
      (0.5 * source + 0.3 * consensus + 0.2 * coverage) *
      temporal,
  );
  return {
    value_bpm: confidence >= 0.12 ? round(center, 1) : null,
    confidence: round(confidence, 3),
    valid: confidence >= minimumConfidence,
    uncertainty_bpm: round(
      Math.max(0.3, 15 / Math.max(duration, 1), 1.4826 * dispersion),
      1,
    ),
    method,
    traces_used: inliers.length,
    quality: {
      capture: round(commonGate, 3),
      source: round(source, 3),
      consensus: round(consensus, 3),
      coverage: round(coverage, 3),
      temporal: round(temporal, 3),
    },
  };
}

function weightedMedian(values, weights) {
  const ordered = values
    .map((value, index) => ({ value, weight: weights[index] }))
    .sort((left, right) => left.value - right.value);
  const threshold =
    ordered.reduce((total, item) => total + item.weight, 0) / 2;
  let cumulative = 0;
  for (const item of ordered) {
    cumulative += item.weight;
    if (cumulative >= threshold) return item.value;
  }
  return ordered.at(-1).value;
}

function spectralPeak(timestamps, values, low, high) {
  if (values.length < 32) return { frequency: null, quality: 0, ratio: 0 };
  const duration = timestamps.at(-1) - timestamps[0];
  const sampleRate = (values.length - 1) / Math.max(duration, 1e-9);
  const step = Math.max(0.005, 1 / Math.max(4 * duration, 1));
  const windowed = values.map(
    (value, index) =>
      value *
      (0.5 -
        0.5 *
          Math.cos((2 * Math.PI * index) / Math.max(1, values.length - 1))),
  );
  const samples = [];
  for (
    let frequency = Math.ceil(low / step) * step;
    frequency <= high + 1e-9;
    frequency += step
  ) {
    const coefficient =
      2 * Math.cos((2 * Math.PI * frequency) / sampleRate);
    let previous = 0;
    let beforePrevious = 0;
    windowed.forEach((value) => {
      const current = value + coefficient * previous - beforePrevious;
      beforePrevious = previous;
      previous = current;
    });
    samples.push({
      frequency,
      power:
        previous * previous +
        beforePrevious * beforePrevious -
        coefficient * previous * beforePrevious,
    });
  }
  let peakIndex = 0;
  samples.forEach((sample, index) => {
    if (sample.power > samples[peakIndex].power) peakIndex = index;
  });
  if (!samples.length || samples[peakIndex].power <= 1e-10) {
    return { frequency: null, quality: 0, ratio: 0 };
  }
  let peakFrequency = samples[peakIndex].frequency;
  if (peakIndex > 0 && peakIndex < samples.length - 1) {
    const left = Math.log(Math.max(samples[peakIndex - 1].power, 1e-12));
    const center = Math.log(Math.max(samples[peakIndex].power, 1e-12));
    const right = Math.log(Math.max(samples[peakIndex + 1].power, 1e-12));
    const denominator = left - 2 * center + right;
    if (Math.abs(denominator) > 1e-9) {
      peakFrequency +=
        clamp((0.5 * (left - right)) / denominator, -0.5, 0.5) * step;
    }
  }
  const guard = Math.max(1, Math.round(0.035 / step));
  const background = samples
    .filter((_, index) => Math.abs(index - peakIndex) > guard)
    .map((sample) => sample.power);
  const noise = background.length ? median(background) : 1e-9;
  const ratio = samples[peakIndex].power / Math.max(noise, 1e-9);
  const localPower = samples
    .slice(
      Math.max(0, peakIndex - guard),
      Math.min(samples.length, peakIndex + guard + 1),
    )
    .reduce((total, sample) => total + sample.power, 0);
  const totalPower = samples.reduce(
    (total, sample) => total + sample.power,
    0,
  );
  const purity = localPower / Math.max(totalPower, 1e-9);
  const ratioScore = clamp(Math.log10(Math.max(1, ratio)) / 1.7);
  const purityScore = clamp((purity - 0.1) / 0.62);
  return {
    frequency: peakFrequency,
    quality: 0.62 * ratioScore + 0.38 * purityScore,
    ratio,
  };
}

function autocorrelationPeak(timestamps, values, low, high) {
  const duration = timestamps.at(-1) - timestamps[0];
  const sampleRate = (values.length - 1) / Math.max(duration, 1e-9);
  const minimumLag = Math.max(1, Math.round(sampleRate / high));
  const maximumLag = Math.min(
    Math.floor(values.length / 2),
    Math.round(sampleRate / low),
  );
  let bestLag = 0;
  let best = -1;
  for (let lag = minimumLag; lag <= maximumLag; lag += 1) {
    let numerator = 0;
    let leftPower = 0;
    let rightPower = 0;
    for (let index = 0; index < values.length - lag; index += 1) {
      const left = values[index];
      const right = values[index + lag];
      numerator += left * right;
      leftPower += left * left;
      rightPower += right * right;
    }
    const correlation =
      numerator / Math.sqrt(Math.max(leftPower * rightPower, 1e-12));
    if (correlation > best) {
      best = correlation;
      bestLag = lag;
    }
  }
  return {
    frequency: bestLag ? sampleRate / bestLag : null,
    quality: clamp((best - 0.15) / 0.7),
  };
}

function median(values) {
  if (!values.length) return 0;
  const ordered = [...values].sort((left, right) => left - right);
  const middle = Math.floor(ordered.length / 2);
  return ordered.length % 2
    ? ordered[middle]
    : (ordered[middle - 1] + ordered[middle]) / 2;
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
