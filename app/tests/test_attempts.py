"""The guess limiter (app/models/attempts.py). Go's twin is
server/models/attempts_test.go."""
from __future__ import annotations

import threading
import unittest

from app.models.attempts import MAX_FAILURES, AttemptGuard


class AttemptGuardTest(unittest.TestCase):
    def test_parallel_guesses_cannot_pass_the_limit(self) -> None:
        """S4: guesses sent in parallel are reserved before they are judged,
        so twenty at once still get at most MAX_FAILURES evaluated."""
        guard = AttemptGuard()
        start = threading.Barrier(20)
        evaluated = []
        held = threading.Event()

        def guess() -> None:
            start.wait()
            attempt = guard.reserve(7)
            if attempt is None:
                return
            with attempt:
                evaluated.append(1)
                held.wait(0.2)  # judged slowly, as a real check is
                attempt.failed()

        threads = [threading.Thread(target=guess) for _ in range(20)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertLessEqual(len(evaluated), MAX_FAILURES)
        self.assertIsNone(guard.reserve(7), "not locked after the limit")

    def test_a_right_guess_forgives_and_a_void_one_costs_nothing(self) -> None:
        guard = AttemptGuard(max_failures=3)
        for _ in range(2):
            with guard.reserve(1) as attempt:
                attempt.failed()
        with guard.reserve(1) as attempt:
            attempt.passed()
        for _ in range(10):
            attempt = guard.reserve(1)
            self.assertIsNotNone(attempt, "a void attempt was counted")
            with attempt:
                pass
        for _ in range(2):
            with guard.reserve(1) as attempt:
                attempt.failed()
        with guard.reserve(1) as attempt:
            attempt.failed()
        self.assertIsNone(guard.reserve(1), "three misses did not lock")


if __name__ == "__main__":
    unittest.main()
