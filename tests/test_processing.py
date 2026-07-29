from rf_sense.processing import SensorEngine
from rf_sense.simulator import SyntheticCSIGenerator


def test_calibration_presence_motion_and_vitals() -> None:
    engine = SensorEngine(calibration_frames=40, stale_after_seconds=10)
    generator = SyntheticCSIGenerator(seed=7)

    timestamp = 100.0
    for _ in range(40):
        engine.process(
            generator.frame(timestamp, "empty"),
            source_ip="127.0.0.1",
            source="simulator",
        )
        timestamp += 0.05

    node = engine.nodes[1]
    assert node.calibration.complete
    assert node.calibration.count == 40

    for _ in range(420):
        engine.process(
            generator.frame(timestamp, "still"),
            source_ip="127.0.0.1",
            source="simulator",
        )
        timestamp += 0.05

    latest = engine.latest()
    assert latest["classification"]["presence"] is True
    assert latest["classification"]["motion_state"] == "still"
    assert 6 <= latest["vital_signs"]["breathing_bpm"] <= 30

    for _ in range(100):
        engine.process(
            generator.frame(timestamp, "moving"),
            source_ip="127.0.0.1",
            source="simulator",
        )
        timestamp += 0.05

    latest = engine.latest()
    assert latest["classification"]["motion_state"] == "moving"
    assert latest["vital_signs"]["valid"] is False


def test_multitrace_consensus_estimates_each_vital_independently() -> None:
    engine = SensorEngine(calibration_frames=40, stale_after_seconds=10)
    generator = SyntheticCSIGenerator(
        seed=23,
        breathing_hz=0.30,
        heart_hz=1.35,
        noise_sigma=0.30,
    )
    timestamp = 200.0
    for _ in range(40):
        engine.process(
            generator.frame(timestamp, "empty"),
            source_ip="127.0.0.1",
            source="simulator",
        )
        timestamp += 0.05
    for _ in range(1100):
        engine.process(
            generator.frame(timestamp, "still"),
            source_ip="127.0.0.1",
            source="simulator",
        )
        timestamp += 0.05

    vitals = engine.latest()["vital_signs"]
    assert vitals["breathing"]["valid"] is True
    assert abs(vitals["breathing"]["value_bpm"] - 18.0) <= 1.0
    assert vitals["breathing"]["traces_used"] >= 3
    assert vitals["heart"]["valid"] is True
    assert abs(vitals["heart"]["value_bpm"] - 81.0) <= 2.0
    assert vitals["heart"]["traces_used"] >= 3
    assert vitals["breathing"]["confidence"] != vitals["heart"]["confidence"]
