"""Contención SDK debe ser recuperable, sin 500 ni cambio de almacenamiento."""

import threading
from types import SimpleNamespace

import pytest

from umbral_api.errors import ServiceUnavailable, VersionConflict
from umbral_api.storage import FirestoreRepository

pytest.importorskip("google.api_core.exceptions", reason="La persistencia web necesita el extra firebase; la suite web se ejecuta con --extra firebase.")


def repository():
    repo = FirestoreRepository.__new__(FirestoreRepository)
    repo._write_lock = threading.Lock()
    repo._db = SimpleNamespace(transaction=object)
    return repo


def test_sdk_exhausted_aborted_is_controlled_retryable_503():
    from google.api_core.exceptions import Aborted

    def transaction(_):
        try:
            raise Aborted("Synthetic emulator contention")
        except Aborted as cause:
            raise ValueError("Failed to commit transaction in 5 attempts") from cause

    with pytest.raises(ServiceUnavailable) as failure:
        repository()._run_transaction(transaction)
    assert failure.value.status_code == 503
    assert failure.value.headers == {"Retry-After": "1"}
    assert repository().kind == "firestore"


def test_version_conflicts_are_still_409_not_retried_or_overwritten():
    def transaction(_):
        raise VersionConflict("Expected version does not match")

    with pytest.raises(VersionConflict) as failure:
        repository()._run_transaction(transaction)
    assert failure.value.status_code == 409
