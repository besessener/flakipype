from flakipype.store.database import ScanCache
from flakipype.store.sessions import SessionKind, SessionSummary


def test_sessions_are_created_updated_listed_and_loaded(cache: ScanCache) -> None:
    store = cache.sessions
    first = store.create("Why does E2E fail?", now="2026-10-09T10:00:00Z", data='{"v": 1}')
    second = store.create("Recurring lint", now="2026-10-09T11:00:00Z", data='{"v": 2}')

    store.update(first, now="2026-10-09T12:00:00Z", data='{"v": 3}', tokens=40)

    assert store.load(first) == '{"v": 3}'
    assert store.load(999) is None
    assert store.recent(1) == [SessionSummary(first, "Why does E2E fail?", "2026-10-09T12:00:00Z")]
    assert [summary.session_id for summary in store.recent(5)] == [first, second]
    assert (store.kind(first), store.kind(999)) == (SessionKind.CHAT, None)


def test_run_sessions_give_the_last_run_and_the_tokens_of_a_day(cache: ScanCache) -> None:
    store = cache.sessions
    run = SessionKind.RUN
    early = store.create("run 1", now="2026-10-08T06:00:00+00:00", data="{}", kind=run)
    chat = store.create("chat", now="2026-10-09T05:00:00+00:00", data="{}")
    late = store.create("run 2", now="2026-10-09T06:00:00+00:00", data="{}", kind=run)
    current = store.create("run 3", now="2026-10-09T07:00:00+00:00", data="{}", kind=run)
    store.update(early, now="2026-10-08T07:00:00+00:00", data='{"v": 1}', tokens=500)
    store.update(chat, now="2026-10-09T08:00:00+00:00", data="{}", tokens=9_000)
    # Only the tokens the run stored count, not a key of its document.
    store.update(late, now="2026-10-09T08:00:00+00:00", data='{"tokens": 1}', tokens=700)

    assert store.latest_run(before=current) == '{"tokens": 1}'
    assert store.latest_run(before=late) == '{"v": 1}'
    assert store.latest_run(before=early) is None
    assert store.run_tokens_since("2026-10-08T07:00:00+00:00") == 700
    assert store.run_tokens_since("2026-10-10T00:00:00+00:00") == 0
    assert store.recent(1)[0].kind is SessionKind.RUN
