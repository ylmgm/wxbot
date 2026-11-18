from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from wxgroup.client import ReaderError, Wxauto4Reader
from wxgroup.names import strip_member_count
from wxgroup.config import ConfigError, GroupSpec, Settings, load_settings
from wxgroup.demo import DemoReader
from wxgroup.service import GroupReaderService
from wxgroup.store import MessageStore, write_csv, write_jsonl


def main(argv: list[str] | None = None) -> int:
    _configure_stdio()
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (ConfigError, ReaderError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\n已停止。")
        return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wxgroup",
        description="读取本机已登录微信中指定群的消息，并保存到本地数据库。",
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="配置文件路径，默认 ./config.yaml",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sessions = sub.add_parser("sessions", help="列出微信左侧当前可见的会话")
    sessions.set_defaults(func=cmd_sessions)

    info = sub.add_parser("info", help="打开配置中的群，查看类型、人数和可见消息数")
    info.add_argument("--group", action="append", dest="groups", help="只查看这个群，可重复")
    info.set_defaults(func=cmd_info)

    snapshot = sub.add_parser("snapshot", help="读取当前屏幕上的群消息并写入数据库")
    snapshot.add_argument("--group", action="append", dest="groups", help="只读取这个群，可重复")
    snapshot.add_argument("--reset", action="store_true", help="丢弃该群上次的屏幕快照后重新建立基线")
    snapshot.set_defaults(func=cmd_snapshot)

    watch = sub.add_parser("watch", help="按间隔轮询配置中的群，把新消息写入数据库")
    watch.set_defaults(func=cmd_watch)

    query = sub.add_parser("query", help="查看已经保存的消息")
    query.add_argument("--group", help="群名")
    query.add_argument("--sender", help="发送者")
    query.add_argument("--keyword", help="内容包含的文字")
    query.add_argument("--limit", type=int, default=50, help="最多显示多少条，默认 50")
    query.add_argument("--all", action="store_true", help="连时间分隔条一起显示")
    query.set_defaults(func=cmd_query)

    export = sub.add_parser("export", help="把已保存的消息导出为 jsonl 或 csv")
    export.add_argument("--group", help="只导出这个群")
    export.add_argument("--format", choices=("jsonl", "csv"), default="jsonl")
    export.add_argument("--out", help="输出文件，默认 data/messages.jsonl 或 data/messages.csv")
    export.add_argument("--all", action="store_true", help="连时间分隔条一起导出")
    export.set_defaults(func=cmd_export)

    demo = sub.add_parser("demo", help="用内置样例走一遍读取、去重和查询，不连接微信")
    demo.set_defaults(func=cmd_demo)
    return parser


def cmd_sessions(args: argparse.Namespace) -> int:
    settings = _settings(args)

    def action(service: GroupReaderService, _store: MessageStore) -> int:
        configured = {strip_member_count(item.name) for item in settings.groups}
        sessions = service.list_sessions()
        if not sessions:
            print("没有读到会话。请确认微信主窗口正停在聊天页。")
            return 0
        print(f"可见会话 {len(sessions)} 个。标 * 的群写在配置里。")
        for session in sessions:
            mark = "*" if session.name in configured else " "
            if session.is_new and session.new_count:
                badge = f"新{session.new_count}"
            elif session.is_new:
                badge = "新"
            else:
                badge = ""
            mute = "免打扰" if session.is_mute else ""
            people = f"{session.listed_count}人" if session.listed_count else ""
            preview = session.content.replace("\n", " ")
            print(f"{mark} {badge:<4} {session.time:<16} {session.name}  {people} {mute} {preview}")
        return 0

    return _run_with_wechat(settings, action)


def cmd_info(args: argparse.Namespace) -> int:
    settings = _settings(args)

    def action(service: GroupReaderService, _store: MessageStore) -> int:
        specs = _selected(settings, args.groups)
        for index, spec in enumerate(specs):
            if index:
                _pause(settings)
            described = service.describe(spec)
            members = "未知" if described.member_count is None else str(described.member_count)
            print(f"{described.chat_name}")
            print(f"  类型: {described.chat_type or '未知'}")
            print(f"  成员: {members}")
            print(f"  当前屏幕可见消息: {described.visible_count}")
        return 0

    return _run_with_wechat(settings, action)


def cmd_snapshot(args: argparse.Namespace) -> int:
    settings = _settings(args)

    def action(service: GroupReaderService, _store: MessageStore) -> int:
        results = service.snapshot(args.groups, reset=args.reset)
        for result in results:
            state = "基线" if result.baseline else "新增"
            if result.skipped_overlap:
                state = "跳过"
            members = "" if result.member_count is None else f"，成员 {result.member_count}"
            print(
                f"{result.group_name}: {state} {result.saved_count} 条，"
                f"屏幕上 {result.visible_count} 条{members}"
            )
        return 0

    return _run_with_wechat(settings, action)


def cmd_watch(args: argparse.Namespace) -> int:
    settings = _settings(args)

    def action(service: GroupReaderService, _store: MessageStore) -> int:
        service.watch()
        return 0

    return _run_with_wechat(settings, action)


def cmd_query(args: argparse.Namespace) -> int:
    settings = _settings(args)
    if args.limit <= 0:
        raise ConfigError("--limit 必须大于 0。")
    store = MessageStore(settings.database)
    try:
        messages = store.query(
            group_name=args.group,
            sender=args.sender,
            keyword=args.keyword,
            include_time=args.all,
            limit=args.limit,
        )
    finally:
        store.close()
    if not messages:
        print("没有匹配的消息。")
        return 0
    for message in messages:
        clock = message.time_label or message.captured_at
        who = message.sender or message.attr or message.msg_type
        text = message.content.replace("\n", " ")
        print(f"{clock}  {message.group_name}  {who}: {text}")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    settings = _settings(args)
    default_name = "messages.csv" if args.format == "csv" else "messages.jsonl"
    out = Path(args.out) if args.out else settings.database.parent / default_name
    store = MessageStore(settings.database)
    try:
        messages = store.export_rows(group_name=args.group, include_time=args.all)
    finally:
        store.close()
    if args.format == "csv":
        write_csv(out, messages)
    else:
        write_jsonl(out, messages)
    print(f"已导出 {len(messages)} 条到 {out}")
    return 0


def cmd_demo(_args: argparse.Namespace) -> int:
    database = Path("data") / "demo" / "messages.db"
    if database.exists():
        database.unlink()
    settings = Settings(
        groups=(GroupSpec(name="示例项目群", exact=True),),
        poll_interval_seconds=2,
        force_scan_rounds=12,
        only_new_sessions=True,
        switch_pause_seconds=0,
        store_time_messages=False,
        database=database,
        log_dir=database.parent / "logs",
    )
    _setup_logging(settings.log_dir)
    store = MessageStore(settings.database)
    try:
        service = GroupReaderService(settings, DemoReader(), store)
        first = service.capture(settings.groups[0])
        second = service.capture(settings.groups[0])
        print(f"第一次读取: 基线 {first.saved_count} 条")
        print(f"第二次读取: 新增 {second.saved_count} 条")
        print("--- 已保存 ---")
        for message in store.query(limit=20):
            who = message.sender or message.msg_type
            print(f"{message.time_label}  {message.group_name}  {who}: {message.content}")
    finally:
        store.close()
    print(f"样例数据库: {database}")
    return 0


def _run_with_wechat(settings: Settings, action) -> int:
    _setup_logging(settings.log_dir)
    store = MessageStore(settings.database)
    try:
        reader = Wxauto4Reader()
        logging.getLogger("wxgroup").info("已连接微信，使用 %s", reader.backend)
        service = GroupReaderService(settings, reader, store)
        return action(service, store)
    finally:
        store.close()


def _settings(args: argparse.Namespace) -> Settings:
    return load_settings(Path(args.config))


def _selected(settings: Settings, names: list[str] | None):
    if names:
        return [settings.find_group(name) for name in names]
    return list(settings.require_groups())


def _pause(settings: Settings) -> None:
    import time

    time.sleep(settings.switch_pause_seconds)


def _setup_logging(log_dir: Path) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    if root.handlers:
        return
    root.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    file_handler = logging.FileHandler(log_dir / "wxgroup.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    root.addHandler(file_handler)
    root.addHandler(stream_handler)


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8")
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
