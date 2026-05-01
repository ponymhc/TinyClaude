from datetime import datetime
from typing import Optional


MS_PER_DAY = 86_400_000


def memory_age_days(mtime_ms: int) -> int:
    """
    计算自 mtime 以来的天数。向下取整 — 今天为 0，昨天为 1，更早为 2+。
    负输入（未来 mtime，时钟偏移）钳制为 0。
    """
    now_ms = datetime.now().timestamp() * 1000
    return max(0, int((now_ms - mtime_ms) / MS_PER_DAY))


def memory_age(mtime_ms: int) -> str:
    """
    人类可读的时间年龄字符串。模型不擅长日期运算 —
    原始 ISO 时间戳不会像 "47 days ago" 那样触发陈旧性推理。
    """
    d = memory_age_days(mtime_ms)
    if d == 0:
        return "today"
    if d == 1:
        return "yesterday"
    return f"{d} days ago"


def memory_freshness_text(mtime_ms: int) -> str:
    """
    记忆 >1 天陈旧时的纯文本陈旧性警告。
    今天/昨天的记忆返回 '' — 那里的警告是噪音。

    使用此方法当消费者已经提供自己的包装时。
    """
    d = memory_age_days(mtime_ms)
    if d <= 1:
        return ""
    return (
        f"This memory is {d} days old. "
        "Memories are point-in-time observations, not live state — "
        "claims about code behavior or file:line citations may be outdated. "
        "Verify against current code before asserting as fact."
    )


def memory_freshness_note(mtime_ms: int) -> str:
    """
    每个记忆的陈旧性注释，带 <system-reminder> 标签包装。
    对于 ≤1 天的记忆返回 ''。
    使用此方法当调用者不添加自己的 system-reminder 包装时（例如 FileReadTool 输出）。
    """
    text = memory_freshness_text(mtime_ms)
    if not text:
        return ""
    return f"<system-reminder>{text}</system-reminder>\n"
