"""Bounded fixed-step scheduling without dependencies on rendering or gameplay."""

from math import isfinite, nextafter


def _nonnegative(value, name):
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be finite and nonnegative") from exc
    if not isfinite(value) or value < 0:
        raise ValueError(f"{name} must be finite and nonnegative")
    return value


class FixedStepClock:
    """Call callback(step) for elapsed simulation time, with bounded catch-up.

    Speed scales incoming elapsed time only. dropped_time is in simulation
    seconds: clamped wall time times speed, plus discarded whole-step backlog.
    Fractional time is retained even when catch-up is capped.

    If a callback raises, its attempted step is consumed because it may already
    have changed the simulation. Unattempted scheduled steps are dropped, the
    fractional remainder is preserved, and the exception propagates.
    """

    def __init__(self, step=1 / 30, max_steps=8, max_frame=0.25):
        self._step = _nonnegative(step, "step")
        if self._step == 0:
            raise ValueError("step must be positive")
        if (
            isinstance(max_steps, bool)
            or not isinstance(max_steps, int)
            or max_steps <= 0
        ):
            raise ValueError("max_steps must be a positive integer")
        self._max_steps = max_steps
        self._max_frame = _nonnegative(max_frame, "max_frame")
        self.reset()

    @property
    def step(self):
        return self._step

    @property
    def max_steps(self):
        return self._max_steps

    @property
    def max_frame(self):
        return self._max_frame

    @property
    def accumulator(self):
        return self._accumulator

    @property
    def dropped_time(self):
        return self._dropped_time

    @property
    def alpha(self):
        return min(self._accumulator / self._step, nextafter(1.0, 0.0))

    def reset(self):
        self._accumulator = 0.0
        self._dropped_time = 0.0

    def advance(self, elapsed, callback, *, speed=1.0):
        elapsed = _nonnegative(elapsed, "elapsed")
        speed = _nonnegative(speed, "speed")
        if not callable(callback):
            raise TypeError("callback must be callable")
        accepted = min(elapsed, self._max_frame)
        total = self._accumulator + accepted * speed
        dropped = (elapsed - accepted) * speed
        if not isfinite(total) or not isfinite(dropped + self._dropped_time):
            raise ValueError("scaled elapsed time exceeds finite clock capacity")

        whole_steps, remainder = divmod(total, self._step)
        # divmod(1.0, 0.1), for example, returns nine steps plus almost 0.1.
        # Allow accumulated roundoff across frames, not just the final division;
        # keep tolerance a tiny fraction of one tick even for large totals.
        tolerance = self._step * 1e-12
        if remainder and self._step - remainder <= tolerance:
            whole_steps += 1
            remainder = 0.0
        steps = self._max_steps if whole_steps >= self._max_steps else int(whole_steps)
        if whole_steps > self._max_steps:
            dropped += max(0.0, total - remainder - steps * self._step)
        if not isfinite(dropped + self._dropped_time):
            raise ValueError("dropped time exceeds finite clock capacity")

        # Commit the bounded schedule before callbacks so failures cannot replay
        # an attempted tick or leave a backlog to accumulate on the next frame.
        self._accumulator = remainder
        self._dropped_time += dropped
        for index in range(steps):
            try:
                callback(self._step)
            except BaseException:
                self._dropped_time += (steps - index - 1) * self._step
                raise
        return steps
