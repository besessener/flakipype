"""The session's audit entries as the chat shows them."""

from flakipype.store.audit import AuditEntry


def audit_text(entries: list[AuditEntry]) -> str:
    if not entries:
        return "No actions requested in this session."
    lines = [
        f"- {entry.time[11:16]} `{entry.action}` asked by {entry.origin}, {entry.answer}: "
        f"{entry.outcome}"
        for entry in entries
    ]
    return "Actions in this session:\n" + "\n".join(lines)
