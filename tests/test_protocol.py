from pathlib import Path

import pytest

from rf_sense.protocol import (
    HEADER,
    ProtocolError,
    RawCSIFrame,
    encode_raw_frame,
    parse_datagram,
)

GOLDEN = (
    Path(__file__).parents[1]
    / "protocol"
    / "golden"
    / "raw-csi-v1-node1-4sc.hex"
)


def test_golden_vector() -> None:
    payload = bytes.fromhex(GOLDEN.read_text())
    frame = parse_datagram(payload, received_at=123.0)
    assert frame.node_id == 1
    assert frame.n_subcarriers == 4
    assert frame.frequency_mhz == 2437
    assert frame.sequence == 42
    assert frame.rssi_dbm == -48
    assert frame.noise_floor_dbm == -94
    assert frame.iq == ((10, -10), (20, -20), (30, -30), (40, -40))
    assert encode_raw_frame(frame) == payload


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        (b"", "truncated"),
        (b"\x01\x00\x11\xc5", "truncated"),
        (b"\xff\xff\xff\xff" + b"\x00" * 16, "bad_magic"),
        (
            HEADER.pack(0xC5110001, 1, 0, 64, 2437, 1, -48, -94, 0),
            "antenna_count",
        ),
        (
            HEADER.pack(0xC5110001, 1, 1, 513, 2437, 1, -48, -94, 0),
            "subcarrier_count",
        ),
    ],
)
def test_rejects_invalid_frames(payload: bytes, code: str) -> None:
    with pytest.raises(ProtocolError) as error:
        parse_datagram(payload)
    assert error.value.code == code


def test_roundtrip() -> None:
    frame = RawCSIFrame(
        node_id=7,
        n_antennas=1,
        n_subcarriers=2,
        frequency_mhz=2412,
        sequence=0xFFFFFFFF,
        rssi_dbm=-61,
        noise_floor_dbm=-95,
        flags=1,
        iq=((-128, 127), (0, -1)),
        received_at=5.0,
    )
    parsed = parse_datagram(encode_raw_frame(frame), received_at=5.0)
    assert parsed == frame

