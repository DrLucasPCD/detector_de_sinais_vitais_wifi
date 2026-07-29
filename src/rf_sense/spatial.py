from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence


DEFAULT_ENVIRONMENT = {
    "version": 1,
    "site": {"id": "rf-sense-local", "name": "Ambiente RF Sense"},
    "units": "m",
    "bounds": {"width": 8.0, "depth": 6.0, "height": 2.8},
    "rooms": [
        {
            "id": "ambiente",
            "name": "Ambiente",
            "origin": [0.0, 0.0, 0.0],
            "size": [8.0, 6.0, 2.8],
        }
    ],
    "nodes": [
        {
            "node_id": 1,
            "name": "Nó 1",
            "room_id": "ambiente",
            "position": [0.6, 0.6, 1.2],
            "coverage_radius_m": 4.5,
        }
    ],
    "mesh_links": [],
}


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} deve ser numérico")
    if not math.isfinite(float(value)):
        raise ValueError(f"{name} deve ser finito")
    return float(value)


def _vector3(value: object, name: str) -> tuple[float, float, float]:
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError(f"{name} deve conter três números")
    return (
        _number(value[0], f"{name}[0]"),
        _number(value[1], f"{name}[1]"),
        _number(value[2], f"{name}[2]"),
    )


@dataclass(frozen=True, slots=True)
class Room:
    room_id: str
    name: str
    origin: tuple[float, float, float]
    size: tuple[float, float, float]

    @property
    def center(self) -> tuple[float, float, float]:
        return (
            self.origin[0] + self.size[0] / 2.0,
            self.origin[1] + self.size[1] / 2.0,
            min(1.0, self.size[2] / 2.0),
        )

    def contains(self, point: Sequence[float]) -> bool:
        return (
            self.origin[0] <= point[0] <= self.origin[0] + self.size[0]
            and self.origin[1] <= point[1] <= self.origin[1] + self.size[1]
            and self.origin[2] <= point[2] <= self.origin[2] + self.size[2]
        )


@dataclass(frozen=True, slots=True)
class SpatialNode:
    node_id: int
    name: str
    room_id: str
    position: tuple[float, float, float]
    coverage_radius_m: float


@dataclass(frozen=True, slots=True)
class Environment:
    raw: dict[str, object]
    rooms: tuple[Room, ...]
    nodes: tuple[SpatialNode, ...]

    @classmethod
    def load(cls, path: str | Path | None) -> "Environment":
        if path:
            source = Path(path).expanduser()
            with source.open("r", encoding="utf-8") as handle:
                raw = json.load(handle)
        else:
            raw = json.loads(json.dumps(DEFAULT_ENVIRONMENT))
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, raw: object) -> "Environment":
        if not isinstance(raw, dict):
            raise ValueError("ambiente deve ser um objeto JSON")
        bounds = raw.get("bounds")
        if not isinstance(bounds, dict):
            raise ValueError("bounds é obrigatório")
        width = _number(bounds.get("width"), "bounds.width")
        depth = _number(bounds.get("depth"), "bounds.depth")
        height = _number(bounds.get("height"), "bounds.height")
        if min(width, depth, height) <= 0:
            raise ValueError("dimensões do ambiente devem ser positivas")

        room_items = raw.get("rooms")
        if not isinstance(room_items, list) or not room_items:
            raise ValueError("rooms deve conter ao menos um ambiente")
        rooms: list[Room] = []
        room_ids: set[str] = set()
        for index, item in enumerate(room_items):
            if not isinstance(item, dict):
                raise ValueError(f"rooms[{index}] deve ser um objeto")
            room_id = str(item.get("id", "")).strip()
            if not room_id or room_id in room_ids:
                raise ValueError(f"rooms[{index}].id inválido ou duplicado")
            room_ids.add(room_id)
            origin = _vector3(item.get("origin"), f"rooms[{index}].origin")
            size = _vector3(item.get("size"), f"rooms[{index}].size")
            if min(size) <= 0:
                raise ValueError(f"rooms[{index}].size deve ser positivo")
            if (
                origin[0] < 0
                or origin[1] < 0
                or origin[2] < 0
                or origin[0] + size[0] > width + 1e-6
                or origin[1] + size[1] > depth + 1e-6
                or origin[2] + size[2] > height + 1e-6
            ):
                raise ValueError(f"rooms[{index}] excede os limites do mapa")
            rooms.append(
                Room(
                    room_id=room_id,
                    name=str(item.get("name") or room_id),
                    origin=origin,
                    size=size,
                )
            )

        node_items = raw.get("nodes", [])
        if not isinstance(node_items, list):
            raise ValueError("nodes deve ser uma lista")
        nodes: list[SpatialNode] = []
        node_ids: set[int] = set()
        for index, item in enumerate(node_items):
            if not isinstance(item, dict):
                raise ValueError(f"nodes[{index}] deve ser um objeto")
            node_id = int(_number(item.get("node_id"), f"nodes[{index}].node_id"))
            if not 0 <= node_id <= 255 or node_id in node_ids:
                raise ValueError(f"nodes[{index}].node_id inválido ou duplicado")
            room_id = str(item.get("room_id", "")).strip()
            if room_id not in room_ids:
                raise ValueError(f"nodes[{index}].room_id desconhecido")
            position = _vector3(item.get("position"), f"nodes[{index}].position")
            room = next(room for room in rooms if room.room_id == room_id)
            if not room.contains(position):
                raise ValueError(f"nodes[{index}] está fora do ambiente associado")
            node_ids.add(node_id)
            nodes.append(
                SpatialNode(
                    node_id=node_id,
                    name=str(item.get("name") or f"Nó {node_id}"),
                    room_id=room_id,
                    position=position,
                    coverage_radius_m=max(
                        0.1,
                        _number(
                            item.get("coverage_radius_m", 4.0),
                            f"nodes[{index}].coverage_radius_m",
                        ),
                    ),
                )
            )

        normalized = dict(raw)
        normalized["bounds"] = {
            "width": width,
            "depth": depth,
            "height": height,
        }
        return cls(normalized, tuple(rooms), tuple(nodes))

    def node(self, node_id: int) -> SpatialNode | None:
        return next((node for node in self.nodes if node.node_id == node_id), None)

    def room_for(self, point: Sequence[float]) -> Room | None:
        return next((room for room in self.rooms if room.contains(point)), None)


@dataclass(frozen=True, slots=True)
class MeshObservation:
    track_key: str
    node_id: int
    distance_m: float
    confidence: float
    breathing_bpm: float | None = None
    breathing_confidence: float = 0.0
    heart_bpm: float | None = None
    heart_confidence: float = 0.0


@dataclass(slots=True)
class SpatialTrack:
    track_id: str
    position: tuple[float, float, float]
    uncertainty_m: float
    confidence: float
    room_id: str | None
    source_nodes: tuple[int, ...]
    updated_at: float
    breathing_bpm: float | None = None
    breathing_confidence: float = 0.0
    heart_bpm: float | None = None
    heart_confidence: float = 0.0


class SpatialEngine:
    def __init__(
        self,
        environment: Environment,
        *,
        track_ttl_seconds: float = 10.0,
    ) -> None:
        self.environment = environment
        self.track_ttl_seconds = track_ttl_seconds
        self.tracks: dict[str, SpatialTrack] = {}
        self.observed_nodes: dict[int, float] = {}
        self.version = 0

    def observe(
        self,
        observations: Iterable[MeshObservation],
        *,
        timestamp: float | None = None,
    ) -> int:
        now = time.monotonic() if timestamp is None else timestamp
        grouped: dict[str, list[MeshObservation]] = {}
        for observation in observations:
            if self.environment.node(observation.node_id) is None:
                raise ValueError(f"nó espacial {observation.node_id} desconhecido")
            if observation.distance_m <= 0:
                raise ValueError("distance_m deve ser positivo")
            self.observed_nodes[observation.node_id] = now
            grouped.setdefault(observation.track_key, []).append(observation)

        accepted = 0
        for track_key, items in grouped.items():
            if len({item.node_id for item in items}) < 3:
                continue
            position, uncertainty = self._trilaterate(items)
            bounds = self.environment.raw["bounds"]
            assert isinstance(bounds, dict)
            position = (
                _clamp(position[0], 0.0, float(bounds["width"])),
                _clamp(position[1], 0.0, float(bounds["depth"])),
                _clamp(position[2], 0.0, float(bounds["height"])),
            )
            room = self.environment.room_for(position)
            confidence = _clamp(
                sum(item.confidence for item in items) / len(items)
                * math.exp(-uncertainty / 2.0)
            )
            breathing, breathing_confidence = _weighted_vital(
                (
                    (item.breathing_bpm, item.breathing_confidence)
                    for item in items
                )
            )
            heart, heart_confidence = _weighted_vital(
                ((item.heart_bpm, item.heart_confidence) for item in items)
            )
            self.tracks[track_key] = SpatialTrack(
                track_id=track_key,
                position=position,
                uncertainty_m=uncertainty,
                confidence=confidence,
                room_id=room.room_id if room else None,
                source_nodes=tuple(sorted({item.node_id for item in items})),
                updated_at=now,
                breathing_bpm=breathing,
                breathing_confidence=breathing_confidence,
                heart_bpm=heart,
                heart_confidence=heart_confidence,
            )
            accepted += 1
        if accepted:
            self.version += 1
        self._expire(now)
        return accepted

    def snapshot(self, sensor_engine: object | None = None) -> dict[str, object]:
        now = time.monotonic()
        self._expire(now)
        people = [self._track_dict(track, now) for track in self.tracks.values()]
        zone_people = self._zone_estimates(sensor_engine, now)
        tracked_rooms = {person["room_id"] for person in people}
        people.extend(
            person
            for person in zone_people
            if person["room_id"] not in tracked_rooms
        )
        people.sort(key=lambda item: str(item["track_id"]))
        live_nodes = self._node_states(sensor_engine, now)
        localized = sum(
            1 for person in people if person.get("position_valid") is True
        )
        room_summary = []
        for room in self.environment.rooms:
            occupants = [
                person for person in people if person.get("room_id") == room.room_id
            ]
            room_summary.append(
                {
                    "room_id": room.room_id,
                    "name": room.name,
                    "occupancy": bool(occupants),
                    "people_count": len(occupants),
                    "count_confidence": (
                        min(float(person["confidence"]) for person in occupants)
                        if occupants
                        else 1.0
                    ),
                }
            )
        mesh_nodes = sum(1 for node in live_nodes if node["state"] != "offline")
        return {
            "schema": "rf-sense-spatial-v1",
            "timestamp_host_ms": int(time.time() * 1000),
            "environment": self.environment.raw,
            "nodes": live_nodes,
            "people": people,
            "rooms": room_summary,
            "summary": {
                "people_count": len(people),
                "localized_count": localized,
                "zone_only_count": len(people) - localized,
                "mesh_nodes_online": mesh_nodes,
                "mesh_ready": mesh_nodes >= 3,
                "count_valid": bool(people) and all(
                    person.get("count_valid") is True for person in people
                ),
            },
        }

    def _trilaterate(
        self, observations: Sequence[MeshObservation]
    ) -> tuple[tuple[float, float, float], float]:
        reference = observations[0]
        ref_node = self.environment.node(reference.node_id)
        assert ref_node is not None
        rows: list[tuple[float, float, float]] = []
        for observation in observations[1:]:
            node = self.environment.node(observation.node_id)
            assert node is not None
            ax = 2.0 * (node.position[0] - ref_node.position[0])
            ay = 2.0 * (node.position[1] - ref_node.position[1])
            b = (
                reference.distance_m**2
                - observation.distance_m**2
                - ref_node.position[0] ** 2
                - ref_node.position[1] ** 2
                + node.position[0] ** 2
                + node.position[1] ** 2
            )
            weight = max(0.05, observation.confidence)
            rows.append((ax * weight, ay * weight, b * weight))
        aa = sum(row[0] * row[0] for row in rows)
        ab = sum(row[0] * row[1] for row in rows)
        bb = sum(row[1] * row[1] for row in rows)
        ac = sum(row[0] * row[2] for row in rows)
        bc = sum(row[1] * row[2] for row in rows)
        determinant = aa * bb - ab * ab
        if abs(determinant) < 1e-8:
            raise ValueError("geometria dos nós não permite trilateração")
        x = (ac * bb - bc * ab) / determinant
        y = (bc * aa - ac * ab) / determinant
        z = 1.0
        residuals = []
        for observation in observations:
            node = self.environment.node(observation.node_id)
            assert node is not None
            predicted = math.hypot(x - node.position[0], y - node.position[1])
            residuals.append(predicted - observation.distance_m)
        rms = math.sqrt(
            sum(residual * residual for residual in residuals)
            / max(1, len(residuals))
        )
        geometry_penalty = 0.15 / max(math.sqrt(abs(determinant)), 0.1)
        return (x, y, z), max(0.15, rms + geometry_penalty)

    def _track_dict(self, track: SpatialTrack, now: float) -> dict[str, object]:
        return {
            "track_id": track.track_id,
            "anonymous": True,
            "room_id": track.room_id,
            "position": list(track.position),
            "position_valid": True,
            "uncertainty_m": round(track.uncertainty_m, 2),
            "confidence": round(track.confidence, 3),
            "count_valid": track.confidence >= 0.55,
            "source_nodes": list(track.source_nodes),
            "age_s": round(max(0.0, now - track.updated_at), 2),
            "vital_signs": {
                "breathing_bpm": (
                    round(track.breathing_bpm, 1)
                    if track.breathing_bpm is not None
                    else None
                ),
                "breathing_confidence": round(track.breathing_confidence, 3),
                "heart_bpm": (
                    round(track.heart_bpm, 1)
                    if track.heart_bpm is not None
                    else None
                ),
                "heart_confidence": round(track.heart_confidence, 3),
                "experimental": True,
            },
        }

    def _zone_estimates(
        self, sensor_engine: object | None, now: float
    ) -> list[dict[str, object]]:
        nodes = getattr(sensor_engine, "nodes", {}) if sensor_engine else {}
        by_room: dict[str, list[tuple[SpatialNode, object]]] = {}
        for node_id, sensor_node in nodes.items():
            spatial_node = self.environment.node(int(node_id))
            if spatial_node is None or getattr(sensor_node, "presence", None) is not True:
                continue
            by_room.setdefault(spatial_node.room_id, []).append(
                (spatial_node, sensor_node)
            )
        estimates: list[dict[str, object]] = []
        for room_id, items in by_room.items():
            room = next(room for room in self.environment.rooms if room.room_id == room_id)
            weights = [
                max(0.05, float(getattr(sensor_node, "presence_confidence", 0.0)))
                for _, sensor_node in items
            ]
            total = sum(weights)
            position = [
                sum(node.position[axis] * weight for (node, _), weight in zip(items, weights, strict=True))
                / total
                for axis in range(3)
            ]
            if len(items) == 1:
                position = list(room.center)
            best_sensor = max(
                (sensor_node for _, sensor_node in items),
                key=lambda node: float(getattr(node, "presence_confidence", 0.0)),
            )
            vitals = getattr(best_sensor, "vitals", None)
            breathing = getattr(getattr(vitals, "breathing", None), "value_bpm", None)
            breathing_confidence = getattr(
                getattr(vitals, "breathing", None), "confidence", 0.0
            )
            heart = getattr(getattr(vitals, "heart", None), "value_bpm", None)
            heart_confidence = getattr(
                getattr(vitals, "heart", None), "confidence", 0.0
            )
            estimates.append(
                {
                    "track_id": f"zone-{room_id}",
                    "anonymous": True,
                    "room_id": room_id,
                    "position": position,
                    "position_valid": False,
                    "uncertainty_m": round(max(room.size[0], room.size[1]) / 2, 2),
                    "confidence": round(min(weights), 3),
                    "count_valid": False,
                    "source_nodes": [node.node_id for node, _ in items],
                    "age_s": 0.0,
                    "vital_signs": {
                        "breathing_bpm": round(breathing, 1) if breathing else None,
                        "breathing_confidence": round(float(breathing_confidence), 3),
                        "heart_bpm": round(heart, 1) if heart else None,
                        "heart_confidence": round(float(heart_confidence), 3),
                        "experimental": True,
                    },
                }
            )
        return estimates

    def _node_states(
        self, sensor_engine: object | None, now: float
    ) -> list[dict[str, object]]:
        sensor_nodes = getattr(sensor_engine, "nodes", {}) if sensor_engine else {}
        result = []
        for node in self.environment.nodes:
            sensor = sensor_nodes.get(node.node_id)
            age = now - float(getattr(sensor, "last_seen", 0.0)) if sensor else None
            mesh_age = (
                now - self.observed_nodes[node.node_id]
                if node.node_id in self.observed_nodes
                else None
            )
            online = (
                sensor is not None and age is not None and age <= 10.0
            ) or (
                mesh_age is not None and mesh_age <= self.track_ttl_seconds
            )
            result.append(
                {
                    "node_id": node.node_id,
                    "name": node.name,
                    "room_id": node.room_id,
                    "position": list(node.position),
                    "coverage_radius_m": node.coverage_radius_m,
                    "state": "online" if online else "offline",
                    "presence": getattr(sensor, "presence", None) if sensor else None,
                    "confidence": round(
                        float(getattr(sensor, "presence_confidence", 0.0)), 3
                    ),
                }
            )
        return result

    def _expire(self, now: float) -> None:
        expired = [
            track_id
            for track_id, track in self.tracks.items()
            if now - track.updated_at > self.track_ttl_seconds
        ]
        for track_id in expired:
            del self.tracks[track_id]
        if expired:
            self.version += 1


def _weighted_vital(
    values: Iterable[tuple[float | None, float]]
) -> tuple[float | None, float]:
    accepted = [
        (float(value), _clamp(float(confidence)))
        for value, confidence in values
        if value is not None and confidence > 0
    ]
    if not accepted:
        return None, 0.0
    total = sum(confidence for _, confidence in accepted)
    value = sum(value * confidence for value, confidence in accepted) / total
    agreement = math.exp(
        -sum(abs(item - value) * confidence for item, confidence in accepted)
        / max(total * 4.0, 1e-9)
    )
    return value, _clamp(total / len(accepted) * agreement)
