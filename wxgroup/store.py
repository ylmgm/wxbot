from __future__ import annotations

import csv
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from wxgroup.messages import NormalizedMessage


@dataclass(frozen=True)
class StoredMessage:
    id: int
    group_name: str
    sender: str
    attr: str
    msg_type: str
    content: str
    ui_id: str
    time_label: str
    fingerprint: str
    captured_at: str
    is_baseline: bool


class MessageStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def close(self) -> None:
        self._conn.close()

    def commit_capture(
        self,
        group_name: str,
        visible: list[NormalizedMessage],
        fresh: list[NormalizedMessage],
        *,
        is_baseline: bool,
        chat_type: str,
        member_count: int | None,
    ) -> int:
        captured_at = _now()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO groups (name, chat_type, member_count, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    chat_type = excluded.chat_type,
                    member_count = excluded.member_count,
                    updated_at = excluded.updated_at
                """,
                (group_name, chat_type, member_count, captured_at),
            )
            for message in fresh:
                self._conn.execute(
                    """
                    INSERT INTO messages (
                        group_name, sender, attr, msg_type, content, ui_id,
                        time_label, fingerprint, captured_at, is_baseline
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        message.group_name,
                        message.sender,
                        message.attr,
                        message.msg_type,
                        message.content,
                        message.ui_id,
                        message.time_label,
                        message.fingerprint,
                        captured_at,
                        1 if is_baseline else 0,
                    ),
                )
            self._replace_snapshot(group_name, [item.fingerprint for item in visible])
        return len(fresh)

    def snapshot_keys(self, group_name: str) -> list[str]:
        rows = self._conn.execute(
            """
            SELECT fingerprint
            FROM snapshot_items
            WHERE group_name = ?
            ORDER BY position
            """,
            (group_name,),
        ).fetchall()
        return [row["fingerprint"] for row in rows]

    def clear_snapshot(self, group_name: str) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM snapshot_items WHERE group_name = ?", (group_name,))

    def query(
        self,
        *,
        group_name: str | None = None,
        sender: str | None = None,
        keyword: str | None = None,
        include_time: bool = False,
        limit: int = 50,
    ) -> list[StoredMessage]:
        clauses = ["1 = 1"]
        params: list[object] = []
        if group_name:
            clauses.append("group_name = ?")
            params.append(group_name)
        if sender:
            clauses.append("sender = ?")
            params.append(sender)
        if keyword:
            clauses.append("content LIKE ?")
            params.append(f"%{keyword}%")
        if not include_time:
            clauses.append("msg_type != 'time'")
        params.append(limit)
        rows = self._conn.execute(
            f"""
            SELECT *
            FROM messages
            WHERE {' AND '.join(clauses)}
            ORDER BY id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        return [_row_to_message(row) for row in reversed(rows)]

    def export_rows(
        self,
        *,
        group_name: str | None = None,
        include_time: bool = False,
    ) -> list[StoredMessage]:
        clauses = ["1 = 1"]
        params: list[object] = []
        if group_name:
            clauses.append("group_name = ?")
            params.append(group_name)
        if not include_time:
            clauses.append("msg_type != 'time'")
        rows = self._conn.execute(
            f"""
            SELECT *
            FROM messages
            WHERE {' AND '.join(clauses)}
            ORDER BY id
            """,
            params,
        ).fetchall()
        return [_row_to_message(row) for row in rows]

    def group_summaries(self) -> list[sqlite3.Row]:
        return list(
            self._conn.execute(
                """
                SELECT
                    g.name,
                    g.chat_type,
                    g.member_count,
                    g.updated_at,
                    COUNT(m.id) AS message_count
                FROM groups AS g
                LEFT JOIN messages AS m
                    ON m.group_name = g.name AND m.msg_type != 'time'
                GROUP BY g.name
                ORDER BY g.updated_at DESC
                """
            )
        )

    def _replace_snapshot(self, group_name: str, fingerprints: list[str]) -> None:
        self._conn.execute("DELETE FROM snapshot_items WHERE group_name = ?", (group_name,))
        self._conn.executemany(
            """
            INSERT INTO snapshot_items (group_name, position, fingerprint)
            VALUES (?, ?, ?)
            """,
            [(group_name, index, fingerprint) for index, fingerprint in enumerate(fingerprints)],
        )

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS groups (
                name TEXT PRIMARY KEY,
                chat_type TEXT NOT NULL DEFAULT '',
                member_count INTEGER,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_name TEXT NOT NULL,
                sender TEXT NOT NULL DEFAULT '',
                attr TEXT NOT NULL DEFAULT '',
                msg_type TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL DEFAULT '',
                ui_id TEXT NOT NULL DEFAULT '',
                time_label TEXT NOT NULL DEFAULT '',
                fingerprint TEXT NOT NULL,
                captured_at TEXT NOT NULL,
                is_baseline INTEGER NOT NULL DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_messages_group_id
                ON messages (group_name, id);

            CREATE TABLE IF NOT EXISTS snapshot_items (
                group_name TEXT NOT NULL,
                position INTEGER NOT NULL,
                fingerprint TEXT NOT NULL,
                PRIMARY KEY (group_name, position)
            );
            """
        )


def write_jsonl(path: Path, messages: list[StoredMessage]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for message in messages:
            handle.write(json.dumps(_message_dict(message), ensure_ascii=False) + "\n")


def write_csv(path: Path, messages: list[StoredMessage]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "id",
        "captured_at",
        "group_name",
        "time_label",
        "sender",
        "attr",
        "msg_type",
        "content",
        "is_baseline",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for message in messages:
            row = _message_dict(message)
            writer.writerow({name: row[name] for name in fieldnames})


def _message_dict(message: StoredMessage) -> dict[str, object]:
    return {
        "id": message.id,
        "group_name": message.group_name,
        "sender": message.sender,
        "attr": message.attr,
        "msg_type": message.msg_type,
        "content": message.content,
        "ui_id": message.ui_id,
        "time_label": message.time_label,
        "fingerprint": message.fingerprint,
        "captured_at": message.captured_at,
        "is_baseline": message.is_baseline,
    }


def _row_to_message(row: sqlite3.Row) -> StoredMessage:
    return StoredMessage(
        id=row["id"],
        group_name=row["group_name"],
        sender=row["sender"],
        attr=row["attr"],
        msg_type=row["msg_type"],
        content=row["content"],
        ui_id=row["ui_id"],
        time_label=row["time_label"],
        fingerprint=row["fingerprint"],
        captured_at=row["captured_at"],
        is_baseline=bool(row["is_baseline"]),
    )


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
