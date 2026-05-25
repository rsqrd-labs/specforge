import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


@pytest.fixture(autouse=True)
def _reset_shared_redis():
    """Reset the module-level shared Redis singleton between tests.

    Some tests inject a _NoopRedis (lacking 'delete') via create_app().
    Without this reset, that stale client leaks into subsequent tests that
    call credit_service.invalidate() -> _invalidate() -> redis.delete().
    H-2 — T-219.
    """
    import database

    original = database._shared_redis
    yield
    database._shared_redis = original
