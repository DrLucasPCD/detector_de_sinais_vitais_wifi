from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    value = default if raw is None else int(raw)
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} deve estar entre {minimum} e {maximum}")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    http_host: str
    http_port: int
    udp_host: str
    udp_port: int
    allowed_senders: tuple[str, ...]
    allowed_origins: tuple[str, ...]
    simulator: bool
    simulator_scenario: str
    simulator_seed: int
    calibration_frames: int
    stale_after_seconds: int
    api_token: str | None
    environment_file: str | None
    homekit_enabled: bool
    homekit_port: int
    homekit_pin: str | None
    homekit_persist_file: str
    alexa_iot_enabled: bool
    aws_iot_endpoint: str | None
    aws_iot_thing_name: str
    aws_iot_cert: str | None
    aws_iot_key: str | None
    aws_iot_ca: str | None
    home_assistant_enabled: bool
    mqtt_host: str | None
    mqtt_port: int
    mqtt_username: str | None
    mqtt_password: str | None
    mqtt_tls: bool
    mqtt_discovery_prefix: str

    @classmethod
    def from_env(cls) -> "Settings":
        http_host = os.getenv("RF_HTTP_HOST", "127.0.0.1").strip()
        api_token = os.getenv("RF_API_TOKEN", "").strip() or None
        if not _is_loopback_host(http_host) and not api_token:
            raise ValueError(
                "RF_API_TOKEN é obrigatório quando RF_HTTP_HOST não é loopback"
            )

        senders = tuple(
            item.strip()
            for item in os.getenv("RF_ALLOWED_SENDERS", "127.0.0.1").split(",")
            if item.strip()
        )
        origins = tuple(
            item.strip()
            for item in os.getenv("RF_ALLOWED_ORIGINS", "").split(",")
            if item.strip()
        )
        scenario = os.getenv("RF_SIMULATOR_SCENARIO", "cycle").strip().lower()
        if scenario not in {"cycle", "empty", "still", "moving"}:
            raise ValueError(
                "RF_SIMULATOR_SCENARIO deve ser cycle, empty, still ou moving"
            )

        return cls(
            http_host=http_host,
            http_port=_as_int("RF_HTTP_PORT", 8000, 1, 65535),
            udp_host=os.getenv("RF_UDP_HOST", "0.0.0.0").strip(),
            udp_port=_as_int("RF_UDP_PORT", 5005, 1, 65535),
            allowed_senders=senders,
            allowed_origins=origins,
            simulator=_as_bool(os.getenv("RF_SIMULATOR"), False),
            simulator_scenario=scenario,
            simulator_seed=_as_int("RF_SIMULATOR_SEED", 42, 0, 2**31 - 1),
            calibration_frames=_as_int(
                "RF_CALIBRATION_FRAMES", 600, 100, 100_000
            ),
            stale_after_seconds=_as_int(
                "RF_STALE_AFTER_SECONDS", 10, 2, 3600
            ),
            api_token=api_token,
            environment_file=os.getenv("RF_ENVIRONMENT_FILE", "").strip() or None,
            homekit_enabled=_as_bool(os.getenv("RF_HOMEKIT_ENABLED"), False),
            homekit_port=_as_int("RF_HOMEKIT_PORT", 51826, 1, 65535),
            homekit_pin=os.getenv("RF_HOMEKIT_PIN", "").strip() or None,
            homekit_persist_file=os.getenv(
                "RF_HOMEKIT_PERSIST_FILE", ".rf-sense-homekit.state"
            ).strip(),
            alexa_iot_enabled=_as_bool(
                os.getenv("RF_ALEXA_IOT_ENABLED"), False
            ),
            aws_iot_endpoint=os.getenv("RF_AWS_IOT_ENDPOINT", "").strip()
            or None,
            aws_iot_thing_name=os.getenv(
                "RF_AWS_IOT_THING_NAME", "rf-sense-local"
            ).strip(),
            aws_iot_cert=os.getenv("RF_AWS_IOT_CERT", "").strip() or None,
            aws_iot_key=os.getenv("RF_AWS_IOT_KEY", "").strip() or None,
            aws_iot_ca=os.getenv("RF_AWS_IOT_CA", "").strip() or None,
            home_assistant_enabled=_as_bool(
                os.getenv("RF_HOME_ASSISTANT_ENABLED"), False
            ),
            mqtt_host=os.getenv("RF_MQTT_HOST", "").strip() or None,
            mqtt_port=_as_int("RF_MQTT_PORT", 1883, 1, 65535),
            mqtt_username=os.getenv("RF_MQTT_USERNAME", "").strip() or None,
            mqtt_password=os.getenv("RF_MQTT_PASSWORD", "").strip() or None,
            mqtt_tls=_as_bool(os.getenv("RF_MQTT_TLS"), False),
            mqtt_discovery_prefix=os.getenv(
                "RF_MQTT_DISCOVERY_PREFIX", "homeassistant"
            ).strip(),
        )

    def public_dict(self) -> dict[str, object]:
        return {
            "http_bind": f"{self.http_host}:{self.http_port}",
            "udp_bind": f"{self.udp_host}:{self.udp_port}",
            "allowed_senders": list(self.allowed_senders),
            "allowed_origins": list(self.allowed_origins),
            "simulator": self.simulator,
            "simulator_scenario": self.simulator_scenario,
            "calibration_frames": self.calibration_frames,
            "stale_after_seconds": self.stale_after_seconds,
            "auth_enabled": self.api_token is not None,
            "environment_file": self.environment_file,
            "integrations": {
                "homekit": {
                    "enabled": self.homekit_enabled,
                    "mode": "direct_hap",
                    "port": self.homekit_port,
                },
                "alexa": {
                    "enabled": self.alexa_iot_enabled,
                    "mode": "direct_aws_iot",
                    "thing_name": self.aws_iot_thing_name,
                },
                "home_assistant": {
                    "enabled": self.home_assistant_enabled,
                    "mode": "independent_mqtt_discovery",
                    "broker_configured": self.mqtt_host is not None,
                },
            },
        }


def _is_loopback_host(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False
