from __future__ import annotations

from wxgroup.client import ChatView, SessionView


_BASE_MESSAGES = [
    {"type": "time", "attr": "system", "sender": "", "content": "11月18日 14:30", "id": "t1"},
    {"type": "text", "attr": "friend", "sender": "张三", "content": "下午三点开会", "id": "m1"},
    {"type": "text", "attr": "friend", "sender": "李四", "content": "收到", "id": "m2"},
    {"type": "text", "attr": "self", "sender": "我", "content": "好", "id": "m3"},
]


class DemoReader:
    """不连接微信，用固定样例演示两轮读取。第二轮在底部追加一条新消息。"""

    def __init__(self) -> None:
        self.reads = 0

    def list_sessions(self) -> list[SessionView]:
        return [
            SessionView(
                name="示例项目群",
                time="14:31",
                content="收到",
                is_new=True,
                new_count=1,
                is_mute=False,
            )
        ]

    def read_chat(self, name: str, *, exact: bool) -> tuple[ChatView, list[dict]]:
        del exact
        if name != "示例项目群":
            raise KeyError(name)
        self.reads += 1
        messages = list(_BASE_MESSAGES)
        if self.reads >= 2:
            messages.append(
                {
                    "type": "text",
                    "attr": "friend",
                    "sender": "王五",
                    "content": "我晚点到",
                    "id": "m4",
                }
            )
        return (
            ChatView(
                chat_name="示例项目群",
                chat_type="group",
                member_count=12,
                remark="",
            ),
            messages,
        )
