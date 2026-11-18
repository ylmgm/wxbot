from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Sequence


@dataclass(frozen=True)
class NormalizedMessage:
    group_name: str
    sender: str
    attr: str
    msg_type: str
    content: str
    ui_id: str
    time_label: str
    fingerprint: str

    def display(self) -> str:
        who = self.sender or self.attr or self.msg_type or "未知"
        prefix = f"[{self.time_label}] " if self.time_label else ""
        return f"{prefix}{self.group_name} | {who}: {self.content}"


def normalize_messages(
    group_name: str,
    raw_messages: Sequence[Any],
    *,
    store_time_messages: bool = False,
) -> list[NormalizedMessage]:
    """把 wxauto 消息对象转成可保存的记录。

    时间分隔条用来标注随后消息的 time_label。界面只显示“昨天”“14:32”
    这种标签，没有绝对时间戳。
    """
    time_label = ""
    normalized: list[NormalizedMessage] = []
    for raw in raw_messages:
        if isinstance(raw, (list, tuple)):
            # wxauto 3.9 的 GetAllMessage 有时返回 [发送者, 内容, id]
            sender = _text(raw[0]) if len(raw) > 0 else ""
            content = _text(raw[1]) if len(raw) > 1 else ""
            ui_id = _text(raw[2]) if len(raw) > 2 else ""
            msg_type = "text"
            attr = "friend"
            msg_hash = ""
        else:
            msg_type = _text(_pick(raw, "type", "msg_type"))
            attr = _text(_pick(raw, "attr"))
            sender = _text(_pick(raw, "sender"))
            content = _text(_pick(raw, "content"))
            ui_id = _text(_pick(raw, "id", "ui_id"))
            msg_hash = _text(_pick(raw, "hash"))
        attr, msg_type, sender = _canonicalize(attr, msg_type, sender, content)
        if msg_type == "time":
            time_label = content or sender
            if not store_time_messages:
                continue
        normalized.append(
            NormalizedMessage(
                group_name=group_name,
                sender=sender,
                attr=attr,
                msg_type=msg_type,
                content=content,
                ui_id=ui_id,
                time_label=time_label,
                fingerprint=message_key(time_label, sender, attr, msg_type, content, msg_hash),
            )
        )
    return normalized


def message_key(
    time_label: str,
    sender: str,
    attr: str,
    msg_type: str,
    content: str,
    msg_hash: str = "",
) -> str:
    material = "\n".join((time_label, sender, attr, msg_type, content, msg_hash))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def align_new(previous_keys: Sequence[str], current: Sequence[NormalizedMessage]) -> list[NormalizedMessage]:
    """对照上一屏消息，只返回新出现在末尾的消息。

    微信窗口通常停在最新位置：旧消息从顶部滑出，新消息补在底部。
    因此用上一屏指纹的最长后缀，去匹配当前屏幕上最靠前的同一段。
    没有重叠时返回空列表，避免把整屏历史再写一遍。
    """
    if not previous_keys:
        return list(current)
    current_keys = [item.fingerprint for item in current]
    max_len = min(len(previous_keys), len(current_keys))
    for length in range(max_len, 0, -1):
        suffix = list(previous_keys[-length:])
        last_start = len(current_keys) - length
        for start in range(last_start + 1):
            if current_keys[start : start + length] == suffix:
                return list(current[start + length :])
    return []


def has_overlap(previous_keys: Sequence[str], current_keys: Sequence[str]) -> bool:
    if not previous_keys or not current_keys:
        return False
    max_len = min(len(previous_keys), len(current_keys))
    for length in range(max_len, 0, -1):
        suffix = list(previous_keys[-length:])
        last_start = len(current_keys) - length
        for start in range(last_start + 1):
            if current_keys[start : start + length] == suffix:
                return True
    return False


def _canonicalize(attr: str, msg_type: str, sender: str, content: str) -> tuple[str, str, str]:
    """wxauto 3.9 把 friend/self/time 放在 type 上，4.x 则分成 attr 和 type。"""
    if not attr and msg_type in {"friend", "self", "sys", "system", "time", "recall"}:
        attr = "system" if msg_type == "sys" else msg_type
        if msg_type in {"friend", "self", "sys", "system", "recall"}:
            msg_type = _content_type(content)
    if attr == "self" and sender == "Self":
        sender = "我"
    return attr, msg_type, sender


def _content_type(content: str) -> str:
    for prefix, msg_type in (
        ("[图片]", "image"),
        ("[文件]", "file"),
        ("[语音]", "voice"),
        ("[视频]", "video"),
    ):
        if content.startswith(prefix):
            return msg_type
    return "text"


def _pick(raw: Any, *names: str) -> Any:
    if isinstance(raw, dict):
        for name in names:
            if name in raw and raw[name] is not None:
                return raw[name]
        info = raw.get("info")
        if isinstance(info, dict):
            for name in names:
                if info.get(name) is not None:
                    return info[name]
        return ""
    for name in names:
        value = getattr(raw, name, None)
        if value is not None:
            return value
    info = getattr(raw, "info", None)
    if isinstance(info, dict):
        for name in names:
            if info.get(name) is not None:
                return info.get(name)
    return ""


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)
