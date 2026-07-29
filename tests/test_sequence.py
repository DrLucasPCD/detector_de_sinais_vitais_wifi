from rf_sense.sequence import SequenceTracker


def test_counts_gap_and_duplicate() -> None:
    tracker = SequenceTracker()
    tracker.observe(10, 0.0)
    tracker.observe(11, 0.05)
    tracker.observe(14, 0.10)
    tracker.observe(14, 0.15)
    assert tracker.received == 4
    assert tracker.lost == 2
    assert tracker.duplicates == 1
    assert tracker.reordered == 0


def test_uint32_wrap_is_forward_progress() -> None:
    tracker = SequenceTracker()
    tracker.observe(0xFFFFFFFE, 0.0)
    tracker.observe(0xFFFFFFFF, 0.05)
    tracker.observe(0, 0.10)
    assert tracker.lost == 0
    assert tracker.reordered == 0


def test_out_of_order_does_not_advance_last_sequence() -> None:
    tracker = SequenceTracker()
    tracker.observe(100, 0.0)
    tracker.observe(99, 0.05)
    tracker.observe(101, 0.10)
    assert tracker.reordered == 1
    assert tracker.lost == 0

