from __future__ import annotations

import asyncio
import ipaddress
from collections.abc import Iterable

from .processing import SensorEngine
from .protocol import ProtocolError, parse_datagram


class SenderAllowlist:
    def __init__(self, entries: Iterable[str]) -> None:
        self.networks = []
        for entry in entries:
            try:
                self.networks.append(ipaddress.ip_network(entry, strict=False))
            except ValueError as exc:
                raise ValueError(f"RF_ALLOWED_SENDERS inválido: {entry}") from exc

    def allows(self, address: str) -> bool:
        ip = ipaddress.ip_address(address)
        return any(ip in network for network in self.networks)


class CSIUDPProtocol(asyncio.DatagramProtocol):
    def __init__(
        self,
        engine: SensorEngine,
        allowed_senders: Iterable[str],
        simulator_active: bool,
    ) -> None:
        self.engine = engine
        self.allowlist = SenderAllowlist(allowed_senders)
        self.simulator_active = simulator_active
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport  # type: ignore[assignment]

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        source_ip = addr[0]
        if not self.allowlist.allows(source_ip):
            self.engine.reject("sender_not_allowed")
            return
        try:
            frame = parse_datagram(data)
        except ProtocolError as exc:
            self.engine.reject(exc.code)
            return
        source = (
            "simulator"
            if self.simulator_active and ipaddress.ip_address(source_ip).is_loopback
            else "esp32"
        )
        self.engine.process(frame, source_ip=source_ip, source=source)

    def error_received(self, exc: Exception) -> None:
        self.engine.counters["udp_errors"] += 1


async def create_udp_receiver(
    engine: SensorEngine,
    host: str,
    port: int,
    allowed_senders: Iterable[str],
    simulator_active: bool,
) -> asyncio.DatagramTransport:
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(
        lambda: CSIUDPProtocol(engine, allowed_senders, simulator_active),
        local_addr=(host, port),
    )
    return transport  # type: ignore[return-value]

