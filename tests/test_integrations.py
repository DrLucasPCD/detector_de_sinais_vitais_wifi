import importlib.util
from pathlib import Path

from rf_sense.integrations import mqtt_publishers


class FakeMqttClient:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str, int, bool]] = []

    def username_pw_set(self, *_args: object) -> None:
        pass

    def connect(self, *_args: object, **_kwargs: object) -> None:
        pass

    def loop_start(self) -> None:
        pass

    def publish(
        self, topic: str, payload: str, qos: int = 0, retain: bool = False
    ) -> None:
        self.messages.append((topic, payload, qos, retain))

    def disconnect(self) -> None:
        pass

    def loop_stop(self) -> None:
        pass


def test_home_assistant_publishes_its_own_discovery_and_state(
    monkeypatch,
) -> None:
    client = FakeMqttClient()
    monkeypatch.setattr(mqtt_publishers, "_mqtt_client", lambda _id: client)
    publisher = mqtt_publishers.HomeAssistantPublisher(
        host="mqtt.local",
        port=1883,
        username=None,
        password=None,
        tls=False,
        discovery_prefix="homeassistant",
        rooms=[{"id": "sala", "name": "Sala"}],
    )
    publisher.start()
    publisher.publish(
        {
            "rooms": [
                {
                    "room_id": "sala",
                    "occupancy": True,
                    "people_count": 1,
                    "count_confidence": 0.9,
                }
            ],
            "people": [
                {
                    "room_id": "sala",
                    "vital_signs": {
                        "breathing_bpm": 16,
                        "heart_bpm": 72,
                    },
                }
            ],
        }
    )

    topics = {message[0] for message in client.messages}
    assert "homeassistant/binary_sensor/rf_sense/sala_occupancy/config" in topics
    assert "homeassistant/sensor/rf_sense/sala_heart/config" in topics
    assert "rf_sense/rooms/sala/state" in topics
    assert not any("homekit" in topic or "alexa" in topic for topic in topics)


def test_alexa_discovery_and_voice_vitals_are_direct() -> None:
    source = (
        Path(__file__).parents[1] / "integrations" / "alexa" / "lambda_function.py"
    )
    spec = importlib.util.spec_from_file_location("rf_sense_alexa", source)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    state = {
        "environment": {"rooms": [{"id": "sala", "name": "Sala"}]},
        "rooms": [
            {
                "room_id": "sala",
                "occupancy": True,
                "people_count": 1,
            }
        ],
        "people": [
            {
                "room_id": "sala",
                "vital_signs": {
                    "breathing_bpm": 16.2,
                    "heart_bpm": 72,
                },
            }
        ],
        "summary": {"people_count": 1, "count_valid": True},
    }

    discovery = module._discovery(state)
    endpoint = discovery["event"]["payload"]["endpoints"][0]
    assert endpoint["endpointId"] == "rf-sense-room-sala"
    assert any(
        item.get("interface") == "Alexa.MotionSensor"
        for item in endpoint["capabilities"]
    )

    response = module._custom_skill(
        {
            "request": {
                "type": "IntentRequest",
                "intent": {
                    "name": "GetVitalSignsIntent",
                    "slots": {"room": {"value": "sala"}},
                },
            }
        },
        state,
    )
    speech = response["response"]["outputSpeech"]["text"]
    assert "respiração estimada em 16" in speech
    assert "não medições médicas" in speech
