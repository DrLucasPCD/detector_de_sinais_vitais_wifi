from __future__ import annotations

import argparse
import asyncio
import math
import random
import time
from dataclasses import dataclass, field

from .protocol import RawCSIFrame, encode_raw_frame


def _int8(value: float) -> int:
    return max(-128, min(127, round(value)))


@dataclass(slots=True)
class SyntheticCSIGenerator:
    seed: int = 42
    node_id: int = 1
    subcarriers: int = 64
    fps: float = 20.0
    breathing_hz: float = 0.25
    heart_hz: float = 1.2
    noise_sigma: float = 0.22
    sequence: int = 0
    _random: random.Random = field(init=False, repr=False)
    _phases: tuple[float, ...] = field(init=False, repr=False)
    _base: tuple[float, ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._random = random.Random(self.seed)
        self._phases = tuple(
            self._random.uniform(-math.pi, math.pi)
            for _ in range(self.subcarriers)
        )
        self._base = tuple(
            self._random.uniform(35.0, 62.0) for _ in range(self.subcarriers)
        )

    def frame(self, now: float, mode: str) -> RawCSIFrame:
        breathing = math.sin(2 * math.pi * self.breathing_hz * now)
        heart = math.sin(2 * math.pi * self.heart_hz * now)
        iq: list[tuple[int, int]] = []
        for index, (base, phase) in enumerate(
            zip(self._base, self._phases, strict=True)
        ):
            noise = self._random.gauss(0.0, self.noise_sigma)
            if mode == "empty":
                amplitude = base + noise
                phase_shift = self._random.gauss(0.0, 0.004)
            elif mode == "still":
                sensitivity = 0.75 + (index % 9) / 12
                amplitude = (
                    base
                    + 3.5
                    + 1.65 * breathing * sensitivity
                    + 0.42 * heart
                    + noise
                )
                phase_shift = 0.035 * breathing + 0.008 * heart
            else:
                motion = (
                    6.0 * math.sin(2 * math.pi * 1.7 * now + index * 0.19)
                    + self._random.gauss(0.0, 2.2)
                )
                amplitude = base + 4.0 + motion + noise
                phase_shift = 0.25 * math.sin(2 * math.pi * 0.9 * now + index)
            angle = phase + phase_shift
            iq.append(
                (
                    _int8(amplitude * math.cos(angle)),
                    _int8(amplitude * math.sin(angle)),
                )
            )

        frame = RawCSIFrame(
            node_id=self.node_id,
            n_antennas=1,
            n_subcarriers=self.subcarriers,
            frequency_mhz=2437,
            sequence=self.sequence,
            rssi_dbm=-48 + self._random.randint(-1, 1),
            noise_floor_dbm=-94,
            flags=0,
            iq=tuple(iq),
            received_at=now,
        )
        self.sequence = (self.sequence + 1) % 2**32
        return frame


def scenario_at(scenario: str, elapsed: float) -> str:
    if scenario != "cycle":
        return scenario
    if elapsed < 35:
        return "empty"
    phase = (elapsed - 35) % 60
    if phase < 30:
        return "still"
    if phase < 45:
        return "moving"
    return "still"


async def run_simulator(
    host: str = "127.0.0.1",
    port: int = 5005,
    scenario: str = "cycle",
    seed: int = 42,
    node_id: int = 1,
    fps: float = 20.0,
) -> None:
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(
        asyncio.DatagramProtocol,
        remote_addr=(host, port),
    )
    generator = SyntheticCSIGenerator(seed=seed, node_id=node_id, fps=fps)
    start = time.monotonic()
    interval = 1.0 / fps
    next_tick = start
    try:
        while True:
            now = time.monotonic()
            mode = scenario_at(scenario, now - start)
            frame = generator.frame(now, mode)
            transport.sendto(encode_raw_frame(frame))
            next_tick += interval
            await asyncio.sleep(max(0.0, next_tick - time.monotonic()))
    finally:
        transport.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulador CSI wire v1")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5005)
    parser.add_argument(
        "--scenario",
        choices=("cycle", "empty", "still", "moving"),
        default="cycle",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--node-id", type=int, default=1)
    parser.add_argument("--fps", type=float, default=20.0)
    args = parser.parse_args()
    asyncio.run(
        run_simulator(
            host=args.host,
            port=args.port,
            scenario=args.scenario,
            seed=args.seed,
            node_id=args.node_id,
            fps=args.fps,
        )
    )


if __name__ == "__main__":
    main()
