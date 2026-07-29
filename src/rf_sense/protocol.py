from __future__ import annotations

import struct
import time
from dataclasses import dataclass

RAW_CSI_MAGIC = 0xC5110001
VITALS_MAGIC = 0xC5110002
WASM_EVENT_MAGIC = 0xC5110004
HEADER = struct.Struct("<IBBHIIbbH")
MAX_ANTENNAS = 4
MAX_SUBCARRIERS = 512
MAX_DATAGRAM_BYTES = HEADER.size + MAX_ANTENNAS * MAX_SUBCARRIERS * 2


class ProtocolError(ValueError):
    """Datagrama inválido ou incompatível."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class RawCSIFrame:
    node_id: int
    n_antennas: int
    n_subcarriers: int
    frequency_mhz: int
    sequence: int
    rssi_dbm: int
    noise_floor_dbm: int
    flags: int
    iq: tuple[tuple[int, int], ...]
    received_at: float

    @property
    def sample_count(self) -> int:
        return self.n_antennas * self.n_subcarriers

    def amplitudes(self) -> tuple[float, ...]:
        return tuple((i * i + q * q) ** 0.5 for i, q in self.iq)


def parse_datagram(data: bytes, received_at: float | None = None) -> RawCSIFrame:
    if len(data) < 4:
        raise ProtocolError("truncated", "datagrama menor que o magic")
    if len(data) > MAX_DATAGRAM_BYTES:
        raise ProtocolError("too_large", "datagrama excede o limite")
    if len(data) < HEADER.size:
        raise ProtocolError("truncated", "cabeçalho wire v1 incompleto")

    (
        magic,
        node_id,
        n_antennas,
        n_subcarriers,
        frequency_mhz,
        sequence,
        rssi_dbm,
        noise_floor_dbm,
        flags,
    ) = HEADER.unpack_from(data)

    if magic != RAW_CSI_MAGIC:
        if magic in {VITALS_MAGIC, WASM_EVENT_MAGIC}:
            raise ProtocolError("unsupported_type", f"tipo 0x{magic:08x} não ativo")
        raise ProtocolError("bad_magic", f"magic desconhecido 0x{magic:08x}")
    if not 1 <= n_antennas <= MAX_ANTENNAS:
        raise ProtocolError("antenna_count", "quantidade de antenas impossível")
    if not 1 <= n_subcarriers <= MAX_SUBCARRIERS:
        raise ProtocolError(
            "subcarrier_count", "quantidade de subportadoras impossível"
        )
    if not 2_400 <= frequency_mhz <= 2_500:
        raise ProtocolError("frequency", "frequência fora da banda de 2,4 GHz")

    sample_count = n_antennas * n_subcarriers
    expected_size = HEADER.size + sample_count * 2
    if len(data) != expected_size:
        raise ProtocolError(
            "size_mismatch",
            f"tamanho {len(data)} diverge do esperado {expected_size}",
        )

    raw_iq = struct.unpack_from(f"<{sample_count * 2}b", data, HEADER.size)
    iq = tuple(zip(raw_iq[0::2], raw_iq[1::2], strict=True))
    return RawCSIFrame(
        node_id=node_id,
        n_antennas=n_antennas,
        n_subcarriers=n_subcarriers,
        frequency_mhz=frequency_mhz,
        sequence=sequence,
        rssi_dbm=rssi_dbm,
        noise_floor_dbm=noise_floor_dbm,
        flags=flags,
        iq=iq,
        received_at=time.monotonic() if received_at is None else received_at,
    )


def encode_raw_frame(frame: RawCSIFrame) -> bytes:
    if len(frame.iq) != frame.sample_count:
        raise ProtocolError("sample_count", "I/Q não corresponde ao cabeçalho")
    header = HEADER.pack(
        RAW_CSI_MAGIC,
        frame.node_id,
        frame.n_antennas,
        frame.n_subcarriers,
        frame.frequency_mhz,
        frame.sequence,
        frame.rssi_dbm,
        frame.noise_floor_dbm,
        frame.flags,
    )
    flat = tuple(value for pair in frame.iq for value in pair)
    try:
        return header + struct.pack(f"<{len(flat)}b", *flat)
    except struct.error as exc:
        raise ProtocolError("iq_range", "I/Q deve caber em int8") from exc

