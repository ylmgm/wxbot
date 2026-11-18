from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


class ConfigError(ValueError):
    """配置文件无法使用。"""


@dataclass(frozen=True)
class GroupSpec:
    name: str
    exact: bool = True


@dataclass(frozen=True)
class Settings:
    groups: tuple[GroupSpec, ...]
    poll_interval_seconds: float
    force_scan_rounds: int
    only_new_sessions: bool
    switch_pause_seconds: float
    store_time_messages: bool
    database: Path
    log_dir: Path
    config_path: Path | None = None

    def require_groups(self) -> tuple[GroupSpec, ...]:
        if not self.groups:
            raise ConfigError("config.yaml 里还没有群。请在 groups 下填写要读取的群名。")
        return self.groups

    def find_group(self, name: str) -> GroupSpec:
        for spec in self.groups:
            if spec.name == name:
                return spec
        return GroupSpec(name=name, exact=True)


def load_settings(path: Path) -> Settings:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise ConfigError(
            f"找不到配置文件 {path}。请先复制 config.example.yaml 为 config.yaml，并填入群名。"
        )
    try:
        raw = yaml.safe_load(_read_text(path)) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"配置文件不是合法的 YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError("配置文件的顶层必须是映射。")

    base = path.parent
    groups = _parse_groups(raw.get("groups", []))
    interval = _positive_number(raw.get("poll_interval_seconds", 5), "poll_interval_seconds")
    if interval < 2:
        raise ConfigError("poll_interval_seconds 不能小于 2，避免过于频繁地切换微信窗口。")
    force_rounds = _positive_int(raw.get("force_scan_rounds", 12), "force_scan_rounds")
    pause = _positive_number(raw.get("switch_pause_seconds", 0.6), "switch_pause_seconds")
    database = _resolve_path(base, raw.get("database", "data/messages.db"))
    log_dir = _resolve_path(base, raw.get("log_dir", "logs"))
    return Settings(
        groups=groups,
        poll_interval_seconds=interval,
        force_scan_rounds=force_rounds,
        only_new_sessions=bool(raw.get("only_new_sessions", True)),
        switch_pause_seconds=pause,
        store_time_messages=bool(raw.get("store_time_messages", False)),
        database=database,
        log_dir=log_dir,
        config_path=path,
    )


def _read_text(path: Path) -> str:
    data = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "gbk"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ConfigError(f"无法识别配置文件编码: {path}")


def _parse_groups(value: object) -> tuple[GroupSpec, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ConfigError("groups 必须是列表。")
    specs: list[GroupSpec] = []
    seen: set[str] = set()
    for item in value:
        if isinstance(item, str):
            name, exact = item.strip(), True
        elif isinstance(item, dict):
            name = str(item.get("name", "")).strip()
            exact = bool(item.get("exact", True))
        else:
            raise ConfigError("groups 里的每一项必须是群名，或包含 name 的映射。")
        if not name:
            raise ConfigError("群名不能为空。")
        if name in seen:
            raise ConfigError(f"群名重复: {name}")
        seen.add(name)
        specs.append(GroupSpec(name=name, exact=exact))
    return tuple(specs)


def _positive_number(value: object, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{field} 必须是数字。") from exc
    if number <= 0:
        raise ConfigError(f"{field} 必须大于 0。")
    return number


def _positive_int(value: object, field: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{field} 必须是整数。") from exc
    if number <= 0:
        raise ConfigError(f"{field} 必须大于 0。")
    return number


def _resolve_path(base: Path, value: object) -> Path:
    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        path = base / path
    return path
