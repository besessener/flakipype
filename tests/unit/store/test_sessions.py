from flakipype.store.database import ScanCache
from flakipype.store.sessions import SessionSummary


def test_sessions_are_created_updated_listed_and_loaded(cache: ScanCache) -> None:
    store = cache.sessions
    first = store.create("Why does E2E fail?", now="2026-10-09T10:00:00Z", data='{"v": 1}')
    second = store.create("Recurring lint", now="2026-10-09T11:00:00Z", data='{"v": 2}')

    store.update(first, now="2026-10-09T12:00:00Z", data='{"v": 3}')

    assert store.load(first) == '{"v": 3}'
    assert store.load(999) is None
    assert store.recent(1) == [SessionSummary(first, "Why does E2E fail?", "2026-10-09T12:00:00Z")]
    assert [summary.session_id for summary in store.recent(5)] == [first, second]
