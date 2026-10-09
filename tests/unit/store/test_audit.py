from flakipype.store.audit import AuditEntry
from flakipype.store.database import ScanCache


def test_entries_are_kept_per_session_in_order(cache: ScanCache) -> None:
    log = cache.audit
    first = AuditEntry(
        "2026-10-09T10:00:00+00:00", "s1", "rerun_failed", "model", "Rerun?", "confirmed",
        "started", 7,
    )  # fmt: skip
    declined = AuditEntry(
        "2026-10-09T10:01:00+00:00", "s1", "dispatch", "command", "Dispatch?", "declined", ""
    )
    other = AuditEntry("2026-10-09T10:02:00+00:00", "s2", "cancel", "model", "C?", "confirmed", "")

    for entry in (first, declined, other):
        log.record(entry)

    assert log.entries("s1") == [first, declined]
    assert log.entries("s3") == []
