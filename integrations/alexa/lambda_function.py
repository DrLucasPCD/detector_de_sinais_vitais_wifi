"""Alexa Smart Home + custom voice Lambda for RF Sense.

The function reads an AWS IoT Thing Shadow published directly by RF Sense.
It never calls Home Assistant.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from typing import Any


THING_NAME = os.getenv("RF_SENSE_THING_NAME", "rf-sense-local")


def _shadow() -> dict[str, Any]:
    import boto3

    response = boto3.client("iot-data").get_thing_shadow(thingName=THING_NAME)
    payload = json.loads(response["payload"].read())
    return payload.get("state", {}).get("reported", {})


def _timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _endpoint_id(room_id: str) -> str:
    return f"rf-sense-room-{room_id}"


def _room_id(endpoint_id: str) -> str:
    return endpoint_id.removeprefix("rf-sense-room-")


def _discovery(state: dict[str, Any]) -> dict[str, Any]:
    rooms = state.get("environment", {}).get("rooms", [])
    endpoints = []
    for room in rooms:
        endpoints.append(
            {
                "endpointId": _endpoint_id(str(room["id"])),
                "manufacturerName": "RF Sense",
                "friendlyName": f"Presença {room['name']}",
                "description": "Sensor de presença RF Sense por Wi-Fi CSI",
                "displayCategories": ["MOTION_SENSOR"],
                "cookie": {"roomId": str(room["id"])},
                "capabilities": [
                    {
                        "type": "AlexaInterface",
                        "interface": "Alexa",
                        "version": "3",
                    },
                    {
                        "type": "AlexaInterface",
                        "interface": "Alexa.MotionSensor",
                        "version": "3",
                        "properties": {
                            "supported": [{"name": "detectionState"}],
                            "proactivelyReported": False,
                            "retrievable": True,
                        },
                    },
                    {
                        "type": "AlexaInterface",
                        "interface": "Alexa.EndpointHealth",
                        "version": "3.2",
                        "properties": {
                            "supported": [{"name": "connectivity"}],
                            "proactivelyReported": False,
                            "retrievable": True,
                        },
                    },
                ],
            }
        )
    return {
        "event": {
            "header": {
                "namespace": "Alexa.Discovery",
                "name": "Discover.Response",
                "payloadVersion": "3",
                "messageId": str(uuid.uuid4()),
            },
            "payload": {"endpoints": endpoints},
        }
    }


def _state_report(
    directive: dict[str, Any], state: dict[str, Any]
) -> dict[str, Any]:
    endpoint = directive["endpoint"]
    room_id = endpoint.get("cookie", {}).get("roomId") or _room_id(
        endpoint["endpointId"]
    )
    room = next(
        (item for item in state.get("rooms", []) if item["room_id"] == room_id),
        None,
    )
    occupied = bool(room and room.get("occupancy"))
    now = _timestamp()
    return {
        "context": {
            "properties": [
                {
                    "namespace": "Alexa.MotionSensor",
                    "name": "detectionState",
                    "value": "DETECTED" if occupied else "NOT_DETECTED",
                    "timeOfSample": now,
                    "uncertaintyInMilliseconds": 2000,
                },
                {
                    "namespace": "Alexa.EndpointHealth",
                    "name": "connectivity",
                    "value": {"value": "OK"},
                    "timeOfSample": now,
                    "uncertaintyInMilliseconds": 2000,
                },
            ]
        },
        "event": {
            "header": {
                "namespace": "Alexa",
                "name": "StateReport",
                "payloadVersion": "3",
                "messageId": str(uuid.uuid4()),
                "correlationToken": directive["header"].get("correlationToken"),
            },
            "endpoint": {"endpointId": endpoint["endpointId"]},
            "payload": {},
        },
    }


def _speech(text: str, *, should_end: bool = True) -> dict[str, Any]:
    return {
        "version": "1.0",
        "response": {
            "outputSpeech": {"type": "PlainText", "text": text},
            "shouldEndSession": should_end,
        },
    }


def _custom_skill(event: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    request = event.get("request", {})
    if request.get("type") == "LaunchRequest":
        return _speech(
            "RF Sense pronto. Pergunte quantas pessoas há ou os sinais de um ambiente.",
            should_end=False,
        )
    intent = request.get("intent", {})
    name = intent.get("name")
    slots = intent.get("slots", {})
    spoken_room = (
        slots.get("room", {}).get("value", "").strip().casefold()
    )
    rooms = state.get("rooms", [])
    environment_rooms = state.get("environment", {}).get("rooms", [])
    labels = {
        str(room["id"]): str(room["name"]) for room in environment_rooms
    }
    room = next(
        (
            item
            for item in rooms
            if spoken_room in {
                str(item["room_id"]).casefold(),
                labels.get(str(item["room_id"]), "").casefold(),
            }
        ),
        rooms[0] if len(rooms) == 1 else None,
    )
    if name == "GetPeopleCountIntent":
        summary = state.get("summary", {})
        count = int(summary.get("people_count", 0))
        qualifier = "" if summary.get("count_valid") else " aproximadamente"
        return _speech(f"Há{qualifier} {count} pessoas detectadas.")
    if room is None:
        return _speech("Não encontrei esse ambiente no mapa RF Sense.")
    label = labels.get(str(room["room_id"]), str(room["room_id"]))
    if name == "GetRoomOccupancyIntent":
        answer = "há presença" if room.get("occupancy") else "não há presença"
        return _speech(f"No ambiente {label}, {answer}.")
    if name == "GetVitalSignsIntent":
        person = next(
            (
                item
                for item in state.get("people", [])
                if item.get("room_id") == room["room_id"]
            ),
            None,
        )
        vitals = person.get("vital_signs", {}) if person else {}
        breathing = vitals.get("breathing_bpm")
        heart = vitals.get("heart_bpm")
        if breathing is None and heart is None:
            return _speech(
                f"Não há estimativa confiável de sinais no ambiente {label}."
            )
        parts = []
        if breathing is not None:
            parts.append(f"respiração estimada em {round(breathing)} por minuto")
        if heart is not None:
            parts.append(f"frequência cardíaca estimada em {round(heart)}")
        return _speech(
            f"No ambiente {label}, " + " e ".join(parts)
            + ". São estimativas experimentais, não medições médicas."
        )
    return _speech("Não entendi a consulta ao RF Sense.")


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    state = _shadow()
    directive = event.get("directive")
    if directive:
        header = directive.get("header", {})
        if (
            header.get("namespace") == "Alexa.Discovery"
            and header.get("name") == "Discover"
        ):
            return _discovery(state)
        if (
            header.get("namespace") == "Alexa"
            and header.get("name") == "ReportState"
        ):
            return _state_report(directive, state)
        raise ValueError(
            f"diretiva Alexa não suportada: "
            f"{header.get('namespace')}.{header.get('name')}"
        )
    return _custom_skill(event, state)

