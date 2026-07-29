from __future__ import annotations

import json
import ssl
from pathlib import Path
from typing import Any


def _mqtt_client(client_id: str) -> Any:
    try:
        import paho.mqtt.client as mqtt
    except ImportError as exc:
        raise RuntimeError(
            "Integração MQTT ativada, mas paho-mqtt não está instalado; "
            "instale rf-sense[integrations]"
        ) from exc
    return mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)


class HomeAssistantPublisher:
    """Publishes MQTT Discovery directly to a broker chosen by the user."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str | None,
        password: str | None,
        tls: bool,
        discovery_prefix: str,
        rooms: list[dict[str, object]],
    ) -> None:
        self.host = host
        self.port = port
        self.discovery_prefix = discovery_prefix.rstrip("/")
        self.rooms = rooms
        self.client = _mqtt_client("rf-sense-home-assistant")
        if username:
            self.client.username_pw_set(username, password)
        if tls:
            self.client.tls_set()

    def start(self) -> None:
        self.client.connect(self.host, self.port, keepalive=60)
        self.client.loop_start()
        device = {
            "identifiers": ["rf-sense-local"],
            "name": "RF Sense",
            "manufacturer": "RF Sense",
            "model": "ESP32-S3 CSI mesh",
        }
        for room in self.rooms:
            room_id = str(room["id"])
            state_topic = f"rf_sense/rooms/{room_id}/state"
            entities = {
                "occupancy": {
                    "platform": "binary_sensor",
                    "device_class": "occupancy",
                    "value_template": "{{ value_json.occupancy }}",
                    "payload_on": True,
                    "payload_off": False,
                },
                "people_count": {
                    "platform": "sensor",
                    "state_class": "measurement",
                    "unit_of_measurement": "pessoas",
                    "value_template": "{{ value_json.people_count }}",
                },
                "breathing": {
                    "platform": "sensor",
                    "state_class": "measurement",
                    "unit_of_measurement": "rpm",
                    "value_template": "{{ value_json.breathing_bpm }}",
                },
                "heart": {
                    "platform": "sensor",
                    "state_class": "measurement",
                    "unit_of_measurement": "bpm",
                    "value_template": "{{ value_json.heart_bpm }}",
                },
            }
            for key, entity in entities.items():
                platform = entity.pop("platform")
                payload = {
                    **entity,
                    "name": f"{room['name']} {key.replace('_', ' ')}",
                    "unique_id": f"rf_sense_{room_id}_{key}",
                    "state_topic": state_topic,
                    "device": device,
                    "availability_topic": "rf_sense/status",
                    "payload_available": "online",
                    "payload_not_available": "offline",
                }
                topic = (
                    f"{self.discovery_prefix}/{platform}/rf_sense/"
                    f"{room_id}_{key}/config"
                )
                self.client.publish(topic, json.dumps(payload), qos=1, retain=True)
        self.client.publish("rf_sense/status", "online", qos=1, retain=True)

    def publish(self, spatial: dict[str, object]) -> None:
        people = spatial.get("people", [])
        for room in spatial.get("rooms", []):
            room_id = room["room_id"]
            occupant = next(
                (person for person in people if person.get("room_id") == room_id),
                None,
            )
            vitals = occupant.get("vital_signs", {}) if occupant else {}
            state = {
                "occupancy": bool(room["occupancy"]),
                "people_count": room["people_count"],
                "count_confidence": room["count_confidence"],
                "breathing_bpm": vitals.get("breathing_bpm"),
                "heart_bpm": vitals.get("heart_bpm"),
                "experimental": True,
            }
            self.client.publish(
                f"rf_sense/rooms/{room_id}/state",
                json.dumps(state),
                qos=1,
                retain=True,
            )

    def stop(self) -> None:
        self.client.publish("rf_sense/status", "offline", qos=1, retain=True)
        self.client.disconnect()
        self.client.loop_stop()


class AwsIotShadowPublisher:
    """Publishes Alexa state to AWS IoT, independently of Home Assistant."""

    def __init__(
        self,
        *,
        endpoint: str,
        thing_name: str,
        cert: str,
        key: str,
        ca: str,
    ) -> None:
        for path in (cert, key, ca):
            if not Path(path).is_file():
                raise ValueError(f"arquivo AWS IoT não encontrado: {path}")
        self.thing_name = thing_name
        self.client = _mqtt_client(f"rf-sense-{thing_name}")
        self.client.tls_set(
            ca_certs=ca,
            certfile=cert,
            keyfile=key,
            tls_version=ssl.PROTOCOL_TLS_CLIENT,
        )
        self.endpoint = endpoint

    def start(self) -> None:
        self.client.connect(self.endpoint, 8883, keepalive=60)
        self.client.loop_start()

    def publish(self, spatial: dict[str, object]) -> None:
        desired = {
            "schema": spatial.get("schema"),
            "timestamp_host_ms": spatial.get("timestamp_host_ms"),
            "environment": spatial.get("environment"),
            "rooms": spatial.get("rooms"),
            "people": spatial.get("people"),
            "summary": spatial.get("summary"),
        }
        self.client.publish(
            f"$aws/things/{self.thing_name}/shadow/update",
            json.dumps({"state": {"reported": desired}}),
            qos=1,
        )

    def stop(self) -> None:
        self.client.disconnect()
        self.client.loop_stop()

