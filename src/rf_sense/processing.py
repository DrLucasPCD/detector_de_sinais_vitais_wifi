from __future__ import annotations

import math
import time
import uuid
from collections import Counter, deque
from dataclasses import dataclass, field

from .protocol import RawCSIFrame
from .sequence import SequenceTracker
from .vitals import VitalResult, estimate_vitals


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _round(value: float | None, digits: int = 3) -> float | None:
    return None if value is None else round(value, digits)


@dataclass(slots=True)
class Calibration:
    target_frames: int
    count: int = 0
    sums: list[float] = field(default_factory=list)
    squares: list[float] = field(default_factory=list)
    calibration_id: str | None = None
    completed_at: float | None = None
    means: tuple[float, ...] | None = None
    stds: tuple[float, ...] | None = None

    @property
    def complete(self) -> bool:
        return self.means is not None

    @property
    def progress(self) -> float:
        return _clamp(self.count / self.target_frames)

    def observe(self, amplitudes: tuple[float, ...], now: float) -> bool:
        if self.complete:
            return False
        if not self.sums:
            self.sums = [0.0] * len(amplitudes)
            self.squares = [0.0] * len(amplitudes)
        if len(amplitudes) != len(self.sums):
            return False
        for index, value in enumerate(amplitudes):
            self.sums[index] += value
            self.squares[index] += value * value
        self.count += 1
        if self.count < self.target_frames:
            return False

        means = [total / self.count for total in self.sums]
        variances = [
            max(0.0, square / self.count - mean * mean)
            for square, mean in zip(self.squares, means, strict=True)
        ]
        self.means = tuple(means)
        self.stds = tuple(max(0.35, math.sqrt(value)) for value in variances)
        self.calibration_id = uuid.uuid4().hex[:12]
        self.completed_at = now
        return True


@dataclass(slots=True)
class NodeState:
    node_id: int
    calibration_frames: int
    source: str
    source_ip: str
    sequence: SequenceTracker = field(default_factory=SequenceTracker)
    calibration: Calibration = field(init=False)
    first_seen: float = 0.0
    last_seen: float = 0.0
    frequency_mhz: int = 0
    rssi_dbm: int = -128
    noise_floor_dbm: int = -128
    sample_count: int = 0
    presence: bool | None = None
    presence_confidence: float = 0.0
    motion_state: str = "unknown"
    motion_power: float = 0.0
    motion_score: float = 0.0
    variance: float = 0.0
    reasons: list[str] = field(default_factory=list)
    signal: deque[tuple[float, float]] = field(
        default_factory=lambda: deque(maxlen=1200)
    )
    csi_history: deque[tuple[float, tuple[float, ...]]] = field(
        default_factory=lambda: deque(maxlen=1200)
    )
    motion_history: deque[float] = field(
        default_factory=lambda: deque(maxlen=80)
    )
    vitals: VitalResult = field(default_factory=VitalResult)
    last_vitals_at: float = 0.0

    def __post_init__(self) -> None:
        self.calibration = Calibration(self.calibration_frames)

    def restart_calibration(self, frames: int) -> None:
        self.calibration = Calibration(frames)
        self.signal.clear()
        self.csi_history.clear()
        self.motion_history.clear()
        self.presence = None
        self.motion_state = "unknown"
        self.vitals = VitalResult()

    def update(self, frame: RawCSIFrame) -> None:
        now = frame.received_at
        amplitudes = frame.amplitudes()
        if self.first_seen == 0:
            self.first_seen = now
        self.last_seen = now
        self.frequency_mhz = frame.frequency_mhz
        self.rssi_dbm = frame.rssi_dbm
        self.noise_floor_dbm = frame.noise_floor_dbm
        self.sample_count = frame.sample_count
        self.sequence.observe(frame.sequence, now)

        if not self.calibration.complete:
            self.calibration.observe(amplitudes, now)
            self.presence = None
            self.motion_state = "unknown"
            self.reasons = ["baseline_em_captura"]
            return

        means = self.calibration.means or ()
        stds = self.calibration.stds or ()
        if len(amplitudes) != len(means):
            self.presence = None
            self.reasons = ["layout_csi_mudou"]
            return

        zscores = tuple(
            (value - mean) / std
            for value, mean, std in zip(amplitudes, means, stds, strict=True)
        )
        reference_index = min(
            range(len(means)),
            key=lambda index: stds[index] / max(means[index], 1e-6),
        )
        reference_amplitude = max(amplitudes[reference_index], 1e-6)
        reference_mean = max(means[reference_index], 1e-6)
        reference_relative_noise = stds[reference_index] / reference_mean
        ratio_features: list[float] = []
        for index, (amplitude, mean, std) in enumerate(
            zip(amplitudes, means, stds, strict=True)
        ):
            if index == reference_index:
                continue
            baseline_ratio = math.log(max(mean, 1e-6) / reference_mean)
            current_ratio = math.log(max(amplitude, 1e-6) / reference_amplitude)
            ratio_noise = math.sqrt(
                (std / max(mean, 1e-6)) ** 2 + reference_relative_noise**2
            )
            ratio_features.append(
                (current_ratio - baseline_ratio) / max(0.015, ratio_noise)
            )
        mean_abs_z = sum(abs(value) for value in zscores) / len(zscores)
        projection = sum(zscores) / len(zscores)
        previous = self.signal[-1][1] if self.signal else projection
        delta = projection - previous
        self.signal.append((now, projection))
        self.csi_history.append((now, zscores + tuple(ratio_features)))
        self.motion_history.append(delta * delta)

        self.variance = mean_abs_z
        self.motion_power = (
            sum(self.motion_history) / len(self.motion_history)
            if self.motion_history
            else 0.0
        )
        self.presence_confidence = _clamp((mean_abs_z - 1.1) / 4.0)
        self.presence = self.presence_confidence >= 0.52
        motion_score = _clamp((self.motion_power - 0.02) / 0.45)
        self.motion_score = motion_score
        self.motion_state = (
            "moving" if self.presence and motion_score >= 0.50 else "still"
        )
        if not self.presence:
            self.motion_state = "empty"

        self.reasons = []
        if self.presence:
            self.reasons.append("desvio_da_baseline")
        if self.motion_state == "moving":
            self.reasons.append("energia_temporal_alta")
        if self.sequence.packet_loss > 0.01:
            self.reasons.append("perda_udp_acima_da_meta")
        if self.sequence.fps and self.sequence.fps < 15:
            self.reasons.append("fps_abaixo_da_meta")

        # Physiological rates evolve slowly; a 5 s cadence reduces CPU use
        # without changing the 45–60 s analysis window.
        if now - self.last_vitals_at >= 5.0:
            self.last_vitals_at = now
            self.vitals = self._estimate_vitals()

    def _estimate_vitals(self) -> VitalResult:
        if len(self.signal) < 200 or not self.presence:
            return VitalResult()
        if self.motion_state == "moving":
            return VitalResult(
                window_seconds=self.signal[-1][0] - self.signal[0][0],
                motion_rejected=True,
            )
        return estimate_vitals(
            list(self.csi_history),
            presence_confidence=self.presence_confidence,
            motion_score=self.motion_score,
            packet_loss=self.sequence.packet_loss,
            jitter_ms=self.sequence.jitter_ms,
            radio_snr_db=self.rssi_dbm - self.noise_floor_dbm,
            previous_breathing_bpm=self.vitals.breathing.value_bpm,
            previous_heart_bpm=self.vitals.heart.value_bpm,
        )

    def summary(self, now: float, stale_after: float) -> dict[str, object]:
        stale = now - self.last_seen > stale_after
        if stale:
            state = "STALE"
        elif not self.calibration.complete:
            state = "CALIBRATING"
        elif self.source == "simulator":
            state = "SIMULATED"
        elif self.sequence.packet_loss > 0.01 or self.sequence.fps < 15:
            state = "LIVE/DEGRADED"
        else:
            state = "LIVE/VALID"
        baseline_age = (
            now - self.calibration.completed_at
            if self.calibration.completed_at is not None
            else None
        )
        return {
            "node_id": self.node_id,
            "source": self.source,
            "source_ip": self.source_ip,
            "state": state,
            "stale": stale,
            "last_seen_age_s": _round(now - self.last_seen),
            "frequency_mhz": self.frequency_mhz,
            "rssi_dbm": self.rssi_dbm,
            "noise_floor_dbm": self.noise_floor_dbm,
            "snr_db": self.rssi_dbm - self.noise_floor_dbm,
            "fps": _round(self.sequence.fps, 2),
            "packet_loss": _round(self.sequence.packet_loss, 5),
            "jitter_ms": _round(self.sequence.jitter_ms, 2),
            "received": self.sequence.received,
            "lost": self.sequence.lost,
            "reordered": self.sequence.reordered,
            "duplicates": self.sequence.duplicates,
            "calibration": {
                "id": self.calibration.calibration_id,
                "frames": self.calibration.count,
                "target_frames": self.calibration.target_frames,
                "progress": _round(self.calibration.progress),
                "age_s": _round(baseline_age),
                "valid": self.calibration.complete,
            },
        }

    def sensing(self) -> dict[str, object]:
        confidence = (
            min(self.presence_confidence, 1.0)
            if self.presence is not None
            else 0.0
        )
        return {
            "features": {
                "variance": _round(self.variance),
                "motion_power": _round(self.motion_power),
                "motion_score": _round(self.motion_score),
                "breathing_power": _round(
                    self.vitals.breathing.quality.get("source")
                ),
                "heart_power": _round(self.vitals.heart.quality.get("source")),
                "psd_peak_hz": (
                    _round(self.vitals.breathing.value_bpm / 60)
                    if self.vitals.breathing.value_bpm
                    else None
                ),
            },
            "classification": {
                "presence": self.presence,
                "motion_state": self.motion_state,
                "confidence": _round(confidence),
                "reasons": list(self.reasons),
            },
            "vital_signs": {
                "breathing_bpm": _round(self.vitals.breathing.value_bpm, 1),
                "heart_bpm": _round(self.vitals.heart.value_bpm, 1),
                "confidence": _round(self.vitals.breathing.confidence),
                "valid": self.vitals.breathing.valid,
                "breathing": {
                    "value_bpm": _round(self.vitals.breathing.value_bpm, 1),
                    "confidence": _round(self.vitals.breathing.confidence),
                    "valid": self.vitals.breathing.valid,
                    "uncertainty_bpm": _round(
                        self.vitals.breathing.uncertainty_bpm, 1
                    ),
                    "method": self.vitals.breathing.method,
                    "traces_used": self.vitals.breathing.traces_used,
                    "quality": dict(self.vitals.breathing.quality),
                },
                "heart": {
                    "value_bpm": _round(self.vitals.heart.value_bpm, 1),
                    "confidence": _round(self.vitals.heart.confidence),
                    "valid": self.vitals.heart.valid,
                    "uncertainty_bpm": _round(
                        self.vitals.heart.uncertainty_bpm, 1
                    ),
                    "method": self.vitals.heart.method,
                    "traces_used": self.vitals.heart.traces_used,
                    "quality": dict(self.vitals.heart.quality),
                },
                "motion_rejected": self.vitals.motion_rejected,
                "experimental": True,
                "window_seconds": _round(self.vitals.window_seconds, 1),
            },
            "alerts": [],
        }


class SensorEngine:
    def __init__(self, calibration_frames: int, stale_after_seconds: int) -> None:
        self.calibration_frames = calibration_frames
        self.stale_after_seconds = stale_after_seconds
        self.nodes: dict[int, NodeState] = {}
        self.counters: Counter[str] = Counter()
        self.started_at = time.monotonic()
        self.version = 0

    def process(
        self, frame: RawCSIFrame, source_ip: str, source: str = "esp32"
    ) -> None:
        node = self.nodes.get(frame.node_id)
        if node is None:
            node = NodeState(
                frame.node_id,
                self.calibration_frames,
                source=source,
                source_ip=source_ip,
            )
            self.nodes[frame.node_id] = node
        node.source = source
        node.source_ip = source_ip
        node.update(frame)
        self.counters["frames_accepted"] += 1
        self.version += 1

    def reject(self, code: str) -> None:
        self.counters["frames_rejected"] += 1
        self.counters[f"reject_{code}"] += 1

    def restart_calibration(self, frames: int) -> int:
        for node in self.nodes.values():
            node.restart_calibration(frames)
        self.calibration_frames = frames
        self.version += 1
        return len(self.nodes)

    def latest(self) -> dict[str, object]:
        now = time.monotonic()
        if not self.nodes:
            return {
                "source": "none",
                "timestamp_host_ms": int(time.time() * 1000),
                "nodes": [],
                "features": {},
                "classification": {
                    "presence": None,
                    "motion_state": "unknown",
                    "confidence": 0.0,
                    "reasons": ["aguardando_quadros"],
                },
                "vital_signs": {
                    "breathing_bpm": None,
                    "heart_bpm": None,
                    "confidence": 0.0,
                    "valid": False,
                    "breathing": {
                        "value_bpm": None,
                        "confidence": 0.0,
                        "valid": False,
                    },
                    "heart": {
                        "value_bpm": None,
                        "confidence": 0.0,
                        "valid": False,
                    },
                    "motion_rejected": False,
                    "experimental": True,
                },
                "alerts": [],
            }
        freshest = max(self.nodes.values(), key=lambda item: item.last_seen)
        node_sensing = freshest.sensing()
        return {
            "source": freshest.source,
            "timestamp_host_ms": int(time.time() * 1000),
            "nodes": [
                node.summary(now, self.stale_after_seconds)
                for node in sorted(self.nodes.values(), key=lambda item: item.node_id)
            ],
            **node_sensing,
        }

    def node_inventory(self) -> list[dict[str, object]]:
        now = time.monotonic()
        return [
            node.summary(now, self.stale_after_seconds)
            for node in sorted(self.nodes.values(), key=lambda item: item.node_id)
        ]
