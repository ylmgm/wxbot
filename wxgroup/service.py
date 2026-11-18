from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from wxgroup.client import ChatView, ReaderError, SessionView, WeChatReader
from wxgroup.config import GroupSpec, Settings
from wxgroup.messages import align_new, has_overlap, normalize_messages
from wxgroup.names import strip_member_count
from wxgroup.store import MessageStore


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CaptureResult:
    group_name: str
    chat_type: str
    member_count: int | None
    visible_count: int
    saved_count: int
    baseline: bool
    skipped_overlap: bool


@dataclass(frozen=True)
class GroupDescription:
    requested_name: str
    chat_name: str
    chat_type: str
    member_count: int | None
    visible_count: int


class GroupReaderService:
    def __init__(self, settings: Settings, reader: WeChatReader, store: MessageStore):
        self.settings = settings
        self.reader = reader
        self.store = store

    def list_sessions(self) -> list[SessionView]:
        return self.reader.list_sessions()

    def describe(self, spec: GroupSpec) -> GroupDescription:
        chat, raw_messages = self.reader.read_chat(self._search_name(spec), exact=spec.exact)
        self._ensure_expected_chat(spec, chat)
        group_name = self._canonical_name(spec, chat)
        visible = normalize_messages(
            group_name,
            raw_messages,
            store_time_messages=True,
        )
        content_count = sum(1 for item in visible if item.msg_type != "time")
        return GroupDescription(
            requested_name=spec.name,
            chat_name=group_name,
            chat_type=chat.chat_type,
            member_count=chat.member_count,
            visible_count=content_count,
        )

    def capture(self, spec: GroupSpec, *, reset: bool = False) -> CaptureResult:
        chat, raw_messages = self.reader.read_chat(self._search_name(spec), exact=spec.exact)
        self._ensure_expected_chat(spec, chat)
        canonical = self._canonical_name(spec, chat)
        if reset:
            self.store.clear_snapshot(canonical)
            if canonical != spec.name:
                self.store.clear_snapshot(spec.name)
        visible = normalize_messages(
            canonical,
            raw_messages,
            store_time_messages=self.settings.store_time_messages,
        )
        previous = self.store.snapshot_keys(canonical)
        baseline = not previous
        if baseline:
            fresh = visible
            skipped = False
        else:
            fresh = align_new(previous, visible)
            skipped = not fresh and not has_overlap(
                previous, [item.fingerprint for item in visible]
            )
            if skipped:
                logger.warning(
                    "%s 当前屏幕和上次快照没有重叠，已跳过写入。若确认是新的一屏，执行 snapshot --group %s --reset",
                    canonical,
                    spec.name,
                )
                return CaptureResult(
                    group_name=canonical,
                    chat_type=chat.chat_type,
                    member_count=chat.member_count,
                    visible_count=len(visible),
                    saved_count=0,
                    baseline=False,
                    skipped_overlap=True,
                )
        saved = self.store.commit_capture(
            canonical,
            visible,
            fresh,
            is_baseline=baseline,
            chat_type=chat.chat_type,
            member_count=chat.member_count,
        )
        for message in fresh:
            if message.msg_type == "time":
                continue
            level = logging.INFO if not baseline else logging.DEBUG
            logger.log(level, message.display())
        if baseline:
            logger.info("%s 已记录当前可见消息 %s 条，作为基线", canonical, saved)
        elif saved:
            logger.info("%s 新增 %s 条", canonical, saved)
        return CaptureResult(
            group_name=canonical,
            chat_type=chat.chat_type,
            member_count=chat.member_count,
            visible_count=len(visible),
            saved_count=saved,
            baseline=baseline,
            skipped_overlap=False,
        )

    def snapshot(self, names: list[str] | None = None, *, reset: bool = False) -> list[CaptureResult]:
        specs = self._select_groups(names)
        results: list[CaptureResult] = []
        for index, spec in enumerate(specs):
            if index:
                time.sleep(self.settings.switch_pause_seconds)
            results.append(self.capture(spec, reset=reset))
        return results

    def watch(self) -> None:
        specs = self.settings.require_groups()
        logger.info(
            "开始读取 %s 个群，间隔 %s 秒。按 Ctrl+C 结束。",
            len(specs),
            self.settings.poll_interval_seconds,
        )
        round_no = 0
        while True:
            round_no += 1
            started = time.monotonic()
            self._watch_round(specs, round_no)
            elapsed = time.monotonic() - started
            remaining = self.settings.poll_interval_seconds - elapsed
            if remaining > 0:
                time.sleep(remaining)

    def _watch_round(self, specs: tuple[GroupSpec, ...], round_no: int) -> None:
        force = round_no == 1 or round_no % self.settings.force_scan_rounds == 0
        try:
            sessions = {strip_member_count(item.name): item for item in self.reader.list_sessions()}
        except ReaderError:
            logger.exception("读取会话列表失败，本轮跳过")
            return
        for spec in specs:
            visible = sessions.get(self._search_name(spec))
            if not self._should_open(visible, force=force):
                continue
            try:
                self.capture(spec)
            except ReaderError:
                logger.exception("读取 %s 失败", spec.name)
            time.sleep(self.settings.switch_pause_seconds)

    def _should_open(self, session: SessionView | None, *, force: bool) -> bool:
        if force:
            return True
        if session is None:
            return False
        if not self.settings.only_new_sessions:
            return True
        return session.is_new

    def _select_groups(self, names: list[str] | None) -> list[GroupSpec]:
        if not names:
            return list(self.settings.require_groups())
        return [self.settings.find_group(name) for name in names]

    def _search_name(self, spec: GroupSpec) -> str:
        return strip_member_count(spec.name)

    def _canonical_name(self, spec: GroupSpec, chat: ChatView) -> str:
        return strip_member_count(chat.chat_name or spec.name)

    def _ensure_expected_chat(self, spec: GroupSpec, chat: ChatView) -> None:
        wanted = self._search_name(spec)
        candidates = [strip_member_count(name) for name in (chat.chat_name, chat.remark) if name]
        if candidates:
            matched = wanted in candidates if spec.exact else any(wanted in name for name in candidates)
            if not matched:
                shown = chat.chat_name or chat.remark
                raise ReaderError(f"准备读取 {wanted}，实际打开的是 {shown}。已停止写入。")
        if chat.chat_type and chat.chat_type != "group":
            raise ReaderError(f"{wanted} 不是群聊，当前类型是 {chat.chat_type}。")
