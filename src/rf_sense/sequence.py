from __future__ import annotations

import statistics
from collections import deque
from dataclasses import dataclass, field

UINT32_MOD = 2**32
UINT32_HALF = 2**31


@dataclass(slots=True)
class SequenceTracker:
    last_sequence: int | None = None
    received: int = 0
    lost: int = 0
    reordered: int = 0
    duplicates: int = 0
    timestamps: deque[float] = field(default_factory=lambda: deque(maxlen=200))

    def observe(self, sequence: int, timestamp: float) -> None:
        self.received += 1
        self.timestamps.append(timestamp)
        if self.last_sequence is None:
            self.last_sequence = sequence
            return

        forward = (sequence - self.last_sequence) % UINT32_MOD
        if forward == 0:
            self.duplicates += 1
            return
        if forward < UINT32_HALF:
            self.lost += max(0, forward - 1)
            self.last_sequence = sequence
            return
        self.reordered += 1

    @property
    def packet_loss(self) -> float:
        expected = self.received + self.lost
        return self.lost / expected if expected else 0.0

    @property
    def fps(self) -> float:
        if len(self.timestamps) < 2:
            return 0.0
        duration = self.timestamps[-1] - self.timestamps[0]
        return (len(self.timestamps) - 1) / duration if duration > 0 else 0.0

    @property
    def jitter_ms(self) -> float:
        if len(self.timestamps) < 3:
            return 0.0
        intervals = [
            b - a for a, b in zip(self.timestamps, list(self.timestamps)[1:])
        ]
        return statistics.pstdev(intervals) * 1000

