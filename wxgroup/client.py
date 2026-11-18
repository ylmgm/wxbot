from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from wxgroup.names import member_count_suffix, strip_member_count


class ReaderError(RuntimeError):
    """读取微信窗口失败。"""


@dataclass(frozen=True)
class SessionView:
    name: str
    time: str
    content: str
    is_new: bool
    new_count: int
    is_mute: bool
    listed_count: int | None = None


@dataclass(frozen=True)
class ChatView:
    chat_name: str
    chat_type: str
    member_count: int | None
    remark: str


class WeChatReader(Protocol):
    def list_sessions(self) -> list[SessionView]:
        """返回微信左侧当前可见的会话。"""

    def read_chat(self, name: str, *, exact: bool) -> tuple[ChatView, list[Any]]:
        """打开指定会话，返回窗口信息和当前已加载的消息。"""


class Wxauto4Reader:
    """通过免费版 wxauto4 操作本机已经登录的微信。

    官方文档里带 ✨ 的监听、翻历史接口属于 Plus 版。这里只用免费接口：
    GetSession、ChatWith、ChatInfo、GetAllMessage。
    """

    def __init__(self) -> None:
        wechat_cls, backend = _load_wechat_class()
        self.backend = backend
        try:
            self._wx = _construct_wechat(wechat_cls)
        except ReaderError:
            raise
        except Exception as exc:
            raise ReaderError(_connect_error(exc)) from exc

    def list_sessions(self) -> list[SessionView]:
        try:
            if hasattr(self._wx, "GetSession"):
                sessions = self._wx.GetSession() or []
            elif hasattr(self._wx, "GetSessionList"):
                sessions = self._wx.GetSessionList() or []
            else:
                raise ReaderError("当前 wxauto 没有 GetSession 或 GetSessionList。")
        except ReaderError:
            raise
        except Exception as exc:
            raise ReaderError("读取会话列表失败。") from exc
        views: list[SessionView] = []
        for item in sessions:
            if isinstance(item, str):
                name = item
                time = ""
                content = ""
                is_new = False
                new_count = 0
                is_mute = False
            else:
                name = _text(_pick(item, "name"))
                time = _text(_pick(item, "time"))
                content = _text(_pick(item, "content"))
                is_new = bool(_pick(item, "isnew", "is_new", default=False))
                new_count = _int(_pick(item, "new_count", "newcount", default=0))
                is_mute = bool(_pick(item, "ismute", "is_mute", default=False))
            if not name:
                continue
            views.append(
                SessionView(
                    name=strip_member_count(name),
                    time=time,
                    content=content,
                    is_new=is_new,
                    new_count=new_count,
                    is_mute=is_mute,
                    listed_count=member_count_suffix(name),
                )
            )
        return views

    def read_chat(self, name: str, *, exact: bool) -> tuple[ChatView, list[Any]]:
        search_name = strip_member_count(name)
        opened = _open_chat(self._wx, search_name, exact)
        if opened is False:
            raise ReaderError(f"没有找到会话 {search_name}。请填写左侧会话列表里的群名，不要带末尾的人数。")

        if hasattr(self._wx, "ChatInfo"):
            info = _as_dict(_call(self._wx, "ChatInfo"))
            raw_name = _text(info.get("chat_name"))
            raw_remark = _text(info.get("remark"))
            member_count = info.get("group_member_count")
            if member_count in (None, ""):
                member_count = member_count_suffix(raw_name)
            chat = ChatView(
                chat_name=strip_member_count(raw_name),
                chat_type=_text(info.get("chat_type")),
                member_count=_int(member_count) if member_count not in (None, "") else None,
                remark=strip_member_count(raw_remark),
            )
        else:
            current = ""
            if hasattr(self._wx, "CurrentChat"):
                current = _text(self._wx.CurrentChat())
            if not current and isinstance(opened, str):
                current = opened
            title_count = member_count_suffix(current)
            chat = ChatView(
                chat_name=strip_member_count(current or name),
                chat_type="",
                member_count=title_count,
                remark="",
            )
        messages = _call(self._wx, "GetAllMessage") or []
        if not isinstance(messages, list):
            messages = list(messages)
        return chat, messages


def _open_chat(wx: Any, name: str, exact: bool) -> Any:
    attempts = (
        lambda: wx.ChatWith(name, exact=exact),
        lambda: wx.ChatWith(who=name, exact=exact),
        lambda: wx.ChatWith(name),
        lambda: wx.ChatWith(who=name),
    )
    type_error: TypeError | None = None
    for attempt in attempts:
        try:
            return attempt()
        except TypeError as exc:
            type_error = exc
            continue
        except ReaderError:
            raise
        except Exception as exc:
            raise ReaderError(f"无法打开会话 {name}。") from exc
    if type_error is not None:
        raise ReaderError(f"当前 wxauto 的 ChatWith 参数和程序不兼容: {type_error}") from type_error
    raise ReaderError(f"无法打开会话 {name}。")


def _construct_wechat(wechat_cls: Any) -> Any:
    attempts = (
        lambda: wechat_cls(resize=False, debug=False, ads=False),
        lambda: wechat_cls(resize=False, debug=False),
        lambda: wechat_cls(debug=False),
        lambda: wechat_cls(),
    )
    type_error: TypeError | None = None
    for attempt in attempts:
        try:
            return attempt()
        except TypeError as exc:
            type_error = exc
    if type_error is not None:
        raise ReaderError(f"无法初始化微信对象: {type_error}") from type_error
    raise ReaderError("无法初始化微信对象。")


def _load_wechat_class() -> tuple[Any, str]:
    family = _detect_wechat_family()
    if family == "3.9":
        return _import_legacy_wxauto()
    if family == "4":
        return _import_wxauto4()
    try:
        return _import_wxauto4()
    except ReaderError:
        return _import_legacy_wxauto()


def _import_wxauto4() -> tuple[Any, str]:
    try:
        from wxauto4 import WeChat

        return WeChat, "wxauto4"
    except ImportError as exc:
        raise ReaderError(
            "没有安装 wxauto4。微信 4.1 需要它：python -m pip install wxauto4"
        ) from exc


def _import_legacy_wxauto() -> tuple[Any, str]:
    try:
        from wxauto import WeChat

        return WeChat, "wxauto"
    except ImportError as exc:
        raise ReaderError(
            "没有安装微信 3.9 对应的 wxauto。PyPI 上的旧包已经下架，请在项目目录执行:\n"
            'python -m pip install -r requirements.txt'
        ) from exc


def _detect_wechat_family() -> str:
    """根据正在运行的微信进程判断 3.9 还是 4.x。没有进程时返回空字符串。"""
    try:
        import psutil
        import win32api
    except ImportError:
        return ""
    for proc in psutil.process_iter(["name", "exe"]):
        name = (proc.info.get("name") or "").lower()
        if name not in {"wechat.exe", "weixin.exe"}:
            continue
        exe = proc.info.get("exe") or ""
        version = _file_version(win32api, exe)
        if version.startswith("3."):
            return "3.9"
        if version.startswith("4."):
            return "4"
    return ""


def _file_version(win32api: Any, path: str) -> str:
    if not path:
        return ""
    try:
        info = win32api.GetFileVersionInfo(path, "\\")
        ms = info["FileVersionMS"]
        ls = info["FileVersionLS"]
    except Exception:
        return ""
    return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}"


def _connect_error(exc: Exception) -> str:
    return (
        "无法连接微信窗口。请先登录 PC 微信，并打开主窗口。\n"
        "微信 3.9 使用 wxauto 归档版，官方标注适配 3.9.11.17；"
        "微信 4.1 使用 wxauto4，免费版目前支持到 4.1.8.107。\n"
        f"原始错误: {exc}"
    )


def _call(obj: Any, name: str) -> Any:
    method = getattr(obj, name, None)
    if method is None:
        raise ReaderError(f"当前 wxauto 没有 {name} 方法。")
    try:
        return method()
    except Exception as exc:
        raise ReaderError(f"调用 {name} 失败。") from exc


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    info = getattr(value, "info", None)
    if isinstance(info, dict):
        return info
    return {}


def _pick(raw: Any, *names: str, default: Any = "") -> Any:
    info: dict[str, Any] = {}
    if isinstance(raw, dict):
        nested = raw.get("info")
        if isinstance(nested, dict):
            info = nested
        for name in names:
            if raw.get(name) is not None:
                return raw.get(name)
    else:
        nested = getattr(raw, "info", None)
        if isinstance(nested, dict):
            info = nested
        for name in names:
            value = getattr(raw, name, None)
            if value is not None:
                return value
    for name in names:
        if info.get(name) is not None:
            return info.get(name)
    return default


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
