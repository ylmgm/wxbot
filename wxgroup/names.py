from __future__ import annotations

import re


# 微信会把群人数接在标题后面，例如「项目群（17）」。这不是群名的一部分。
_MEMBER_COUNT_SUFFIX = re.compile(r"\s*[（(]\s*(\d+)\s*[）)]\s*$")


def strip_member_count(name: str) -> str:
    """去掉标题末尾的人数，供搜索和核对使用。"""
    cleaned = _MEMBER_COUNT_SUFFIX.sub("", name).strip()
    return cleaned or name.strip()


def member_count_suffix(name: str) -> int | None:
    matched = _MEMBER_COUNT_SUFFIX.search(name)
    if not matched:
        return None
    return int(matched.group(1))
