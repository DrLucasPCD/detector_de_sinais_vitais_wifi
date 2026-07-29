from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any


class HomeKitBridge:
    """Local HAP bridge. It has no Home Assistant dependency."""

    def __init__(
        self,
        snapshot: Callable[[], dict[str, object]],
        rooms: list[dict[str, object]],
        *,
        port: int,
        pin: str,
        persist_file: str,
    ) -> None:
        self.snapshot = snapshot
        self.rooms = rooms
        self.port = port
        self.pin = pin
        self.persist_file = persist_file
        self.driver: Any = None
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        try:
            from pyhap.accessory import Accessory, Bridge
            from pyhap.accessory_driver import AccessoryDriver
            from pyhap.const import CATEGORY_SENSOR
        except ImportError as exc:
            raise RuntimeError(
                "HomeKit ativado, mas HAP-python não está instalado; "
                "instale rf-sense[homekit]"
            ) from exc

        snapshot_provider = self.snapshot

        class RoomSensor(Accessory):
            category = CATEGORY_SENSOR

            def __init__(
                accessory_self: Any,
                driver: Any,
                display_name: str,
                room_id: str,
            ) -> None:
                super().__init__(driver, display_name)
                accessory_self.room_id = room_id
                occupancy = accessory_self.add_preload_service("OccupancySensor")
                motion = accessory_self.add_preload_service("MotionSensor")
                accessory_self.occupancy = occupancy.configure_char(
                    "OccupancyDetected", value=0
                )
                accessory_self.motion = motion.configure_char(
                    "MotionDetected", value=False
                )

            @Accessory.run_at_interval(2)
            async def run(accessory_self: Any) -> None:
                state = snapshot_provider()
                room = next(
                    (
                        item
                        for item in state.get("rooms", [])
                        if item.get("room_id") == accessory_self.room_id
                    ),
                    None,
                )
                occupied = bool(room and room.get("occupancy"))
                accessory_self.occupancy.set_value(1 if occupied else 0)
                accessory_self.motion.set_value(occupied)

        self.driver = AccessoryDriver(
            port=self.port,
            pincode=self.pin.encode("ascii"),
            persist_file=self.persist_file,
        )
        bridge = Bridge(self.driver, "RF Sense")
        for room in self.rooms:
            bridge.add_accessory(
                RoomSensor(
                    self.driver,
                    f"Presença {room['name']}",
                    str(room["id"]),
                )
            )
        self.driver.add_accessory(accessory=bridge)
        self.thread = threading.Thread(
            target=self.driver.start,
            name="rf-sense-homekit",
            daemon=True,
        )
        self.thread.start()

    def stop(self) -> None:
        if self.driver is not None:
            self.driver.stop()
        if self.thread is not None:
            self.thread.join(timeout=3)

