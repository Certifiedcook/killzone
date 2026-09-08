"""Dependency-free deterministic checks for the shared fixed-step scheduler."""

import math

from engine.clock import FixedStepClock


def close(actual, expected):
    assert math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12), (
        actual,
        expected,
    )


def rejects(call, error=ValueError):
    try:
        call()
    except error:
        return
    raise AssertionError("invalid input was accepted")


def test_frame_rates_and_exact_chunks_produce_identical_ticks():
    for fps in (24, 30, 47, 49, 60, 97, 143, 144):
        clock, ticks = FixedStepClock(), []
        for _ in range(fps * 10):
            clock.advance(1 / fps, ticks.append)
            assert 0 <= clock.alpha < 1
        assert ticks == [1 / 30] * 300, (fps, len(ticks))
        close(clock.accumulator, 0)
        assert clock.dropped_time == 0
    clock, ticks = FixedStepClock(step=0.1, max_frame=1), []
    for _ in range(1000):
        assert clock.advance(0.1, ticks.append) == 1
    for _ in range(300):
        clock.advance(0.1 / 3, ticks.append)
    assert len(ticks) == 1100
    close(clock.accumulator, 0)
    assert clock.dropped_time == 0
    for divisor in (7, 60, 1000):
        clock = FixedStepClock()
        count = sum(
            clock.advance(clock.step / divisor, lambda dt: None)
            for _ in range(divisor * 10)
        )
        assert count == 10
        close(clock.accumulator, 0)
    clock = FixedStepClock()
    assert clock.advance(clock.step * (1 - 1e-9), lambda dt: None) == 0
    assert clock.advance(clock.step * 1e-9, lambda dt: None) == 1


def test_speed_only_changes_new_time_and_zero_preserves_fraction():
    clock, ticks = FixedStepClock(step=0.1), []
    assert clock.advance(0.025, ticks.append, speed=2) == 0
    close(clock.alpha, 0.5)
    assert clock.advance(0.025, ticks.append) == 0
    assert clock.advance(10, ticks.append, speed=0) == 0
    close(clock.accumulator, 0.075)
    assert clock.dropped_time == 0
    assert clock.advance(0.025, ticks.append) == 1
    assert ticks == [0.1]
    close(clock.alpha, 0)


def test_stalls_are_bounded_and_dropped_time_uses_simulation_seconds():
    clock, ticks = FixedStepClock(step=0.1, max_steps=2, max_frame=0.5), []
    assert clock.advance(1, ticks.append, speed=2) == 2
    close(clock.dropped_time, 1.8)
    close(clock.accumulator, 0)
    clock = FixedStepClock(step=0.01, max_steps=3, max_frame=0.1)
    assert clock.advance(1e9, ticks.append) == 3
    close(clock.dropped_time, 1e9 - 0.03)
    assert 0 <= clock.alpha < 1
    # A finite scaled total can contain more steps than a float can represent.
    clock = FixedStepClock(step=1e-308, max_steps=2, max_frame=1e308)
    assert clock.advance(1e308, ticks.append) == 2
    assert math.isfinite(clock.dropped_time) and 0 <= clock.alpha < 1


def test_backlog_drops_whole_steps_and_preserves_remainder():
    clock, ticks = FixedStepClock(step=0.01, max_steps=1, max_frame=1), []
    assert clock.advance(0.025, ticks.append) == 1
    close(clock.accumulator, 0.005)
    close(clock.dropped_time, 0.01)
    assert clock.advance(0.005, ticks.append) == 1
    close(clock.accumulator, 0)
    close(clock.dropped_time, 0.01)
    clock = FixedStepClock(max_frame=0)
    assert clock.advance(2, ticks.append) == 0
    close(clock.dropped_time, 2)


def test_callback_exception_consumes_attempt_and_discards_pending_ticks():
    clock = FixedStepClock(step=0.1, max_steps=4, max_frame=1)
    attempted = []
    failure = RuntimeError("partially applied simulation update")

    def update(dt):
        attempted.append(dt)
        if len(attempted) == 2:
            raise failure

    try:
        clock.advance(0.35, update)
    except RuntimeError as exc:
        assert exc is failure
    else:
        raise AssertionError("callback exception was swallowed")
    assert attempted == [0.1, 0.1]
    close(clock.accumulator, 0.05)
    close(clock.dropped_time, 0.1)
    assert clock.advance(0.05, attempted.append) == 1
    assert attempted == [0.1] * 3
    close(clock.accumulator, 0)


def test_invalid_values_do_not_change_state_and_reset_clears_counters():
    bad_values = (-1, math.nan, math.inf, -math.inf, None)
    for bad in bad_values:
        rejects(lambda: FixedStepClock(step=bad))
        rejects(lambda: FixedStepClock(max_frame=bad))
    rejects(lambda: FixedStepClock(step=0))
    for bad in (0, -1, 1.5, math.nan, math.inf, True, None):
        rejects(lambda: FixedStepClock(max_steps=bad))
    clock = FixedStepClock(step=0.1, max_steps=1, max_frame=0.5)
    clock.advance(1.05, lambda dt: None)
    snapshot = (clock.accumulator, clock.dropped_time)
    for bad in bad_values:
        rejects(lambda: clock.advance(bad, lambda dt: None))
        rejects(lambda: clock.advance(0.1, lambda dt: None, speed=bad))
        assert (clock.accumulator, clock.dropped_time) == snapshot
    rejects(lambda: clock.advance(0.1, None), TypeError)
    rejects(lambda: clock.advance(1e308, lambda dt: None, speed=1e308))
    assert (clock.accumulator, clock.dropped_time) == snapshot
    clock.reset()
    assert clock.accumulator == clock.alpha == clock.dropped_time == 0
    assert clock.step == 0.1 and clock.max_steps == 1 and clock.max_frame == 0.5
    assert clock.advance(0.1, lambda dt: None) == 1


TESTS = [value for name, value in list(globals().items()) if name.startswith("test_")]


if __name__ == "__main__":
    for test in TESTS:
        test()
        print("PASS", test.__name__)
    print(f"ALL {len(TESTS)} CLOCK REGRESSIONS PASSED")
