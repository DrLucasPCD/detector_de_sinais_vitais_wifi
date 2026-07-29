from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Sequence


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


@dataclass(frozen=True, slots=True)
class RateEstimate:
    value_bpm: float | None = None
    confidence: float = 0.0
    valid: bool = False
    uncertainty_bpm: float | None = None
    method: str = "spectral-consensus-v2"
    traces_used: int = 0
    quality: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class VitalResult:
    breathing: RateEstimate = field(default_factory=RateEstimate)
    heart: RateEstimate = field(default_factory=RateEstimate)
    window_seconds: float = 0.0
    motion_rejected: bool = False


@dataclass(frozen=True, slots=True)
class _Candidate:
    index: int
    bpm: float
    score: float
    spectral_quality: float
    temporal_quality: float
    estimator_agreement: float


def estimate_vitals(
    samples: Sequence[tuple[float, Sequence[float]]],
    *,
    presence_confidence: float,
    motion_score: float,
    packet_loss: float,
    jitter_ms: float,
    radio_snr_db: float,
    previous_breathing_bpm: float | None = None,
    previous_heart_bpm: float | None = None,
) -> VitalResult:
    """Estimate RR/HR from calibrated CSI traces and expose why to trust it.

    The estimator intentionally rejects doubtful windows. It combines:
    robust outlier suppression, per-trace spectral quality, autocorrelation
    agreement (RR), cross-trace consensus, capture quality, motion rejection
    and temporal continuity. Heart rate uses a stricter gate because the
    displacement produced by a heartbeat is much smaller than respiration.
    """

    if len(samples) < 200:
        return VitalResult()
    timestamps = [sample[0] for sample in samples]
    duration = timestamps[-1] - timestamps[0]
    if duration < 10.0:
        return VitalResult(window_seconds=max(0.0, duration))
    if motion_score >= 0.55:
        return VitalResult(window_seconds=duration, motion_rejected=True)

    width = min(len(sample[1]) for sample in samples)
    if width == 0:
        return VitalResult(window_seconds=duration)

    # Keep the newest 60 s. A 45–60 s window resolves slow respiration and
    # gives the cardiac estimate enough cycles without making it sluggish.
    start = 0
    cutoff = timestamps[-1] - 60.0
    while start < len(timestamps) - 1 and timestamps[start] < cutoff:
        start += 1
    timestamps = timestamps[start:]
    samples = samples[start:]
    duration = timestamps[-1] - timestamps[0]
    traces = [
        _prepare_trace([float(sample[1][index]) for sample in samples])
        for index in range(width)
    ]
    if len(traces) > 48:
        ranked = sorted(
            range(len(traces)),
            key=lambda index: _smoothness_proxy(traces[index]),
            reverse=True,
        )[:48]
        traces = [traces[index] for index in ranked]

    expected_fps = (len(timestamps) - 1) / max(duration, 1e-9)
    capture_quality = _capture_quality(
        duration=duration,
        fps=expected_fps,
        packet_loss=packet_loss,
        jitter_ms=jitter_ms,
        radio_snr_db=radio_snr_db,
    )
    stillness = clamp(1.0 - motion_score / 0.90)
    common_gate = (
        clamp(presence_confidence)
        * capture_quality
        * (0.55 + 0.45 * stillness)
    )

    breathing = _estimate_respiration(
        timestamps,
        traces,
        common_gate=common_gate,
        previous_bpm=previous_breathing_bpm,
        window_seconds=duration,
    )
    heart = _estimate_heart(
        timestamps,
        traces,
        common_gate=common_gate,
        respiration_bpm=breathing.value_bpm,
        previous_bpm=previous_heart_bpm,
        window_seconds=duration,
    )
    return VitalResult(
        breathing=breathing,
        heart=heart,
        window_seconds=duration,
        motion_rejected=False,
    )


def _prepare_trace(values: Sequence[float]) -> list[float]:
    median = statistics.median(values)
    deviations = [abs(value - median) for value in values]
    mad = statistics.median(deviations)
    robust_sigma = max(1e-6, 1.4826 * mad)
    limit = 4.5 * robust_sigma
    clipped = [max(median - limit, min(median + limit, value)) for value in values]

    # Remove a linear drift (temperature/AGC) without suppressing the
    # physiological bands.
    count = len(clipped)
    center = (count - 1) / 2
    denominator = sum((index - center) ** 2 for index in range(count))
    slope = (
        sum((index - center) * (value - median) for index, value in enumerate(clipped))
        / max(denominator, 1e-9)
    )
    detrended = [
        value - (median + slope * (index - center))
        for index, value in enumerate(clipped)
    ]
    scale = math.sqrt(sum(value * value for value in detrended) / max(1, count))
    if scale <= 1e-8:
        return [0.0] * count
    return [value / scale for value in detrended]


def _smoothness_proxy(values: Sequence[float]) -> float:
    if len(values) < 3:
        return 0.0
    numerator = sum(
        values[index] * values[index - 1] for index in range(1, len(values))
    )
    denominator = sum(value * value for value in values)
    return numerator / max(denominator, 1e-9)


def _capture_quality(
    *,
    duration: float,
    fps: float,
    packet_loss: float,
    jitter_ms: float,
    radio_snr_db: float,
) -> float:
    duration_score = clamp((duration - 12.0) / 28.0)
    fps_score = clamp((fps - 8.0) / 12.0)
    loss_score = clamp(1.0 - packet_loss / 0.05)
    jitter_score = clamp(1.0 - jitter_ms / 35.0)
    radio_score = clamp((radio_snr_db - 12.0) / 22.0)
    return (
        duration_score**0.30
        * fps_score**0.15
        * loss_score**0.20
        * jitter_score**0.15
        * radio_score**0.20
    )


def _estimate_respiration(
    timestamps: Sequence[float],
    traces: Sequence[Sequence[float]],
    *,
    common_gate: float,
    previous_bpm: float | None,
    window_seconds: float,
) -> RateEstimate:
    if timestamps[-1] - timestamps[0] < 18.0:
        return RateEstimate(quality={"capture": round(common_gate, 3)})

    spectral_candidates: list[tuple[int, float, float, Sequence[float]]] = []
    for index, trace in enumerate(traces):
        frequency, spectral_quality, _ = _spectral_peak(
            timestamps, trace, 0.10, 0.55
        )
        if frequency is None:
            continue
        if spectral_quality >= 0.08:
            spectral_candidates.append(
                (index, frequency, spectral_quality, trace)
            )

    candidates: list[_Candidate] = []
    for index, frequency, spectral_quality, trace in sorted(
        spectral_candidates, key=lambda item: item[2], reverse=True
    )[:16]:
        acf_frequency, acf_quality = _autocorrelation_peak(
            timestamps, trace, 0.10, 0.55
        )
        agreement = (
            math.exp(-abs(frequency - acf_frequency) * 60.0 / 3.0)
            if acf_frequency is not None
            else 0.0
        )
        bpm = frequency * 60.0
        if acf_frequency is not None and agreement > 0.35:
            bpm = (0.68 * frequency + 0.32 * acf_frequency) * 60.0
        score = (
            0.58 * spectral_quality
            + 0.24 * acf_quality
            + 0.18 * agreement
        )
        if score >= 0.12:
            candidates.append(
                _Candidate(
                    index,
                    bpm,
                    score,
                    spectral_quality,
                    acf_quality,
                    agreement,
                )
            )
    return _fuse_candidates(
        candidates,
        common_gate=common_gate,
        previous_bpm=previous_bpm,
        minimum_confidence=0.52,
        tolerance_bpm=2.5,
        method="fft+acf+subcarrier-consensus-v2",
        window_seconds=window_seconds,
    )


def _estimate_heart(
    timestamps: Sequence[float],
    traces: Sequence[Sequence[float]],
    *,
    common_gate: float,
    respiration_bpm: float | None,
    previous_bpm: float | None,
    window_seconds: float,
) -> RateEstimate:
    if timestamps[-1] - timestamps[0] < 35.0:
        return RateEstimate(quality={"capture": round(common_gate, 3)})

    candidates: list[_Candidate] = []
    respiration_hz = respiration_bpm / 60.0 if respiration_bpm else None
    for index, trace in enumerate(traces):
        frequency, spectral_quality, peak_ratio = _spectral_peak(
            timestamps, trace, 0.80, 2.20
        )
        if frequency is None:
            continue
        harmonic_penalty = 1.0
        if respiration_hz:
            distance = min(
                abs(frequency - respiration_hz * harmonic)
                for harmonic in range(2, 9)
            )
            # Do not blindly notch a physiological frequency; reduce trust
            # only when the candidate is almost exactly a breathing harmonic.
            harmonic_penalty = 0.45 + 0.55 * clamp(distance / 0.065)
        score = spectral_quality * harmonic_penalty
        if peak_ratio < 2.0:
            score *= 0.65
        if score >= 0.15:
            candidates.append(
                _Candidate(index, frequency * 60.0, score, spectral_quality, 0.0, 1.0)
            )
    return _fuse_candidates(
        candidates,
        common_gate=common_gate * 0.88,
        previous_bpm=previous_bpm,
        minimum_confidence=0.62,
        tolerance_bpm=4.5,
        method="cardiac-spectral-consensus-v2",
        window_seconds=window_seconds,
    )


def _fuse_candidates(
    candidates: Sequence[_Candidate],
    *,
    common_gate: float,
    previous_bpm: float | None,
    minimum_confidence: float,
    tolerance_bpm: float,
    method: str,
    window_seconds: float,
) -> RateEstimate:
    if len(candidates) < 3:
        return RateEstimate(
            confidence=0.0,
            valid=False,
            method=method,
            traces_used=len(candidates),
            quality={"capture": round(common_gate, 3), "consensus": 0.0},
        )

    selected = sorted(candidates, key=lambda item: item.score, reverse=True)[
        : min(12, max(4, len(candidates) // 3))
    ]
    center = _weighted_median(
        [item.bpm for item in selected],
        [item.score for item in selected],
    )
    deviations = [abs(item.bpm - center) for item in selected]
    dispersion = _weighted_median(
        deviations,
        [item.score for item in selected],
    )
    inliers = [
        item
        for item in selected
        if abs(item.bpm - center) <= max(tolerance_bpm * 1.8, 2.5 * dispersion)
    ]
    if len(inliers) >= 3:
        center = sum(item.bpm * item.score for item in inliers) / sum(
            item.score for item in inliers
        )
        dispersion = _weighted_median(
            [abs(item.bpm - center) for item in inliers],
            [item.score for item in inliers],
        )
    else:
        inliers = selected

    consensus = math.exp(-dispersion / tolerance_bpm)
    coverage = clamp((len(inliers) - 2) / 6.0)
    source_quality = sum(item.score for item in inliers) / len(inliers)
    temporal = 1.0
    if previous_bpm is not None:
        temporal = 0.45 + 0.55 * math.exp(
            -abs(center - previous_bpm) / (tolerance_bpm * 2.5)
        )
    confidence = clamp(
        common_gate
        * (0.50 * source_quality + 0.30 * consensus + 0.20 * coverage)
        * temporal
    )
    uncertainty = max(
        max(0.3, 15.0 / max(window_seconds, 1.0)),
        1.4826 * dispersion,
    )
    return RateEstimate(
        # Keep a low-confidence candidate for diagnostics and validation, while
        # the API/UI only treats it as publishable after the stricter gate.
        value_bpm=center if confidence >= 0.12 else None,
        confidence=confidence,
        valid=confidence >= minimum_confidence,
        uncertainty_bpm=uncertainty,
        method=method,
        traces_used=len(inliers),
        quality={
            "capture": round(common_gate, 3),
            "source": round(source_quality, 3),
            "consensus": round(consensus, 3),
            "coverage": round(coverage, 3),
            "temporal": round(temporal, 3),
        },
    )
def _weighted_median(values: Sequence[float], weights: Sequence[float]) -> float:
    ordered = sorted(zip(values, weights, strict=True), key=lambda item: item[0])
    threshold = sum(weight for _, weight in ordered) / 2.0
    cumulative = 0.0
    for value, weight in ordered:
        cumulative += weight
        if cumulative >= threshold:
            return value
    return ordered[-1][0]


def _spectral_peak(
    timestamps: Sequence[float],
    values: Sequence[float],
    low_hz: float,
    high_hz: float,
) -> tuple[float | None, float, float]:
    count = len(values)
    if count < 32:
        return None, 0.0, 0.0
    relative_times = [timestamp - timestamps[0] for timestamp in timestamps]
    duration = relative_times[-1]
    sample_rate = (count - 1) / max(duration, 1e-9)
    step = max(0.005, 1.0 / max(4.0 * duration, 1.0))
    windowed = [
        value
        * (
            0.5
            - 0.5
            * math.cos(2.0 * math.pi * index / max(1, count - 1))
        )
        for index, value in enumerate(values)
    ]
    powers: list[float] = []
    frequencies: list[float] = []
    frequency = math.ceil(low_hz / step) * step
    while frequency <= high_hz + 1e-9:
        # Goertzel avoids thousands of sin/cos calls. Capture jitter is scored
        # separately and high-jitter windows are rejected by capture_quality.
        omega = 2.0 * math.pi * frequency / sample_rate
        coefficient = 2.0 * math.cos(omega)
        previous = 0.0
        before_previous = 0.0
        for value in windowed:
            current = value + coefficient * previous - before_previous
            before_previous = previous
            previous = current
        frequencies.append(frequency)
        powers.append(
            previous * previous
            + before_previous * before_previous
            - coefficient * previous * before_previous
        )
        frequency += step
    if not powers or max(powers) <= 1e-10:
        return None, 0.0, 0.0

    peak_index = max(range(len(powers)), key=powers.__getitem__)
    peak_frequency = frequencies[peak_index]
    peak_power = powers[peak_index]
    if 0 < peak_index < len(powers) - 1:
        left = math.log(max(powers[peak_index - 1], 1e-12))
        center = math.log(max(peak_power, 1e-12))
        right = math.log(max(powers[peak_index + 1], 1e-12))
        denominator = left - 2.0 * center + right
        if abs(denominator) > 1e-9:
            peak_frequency += clamp(
                0.5 * (left - right) / denominator, -0.5, 0.5
            ) * step

    guard = max(1, round(0.035 / step))
    background = [
        power
        for index, power in enumerate(powers)
        if abs(index - peak_index) > guard
    ]
    noise = statistics.median(background) if background else 1e-9
    ratio = peak_power / max(noise, 1e-9)
    local_power = sum(
        powers[
            max(0, peak_index - guard) : min(len(powers), peak_index + guard + 1)
        ]
    )
    purity = local_power / max(sum(powers), 1e-9)
    ratio_score = clamp(math.log10(max(1.0, ratio)) / 1.7)
    purity_score = clamp((purity - 0.10) / 0.62)
    quality = 0.62 * ratio_score + 0.38 * purity_score
    return peak_frequency, quality, ratio


def _autocorrelation_peak(
    timestamps: Sequence[float],
    values: Sequence[float],
    low_hz: float,
    high_hz: float,
) -> tuple[float | None, float]:
    duration = timestamps[-1] - timestamps[0]
    sample_rate = (len(timestamps) - 1) / max(duration, 1e-9)
    minimum_lag = max(1, round(sample_rate / high_hz))
    maximum_lag = min(len(values) // 2, round(sample_rate / low_hz))
    if maximum_lag <= minimum_lag:
        return None, 0.0

    best_lag = 0
    best = -1.0
    for lag in range(minimum_lag, maximum_lag + 1):
        numerator = 0.0
        left_power = 0.0
        right_power = 0.0
        for index in range(len(values) - lag):
            left = values[index]
            right = values[index + lag]
            numerator += left * right
            left_power += left * left
            right_power += right * right
        correlation = numerator / math.sqrt(
            max(left_power * right_power, 1e-12)
        )
        if correlation > best:
            best = correlation
            best_lag = lag
    if best_lag == 0:
        return None, 0.0
    return sample_rate / best_lag, clamp((best - 0.15) / 0.70)
