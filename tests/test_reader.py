from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from wxgroup.client import ChatView, SessionView
from wxgroup.config import ConfigError, GroupSpec, Settings, load_settings
from wxgroup.messages import align_new, normalize_messages
from wxgroup.names import strip_member_count
from wxgroup.service import GroupReaderService
from wxgroup.store import MessageStore


def _settings(database: Path) -> Settings:
    return Settings(
        groups=(GroupSpec(name="项目群", exact=True),),
        poll_interval_seconds=2,
        force_scan_rounds=3,
        only_new_sessions=True,
        switch_pause_seconds=0,
        store_time_messages=False,
        database=database,
        log_dir=database.parent,
    )


class _FakeReader:
    def __init__(self, screens: list[list[dict]]):
        self.screens = screens
        self.reads = 0
        self.sessions = [
            SessionView(
                name="项目群",
                time="14:32",
                content="",
                is_new=True,
                new_count=1,
                is_mute=False,
            )
        ]

    def list_sessions(self):
        return list(self.sessions)

    def read_chat(self, name: str, *, exact: bool):
        del name, exact
        index = min(self.reads, len(self.screens) - 1)
        self.reads += 1
        return (
            ChatView(chat_name="项目群", chat_type="group", member_count=8, remark=""),
            self.screens[index],
        )


def _text(sender: str, content: str, *, attr: str = "friend", msg_id: str = "") -> dict:
    return {"type": "text", "attr": attr, "sender": sender, "content": content, "id": msg_id}


class NameTests(unittest.TestCase):
    def test_member_count_suffix_is_not_part_of_the_name(self):
        self.assertEqual(strip_member_count("项目群（17）"), "项目群")
        self.assertEqual(strip_member_count("项目群(17)"), "项目群")
        self.assertEqual(strip_member_count("项目群 （17）"), "项目群")
        self.assertEqual(strip_member_count("项目群"), "项目群")
        self.assertEqual(strip_member_count("第（17）组"), "第（17）组")

    def test_title_with_member_count_matches_configured_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "messages.db"

            class CountedTitleReader(_FakeReader):
                def __init__(self):
                    super().__init__([[_text("张三", "开会")]])
                    self.opened = ""

                def read_chat(self, name: str, *, exact: bool):
                    del exact
                    self.opened = name
                    return (
                        ChatView(
                            chat_name="项目群（17）",
                            chat_type="group",
                            member_count=None,
                            remark="",
                        ),
                        self.screens[0],
                    )

            reader = CountedTitleReader()
            store = MessageStore(database)
            try:
                service = GroupReaderService(_settings(database), reader, store)
                result = service.capture(GroupSpec("项目群（17）"))
                saved = store.query(limit=5)
            finally:
                store.close()
        self.assertEqual(reader.opened, "项目群")
        self.assertEqual(result.group_name, "项目群")
        self.assertEqual(saved[0].group_name, "项目群")


class NormalizeTests(unittest.TestCase):
    def test_time_label_is_applied_and_time_row_can_be_dropped(self):
        messages = normalize_messages(
            "项目群",
            [
                {"type": "time", "attr": "system", "sender": "", "content": "14:30", "id": "t"},
                _text("张三", " hello "),
            ],
        )
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].time_label, "14:30")
        self.assertEqual(messages[0].content, " hello ")
        self.assertEqual(messages[0].sender, "张三")

    def test_legacy_wxauto_uses_type_as_sender_kind(self):
        class LegacyMessage:
            type = "friend"
            sender = "张三"
            content = "[图片]"
            id = "runtime-1"

        messages = normalize_messages("项目群", [LegacyMessage(), ["Self", "好", "runtime-2"]])
        self.assertEqual(messages[0].attr, "friend")
        self.assertEqual(messages[0].msg_type, "image")
        self.assertEqual(messages[0].sender, "张三")
        self.assertEqual(messages[1].sender, "Self")
        self.assertEqual(messages[1].msg_type, "text")

    def test_same_screen_keeps_stable_fingerprints(self):
        raw = [_text("张三", "收到"), _text("张三", "收到")]
        first = normalize_messages("项目群", raw)
        second = normalize_messages("项目群", raw)
        self.assertEqual([item.fingerprint for item in first], [item.fingerprint for item in second])
        self.assertEqual(first[0].fingerprint, first[1].fingerprint)


class AlignTests(unittest.TestCase):
    def _messages(self, contents: list[str]):
        return normalize_messages("项目群", [_text("张三", content) for content in contents])

    def test_first_screen_is_all_new(self):
        current = self._messages(["a", "b"])
        self.assertEqual(align_new([], current), current)

    def test_appended_message_is_new(self):
        previous = self._messages(["a", "b", "c"])
        current = self._messages(["a", "b", "c", "d"])
        fresh = align_new([item.fingerprint for item in previous], current)
        self.assertEqual([item.content for item in fresh], ["d"])

    def test_scrolled_window_keeps_only_the_tail(self):
        previous = self._messages(["a", "b", "c", "d"])
        current = self._messages(["c", "d", "e"])
        fresh = align_new([item.fingerprint for item in previous], current)
        self.assertEqual([item.content for item in fresh], ["e"])

    def test_no_overlap_inserts_nothing(self):
        previous = self._messages(["a", "b"])
        current = self._messages(["c", "d"])
        fresh = align_new([item.fingerprint for item in previous], current)
        self.assertEqual(fresh, [])


class StoreAndServiceTests(unittest.TestCase):
    def test_second_capture_saves_only_new_messages(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "messages.db"
            reader = _FakeReader(
                [
                    [
                        {"type": "time", "attr": "system", "content": "14:30"},
                        _text("张三", "开会"),
                        _text("李四", "收到"),
                    ],
                    [
                        {"type": "time", "attr": "system", "content": "14:30"},
                        _text("张三", "开会"),
                        _text("李四", "收到"),
                        _text("王五", "晚点到"),
                    ],
                    [
                        _text("赵六", "完全换了一屏"),
                        _text("钱七", "对不上上一屏"),
                    ],
                ]
            )
            store = MessageStore(database)
            try:
                service = GroupReaderService(_settings(database), reader, store)
                first = service.capture(GroupSpec("项目群"))
                second = service.capture(GroupSpec("项目群"))
                third = service.capture(GroupSpec("项目群"))
                saved = store.query(limit=10)
            finally:
                store.close()

        self.assertTrue(first.baseline)
        self.assertEqual(first.saved_count, 2)
        self.assertEqual(second.saved_count, 1)
        self.assertEqual(second.baseline, False)
        self.assertTrue(third.skipped_overlap)
        self.assertEqual(third.saved_count, 0)
        self.assertEqual([item.content for item in saved], ["开会", "收到", "晚点到"])

    def test_watch_skips_quiet_session_until_force_round(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "messages.db"
            reader = _FakeReader([[_text("张三", "只在强制轮读取")]])
            reader.sessions[0] = SessionView(
                name="项目群",
                time="",
                content="",
                is_new=False,
                new_count=0,
                is_mute=True,
            )
            store = MessageStore(database)
            try:
                service = GroupReaderService(_settings(database), reader, store)
                service._watch_round(service.settings.groups, round_no=2)
                quiet_reads = reader.reads
                service._watch_round(service.settings.groups, round_no=3)
                force_reads = reader.reads
            finally:
                store.close()
        self.assertEqual(quiet_reads, 0)
        self.assertEqual(force_reads, 1)

    def test_rejects_non_group(self):
        class FriendReader(_FakeReader):
            def read_chat(self, name: str, *, exact: bool):
                del name, exact
                return (
                    ChatView(chat_name="项目群", chat_type="friend", member_count=None, remark=""),
                    [],
                )

        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "messages.db"
            store = MessageStore(database)
            try:
                service = GroupReaderService(_settings(database), FriendReader([[]]), store)
                with self.assertRaises(Exception) as raised:
                    service.capture(GroupSpec("项目群"))
            finally:
                store.close()
        self.assertIn("不是群聊", str(raised.exception))


class ConfigTests(unittest.TestCase):
    def test_load_groups_and_reject_fast_polling(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            path.write_text(
                "groups:\n  - name: 项目群\npoll_interval_seconds: 1\n",
                encoding="utf-8",
            )
            with self.assertRaises(ConfigError):
                load_settings(path)

            path.write_text(
                "groups:\n  - name: 项目群\n    exact: true\ndatabase: data/messages.db\n",
                encoding="utf-8",
            )
            settings = load_settings(path)
        self.assertEqual(settings.groups[0].name, "项目群")
        self.assertEqual(settings.database, path.parent / "data" / "messages.db")

    def test_load_gbk_config_from_notepad(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            path.write_bytes("groups:\n  - name: 项目群\n".encode("gbk"))
            settings = load_settings(path)
        self.assertEqual(settings.groups[0].name, "项目群")


if __name__ == "__main__":
    unittest.main()
