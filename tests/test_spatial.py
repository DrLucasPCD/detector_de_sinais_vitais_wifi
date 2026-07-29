import math
from pathlib import Path

import pytest

from rf_sense.spatial import Environment, MeshObservation, SpatialEngine


ENVIRONMENT = Path(__file__).parents[1] / "config" / "environment.example.json"


def observation(node_id: int, position: tuple[float, float]) -> MeshObservation:
    environment = Environment.load(ENVIRONMENT)
    node = environment.node(node_id)
    assert node is not None
    return MeshObservation(
        track_key="anonymous-a",
        node_id=node_id,
        distance_m=math.hypot(
            position[0] - node.position[0],
            position[1] - node.position[1],
        ),
        confidence=0.95,
        breathing_bpm=16,
        breathing_confidence=0.85,
        heart_bpm=72,
        heart_confidence=0.75,
    )


def test_mesh_trilaterates_and_fuses_vitals() -> None:
    environment = Environment.load(ENVIRONMENT)
    engine = SpatialEngine(environment)
    target = (2.0, 2.0)
    accepted = engine.observe(
        [observation(node_id, target) for node_id in (1, 2, 3, 4)],
    )

    assert accepted == 1
    track = engine.tracks["anonymous-a"]
    assert track.position[0] == pytest.approx(target[0], abs=0.05)
    assert track.position[1] == pytest.approx(target[1], abs=0.05)
    assert track.room_id == "sala"
    assert track.breathing_bpm == pytest.approx(16)
    assert track.heart_bpm == pytest.approx(72)
    snapshot = engine.snapshot()
    assert snapshot["summary"]["mesh_nodes_online"] == 4
    assert snapshot["summary"]["mesh_ready"] is True
    assert snapshot["summary"]["count_valid"] is True


def test_two_nodes_do_not_claim_a_location_or_count() -> None:
    environment = Environment.load(ENVIRONMENT)
    engine = SpatialEngine(environment)
    accepted = engine.observe(
        [observation(node_id, (2.0, 2.0)) for node_id in (1, 2)],
        timestamp=100.0,
    )

    assert accepted == 0
    assert engine.tracks == {}


def test_invalid_collinear_geometry_is_rejected() -> None:
    environment = Environment.from_dict(
        {
            "bounds": {"width": 8, "depth": 6, "height": 2.8},
            "rooms": [
                {
                    "id": "room",
                    "name": "Room",
                    "origin": [0, 0, 0],
                    "size": [8, 6, 2.8],
                }
            ],
            "nodes": [
                {
                    "node_id": index,
                    "room_id": "room",
                    "position": [float(index), 1, 1],
                }
                for index in (1, 2, 3)
            ],
        }
    )
    engine = SpatialEngine(environment)
    with pytest.raises(ValueError, match="geometria"):
        engine.observe(
            [
                MeshObservation("track", index, 2, 0.9)
                for index in (1, 2, 3)
            ],
            timestamp=100,
        )
