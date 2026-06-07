"""Unit tests for the pure circuit-breaker state machine (deterministic, injected clock)."""
from src.infra.resilience import CircuitBreaker


def test_opens_after_fail_max_and_blocks():
    cb = CircuitBreaker(fail_max=3, reset_after=30)
    assert cb.allow(0) is True
    for _ in range(3):
        cb.record_failure(now=10)
    assert cb.state == "open"
    assert cb.allow(now=11) is False           # still cooling down → blocked


def test_half_open_after_reset_then_close_on_success():
    cb = CircuitBreaker(fail_max=2, reset_after=30)
    cb.record_failure(now=0)
    cb.record_failure(now=0)
    assert cb.state == "open"
    assert cb.allow(now=31) is True            # cooled down → half_open lets one through
    assert cb.state == "half_open"
    cb.record_success()
    assert cb.state == "closed" and cb.allow(now=40) is True


def test_half_open_failure_reopens():
    cb = CircuitBreaker(fail_max=1, reset_after=10)
    cb.record_failure(now=0)
    assert cb.allow(now=11) is True            # half_open
    cb.record_failure(now=11)                  # fails again → straight back to open
    assert cb.state == "open" and cb.allow(now=12) is False


def test_success_resets_failure_count():
    cb = CircuitBreaker(fail_max=3, reset_after=30)
    cb.record_failure(now=0)
    cb.record_failure(now=0)
    cb.record_success()                        # resets the counter
    cb.record_failure(now=1)
    assert cb.state == "closed"                # 1 failure post-reset, below fail_max
