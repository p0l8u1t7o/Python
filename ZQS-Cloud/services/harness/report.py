"""Render the acceptance checklist as something a person can act on.

The report answers one question - **"can I point this device at the real server
yet?"** - and it only answers yes when every required check passed. A partial
pass is reported as a partial pass, because a device author who is told "mostly
fine" will ship it.
"""

from __future__ import annotations

from services.harness import checks as conformance

VERDICT_READY = "ready"
VERDICT_NOT_READY = "not_ready"
VERDICT_INCOMPLETE = "incomplete"

_ICON = {
    conformance.PASS: "[通過]",
    conformance.FAIL: "[失敗]",
    conformance.WARN: "[注意]",
    conformance.PENDING: "[未測]",
}


def verdict(checks: dict[str, conformance.Check]) -> str:
    """``ready`` only when every required check actually ran and passed."""
    required = [check for check in checks.values() if check.required]
    if any(check.status == conformance.FAIL for check in required):
        return VERDICT_NOT_READY
    if any(check.status == conformance.PENDING for check in required):
        return VERDICT_INCOMPLETE
    return VERDICT_READY


def summarise(checks: dict[str, conformance.Check]) -> dict[str, int]:
    counts = {conformance.PASS: 0, conformance.FAIL: 0, conformance.WARN: 0, conformance.PENDING: 0}
    for check in checks.values():
        counts[check.status] += 1
    return counts


def render(
    checks: dict[str, conformance.Check],
    *,
    device_id: str,
    message_count: int = 0,
) -> str:
    """A plain-text checklist report. Safe to paste into a ticket."""
    lines: list[str] = []
    lines.append("=" * 74)
    lines.append(f"  設備連線驗收報告   device_id = {device_id}")
    lines.append("=" * 74)
    lines.append("")

    for check in checks.values():
        icon = _ICON[check.status]
        optional = "" if check.required else "（選用）"
        lines.append(f"{icon} {check.title}{optional}")
        if check.status == conformance.PASS:
            if check.actual:
                lines.append(f"        實際：{check.actual}")
            if check.detail:
                lines.append(f"        備註：{check.detail}")
        elif check.status == conformance.PENDING:
            lines.append(f"        應為：{check.expected}")
            lines.append("        尚未觀察到這個行為。")
        else:
            lines.append(f"        應為：{check.expected}")
            lines.append(f"        實際：{check.actual}")
            if check.detail:
                for wrapped in _wrap(check.detail, 62):
                    lines.append(f"        → {wrapped}")
        if check.key in conformance.STRICTER_THAN_PRODUCTION:
            lines.append("        （本工具在這一項比正式環境嚴格，見文件說明）")
        lines.append("")

    counts = summarise(checks)
    lines.append("-" * 74)
    lines.append(
        f"通過 {counts[conformance.PASS]}　"
        f"失敗 {counts[conformance.FAIL]}　"
        f"注意 {counts[conformance.WARN]}　"
        f"未測 {counts[conformance.PENDING]}　"
        f"（收到 {message_count} 則訊息）"
    )
    lines.append("")

    result = verdict(checks)
    if result == VERDICT_READY:
        lines.append("結論：可以接正式環境了。")
        lines.append("")
        lines.append("  這代表設備滿足平台的所有連線與 payload 規則——驗證用的是")
        lines.append("  與正式環境完全相同的程式（authenticate_device、ACL 判斷、")
        lines.append("  ingestor 的 decode/validate）。")
        lines.append("")
        lines.append("  仍建議先對真正的 EMQX 做一次煙霧測試，本工具無法涵蓋：")
        lines.append("    - retained 訊息在後續訂閱時的重播")
        lines.append("    - clean_session=false 的 session 跨重連保存")
        lines.append("    - TLS（正式環境用 8883）")
    elif result == VERDICT_NOT_READY:
        failed = [c.title for c in checks.values() if c.status == conformance.FAIL]
        lines.append("結論：還不能接正式環境。")
        lines.append("")
        lines.append("  以下項目必須先修好，否則接上正式環境一定會失敗：")
        for title in failed:
            lines.append(f"    - {title}")
    else:
        pending = [
            c.title
            for c in checks.values()
            if c.required and c.status == conformance.PENDING
        ]
        lines.append("結論：測試尚未完成，無法判定。")
        lines.append("")
        lines.append("  下列必要項目還沒被觀察到，請讓設備實際做一次：")
        for title in pending:
            lines.append(f"    - {title}")
    lines.append("=" * 74)
    return "\n".join(lines)


def _wrap(text: str, width: int) -> list[str]:
    """Wrap on width, counting CJK characters as two columns."""
    lines: list[str] = []
    current = ""
    used = 0
    for char in text:
        cost = 2 if ord(char) > 0x2E80 else 1
        if used + cost > width:
            lines.append(current)
            current, used = "", 0
        current += char
        used += cost
    if current:
        lines.append(current)
    return lines
