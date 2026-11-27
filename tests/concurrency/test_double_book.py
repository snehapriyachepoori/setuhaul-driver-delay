"""T-01 integrity proof: 10 threads, one slot, 100 repeats, 0 double bookings.
Plus a control run with protection OFF that does double book (the test can fail)."""
import os

from tests.concurrency.harness import run_race

REPEATS = int(os.environ.get("INTEGRITY_REPEATS", "100"))


def test_protected_path_never_double_books(tmp_path):
    t = run_race(tmp_path, "protected", repeats=REPEATS)
    assert t["ERROR"] == 0, t.get("errors")
    assert t["double_bookings"] == 0
    assert t["per_repeat_confirmed"] == [1] * REPEATS        # exactly one winner every time
    assert t["CONFIRMED"] == REPEATS and t["REFUSED"] == 9 * REPEATS


def test_control_without_any_protection_does_double_book(tmp_path):
    t = run_race(tmp_path, "naive_index_off", repeats=20)
    assert t["double_bookings"] > 0, "control should fail; if it never fails the test proves nothing"
