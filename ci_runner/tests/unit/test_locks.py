"""Tests for app/locks.py."""
from __future__ import annotations

import threading

from app.locks import RunLock


def test_acquire_and_release(run_lock: RunLock):
    assert run_lock.try_acquire("run-1") is True
    assert run_lock.current() == "run-1"
    run_lock.release()
    assert run_lock.current() is None


def test_double_acquire_blocked(run_lock: RunLock):
    assert run_lock.try_acquire("run-1") is True
    assert run_lock.try_acquire("run-2") is False
    assert run_lock.current() == "run-1"
    run_lock.release()


def test_acquire_after_release(run_lock: RunLock):
    assert run_lock.try_acquire("run-1") is True
    run_lock.release()
    assert run_lock.try_acquire("run-2") is True
    assert run_lock.current() == "run-2"
    run_lock.release()


def test_context_manager_acquired(run_lock: RunLock):
    with run_lock.acquired("run-1") as got:
        assert got is True
        assert run_lock.current() == "run-1"
    assert run_lock.current() is None


def test_context_manager_not_acquired(run_lock: RunLock):
    run_lock.try_acquire("run-1")
    with run_lock.acquired("run-2") as got:
        assert got is False
        assert run_lock.current() == "run-1"  # still locked by run-1
    run_lock.release()


def test_thread_safety(run_lock: RunLock):
    """One thread holds the lock; the other can't get it."""
    results = []
    hold = threading.Event()
    released = threading.Event()

    def holder():
        if run_lock.try_acquire("holder"):
            results.append("holder")
            hold.set()  # tell the other thread we have the lock
            released.wait(timeout=5)  # hold it until tester is done
            run_lock.release()

    def tester():
        hold.wait(timeout=5)  # wait until holder has the lock
        if run_lock.try_acquire("tester"):
            results.append("tester")
            run_lock.release()
        released.set()

    threads = [threading.Thread(target=holder), threading.Thread(target=tester)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results == ["holder"]