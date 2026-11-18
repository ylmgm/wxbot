# wxauto 微信群消息读取

版本 0.1.0。在 Windows 上读取本机已经登录的 PC 微信里、配置点名的群消息，写入本地 SQLite。

程序只读。它会打开指定群并读取当前屏幕上的消息，不发送、不回复、不加好友，也不群发。

## 读到的是哪一屏

两种库都只能读到聊天窗口里已经加载出来的那一屏。程序按间隔切到配置里的群，和上一屏的指纹对齐，只把新出现在底部的消息入库。窗口上方还没滚出来的历史不在这次读取范围内。

程序根据正在运行的 `WeChat.exe` 或 `Weixin.exe` 文件版本选择库：

| 微信 | 库 | 说明 |
| --- | --- | --- |
| 3.9 | `wxauto` 39.2.1 | 从 GitHub `cluic/wxauto` 安装。PyPI 上的同名包已经下架。源码标注适配 3.9.11.17 |
| 4.1 | `wxauto4` | 免费版目前支持到 4.1.8.107。文档里标 ✨ 的监听、翻历史属于 Plus，本项目不用 |

版本号以 `3.` 开头走 `wxauto`，以 `4.` 开头走 `wxauto4`。读不到进程版本时，先试 `wxauto4`，失败再试 `wxauto`。

本机曾经用 3.9.12.51 读到过左侧会话列表。`wxauto4` 连不上这个客户端。3.9.12 和库标注的 3.9.11.17 不完全一样，打开具体群读取消息这一步还没有在这台客户端上核对过。界面控件变了时，打开群或解析消息会失败。

3.9 的库在初始化时会把主窗口显示到前台，并在控制台打印已登录窗口的昵称。

## 环境

- Windows 10 或 11
- Python 3.9 到 3.13
- Git。微信 3.9 的 `wxauto` 要从 GitHub 安装
- PC 微信已登录，主窗口开着
- 读取期间程序会切换当前会话。这段时间不要同时手动点微信

`wxauto4` 会导入 `comtypes.stream`，所以项目里把 `comtypes` 固定到 1.4.17 及以上。请装在项目虚拟环境里。

## 一键启动

先登录微信并打开主窗口，然后双击项目目录里的 `一键启动.bat`。

这个 bat 会切到自己所在目录，优先用 `pwsh`，没有就用 Windows PowerShell，并绕过执行策略去跑 `start.ps1`。出错时窗口会停住。

`start.ps1` 做这些事：

1. 没有 `.venv` 时创建。优先用 `py -3`，要求 Python 3.9–3.13；否则用 `python`。
2. `.venv\.requirements.stamp` 不存在，或比 `requirements.txt` 旧时，执行 `pip install -r requirements.txt`。3.9 的库要从 GitHub 下载，需要联网。
3. 没有 `config.yaml` 时，从 `config.example.yaml` 复制一份。
4. 配置里还写着「示例项目群」时，用记事本打开一次。改成左侧会话列表里的群名，保存并关闭记事本。若仍是示例名，脚本停止。
5. 执行 `.venv\Scripts\python.exe -m wxgroup watch`。

窗口里按 Ctrl+C 结束监听，再按回车关闭窗口。

## 手动安装

在项目目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
copy config.example.yaml config.yaml
```

然后编辑 `config.yaml`，再运行下面的命令。命令都要在项目目录、并且使用这个虚拟环境。也可以写成 `python -m wxgroup`。安装后入口名是 `wxgroup`。

所有命令都可以加 `--config 路径`，默认读取当前目录的 `config.yaml`。

## 配置

复制 `config.example.yaml` 为 `config.yaml`。程序按 UTF-8（可带 BOM）、UTF-8、GBK 的顺序解码，记事本另存成 ANSI 时也能读。YAML 本身不合法会直接报错。相对路径相对于配置文件所在目录。

```yaml
groups:
  - name: "项目群"
    exact: true

poll_interval_seconds: 5
force_scan_rounds: 12
only_new_sessions: true
switch_pause_seconds: 0.6
store_time_messages: false
database: data/messages.db
log_dir: logs
```

| 字段 | 含义 |
| --- | --- |
| `groups` | 要读取的群。每一项可以是字符串，或带 `name` 的映射。`exact` 默认 `true`，按去掉人数后的名字精确匹配。设为 `false` 时，配置名是窗口标题或备注的子串即可。空列表、空名字、重复名字都会拒绝 |
| `poll_interval_seconds` | 两轮之间的间隔，默认 5，不能小于 2 |
| `force_scan_rounds` | 每隔多少轮强制再读一遍，默认 12。用来照顾免打扰、以及当前没出现在可见会话列表里的群 |
| `only_new_sessions` | 默认 `true`。会话列表里没有新消息标记时先跳过。第 1 轮和强制轮仍会打开 |
| `switch_pause_seconds` | 打开下一个群之前的停顿，默认 0.6 秒，给界面留渲染时间 |
| `store_time_messages` | 默认 `false`。时间分隔条只用来给后面的消息标注时间，不单独入库 |
| `database` | SQLite 路径，默认 `data/messages.db` |
| `log_dir` | 日志目录，默认 `logs`，文件名 `wxgroup.log` |

`config.yaml`、`data/`、`logs/`、`.venv/` 已在 `.gitignore` 里，不要提交。

## 群名末尾的人数

微信标题末尾的 `（17）` 或 `(17)` 是群人数。搜索、核对、入库用的群名都会去掉这一段，所以人数从 17 变成 18 时，历史仍记在同一个群下。

配置里写成 `项目群（17）` 也可以，实际会按 `项目群` 去打开，数据库里的群名也是 `项目群`。名字中间的数字会保留，例如 `第（17）组`。

`sessions` 会在去掉人数后的名字旁边显示 `17人`。3.9 没有 `ChatInfo`，成员数取自当前窗口标题末尾。4.1 优先用 `ChatInfo` 里的 `group_member_count`，没有时再用标题末尾的数字。

以前已经按带人数的名字存进去的旧记录，仍留在原来的群名下。新的读取使用去掉人数后的名字。

## 命令

先看左侧当前可见的会话，确认能连上微信：

```powershell
python -m wxgroup sessions
```

行首 `*` 表示这个群写在配置里。有新消息时显示 `新` 或 `新N`，免打扰会话会标出「免打扰」。3.9 的会话对象通常只有「有没有新消息」，没有条数。

打开配置中的群，看类型、人数和当前屏幕上的消息条数：

```powershell
python -m wxgroup info
python -m wxgroup info --group 项目群
```

`--group` 可以重复。名字不在配置里时，按精确匹配临时打开。

把当前屏幕写入数据库。第一次是基线，之后只追加新消息：

```powershell
python -m wxgroup snapshot
python -m wxgroup snapshot --group 项目群 --reset
python -m wxgroup watch
```

`snapshot` 的输出里，`基线` 表示第一次整屏写入，`新增` 表示只写入新消息，`跳过` 表示这一屏和上次快照对不上、没有写入。

`watch` 一直运行，直到 Ctrl+C。每一轮先读可见会话：

- 第 1 轮，以及轮次能被 `force_scan_rounds` 整除时，强制打开配置里的每个群。
- 其他轮在 `only_new_sessions: true` 时，只打开列表里标了新消息的群。
- 群不在当前可见会话列表里时，非强制轮会跳过。
- 某个群打开失败时，记一条日志，继续下一个。

查看和导出已经入库的消息。`--group` 要写去掉人数后的群名。默认不显示时间分隔条，加上 `--all` 才一起出：

```powershell
python -m wxgroup query --group 项目群 --limit 20
python -m wxgroup query --sender 张三
python -m wxgroup query --keyword 开会
python -m wxgroup export --format jsonl
python -m wxgroup export --format csv --out data\messages.csv
```

`query` 默认最多 50 条，按时间从早到晚打印。`export` 默认写到数据库同目录的 `messages.jsonl` 或 `messages.csv`。CSV 用带 BOM 的 UTF-8，方便 Excel 打开。

不连接微信，用内置样例走一遍去重：

```powershell
python -m wxgroup demo
```

样例群是「示例项目群」。第一次写入 3 条基线，第二次追加「王五：我晚点到」。数据库在 `data/demo/messages.db`，每次运行会先删掉旧文件。

## 去重

指纹是这段内容的 SHA-256：时间标签、发送者、`attr`、消息类型、正文，以及 4.x 消息上可选的 `hash`。界面上的运行时 `id` 会变，不参与去重。

每一屏按顺序记下指纹。下一轮用上一屏末尾最长的一段，去对齐当前屏幕里同一段，只保存对齐位置之后的消息。微信窗口通常停在最新位置：旧消息从顶部滑出，新消息补在底部。

- 没有上一屏快照：整屏作为基线写入，`is_baseline` 为 1。
- 对得上，底部有新消息：只追加这些新消息，并更新这一屏的指纹。
- 对得上，没有新消息：不新增记录，仍更新这一屏的指纹。
- 完全对不上：跳过写入，保留旧快照，避免把同一屏再写一遍。日志会提示对该群执行 `snapshot --group 群名 --reset`。

同一时间标签里、正文完全相同的消息，指纹也相同。相邻的重复消息靠先后顺序对齐。窗口被大幅翻走、屏幕上只剩这种重复消息时，可能对不齐，用 `--reset` 清掉该群快照后再建基线。`--reset` 会同时清掉「带人数的旧群名」和「去掉人数后的群名」两份快照。

3.9 把 `friend`、`self`、`sys`、`time`、`recall` 放在 `type` 上。程序会把它们挪到 `attr`（`sys` 记成 `system`），再按正文前缀判断内容类型：`[图片]`、`[文件]`、`[语音]`、`[视频]`，其余记为 `text`。发送者 `Self` 记为「我」。4.x 本来就把发送者类别放在 `attr`、内容类别放在 `type`。

## 数据

默认数据库是 `data/messages.db`。日志是 `logs/wxgroup.log`，同时打到控制台。

`groups`

| 列 | 含义 |
| --- | --- |
| `name` | 去掉人数后的群名，主键 |
| `chat_type` | 4.1 为 `group` 等；3.9 读不到类型时为空 |
| `member_count` | 最近一次读到的人数 |
| `updated_at` | 最近一次写入时间，本地时区的 ISO 时间 |

`messages`

| 列 | 含义 |
| --- | --- |
| `id` | 自增主键 |
| `group_name` | 去掉人数后的群名 |
| `sender` | 发送者。自己的消息在 3.9 上记为「我」 |
| `attr` | `friend`、`self`、`system`、`time`、`recall` |
| `msg_type` | `text`、`image`、`file`、`voice`、`video`，或 4.x 原来的类型。时间分隔条为 `time` |
| `content` | 正文。图片、文件、语音、视频通常是 `[图片]` 这类占位文字 |
| `ui_id` | 界面运行时 id，会变 |
| `time_label` | 这条消息上方最近的时间分隔，例如「昨天」「14:32」。界面没有完整时间戳 |
| `fingerprint` | 去重指纹 |
| `captured_at` | 写入数据库的时间 |
| `is_baseline` | 1 表示来自第一次基线 |

`snapshot_items` 按 `group_name` 和 `position` 保存上一屏的指纹顺序。

JSONL 导出含全部字段。CSV 导出列为 `id`、`captured_at`、`group_name`、`time_label`、`sender`、`attr`、`msg_type`、`content`、`is_baseline`。

## 目录

```text
一键启动.bat          双击入口
start.ps1             创建环境、安装依赖、启动 watch
config.example.yaml   配置示例
config.yaml           本机配置，不提交
requirements.txt
pyproject.toml
wxgroup/              程序包
  cli.py              命令行
  client.py           连接微信、列会话、打开群
  config.py           读取配置
  names.py            去掉标题末尾的人数
  messages.py         规范化消息、对齐新消息
  service.py          快照与轮询
  store.py            SQLite
  demo.py             不连接微信的样例
tests/test_reader.py
data/messages.db      运行后生成
logs/wxgroup.log      运行后生成
```

在项目目录跑测试：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## 边界

只处理 `config.yaml` 里点名的群。`watch` 不会去读列表里的其他会话。打开之后会核对去掉人数后的窗口标题或备注。4.1 还能核对 `chat_type`，不是群就停止写入。3.9 没有这个字段，名字对上就会读；请把 `groups` 写成左侧会话列表里的群名，有备注时先填备注。

消息留在本机数据库。用它读取自己有权查看的群。

免费接口是 `GetSession` 或 `GetSessionList`、`ChatWith`、`GetAllMessage`。4.1 另外使用 `ChatInfo`。本项目不调用发送、加好友、新好友这些接口，也不使用 Plus 的独立监听窗口和翻历史。

轮询会把微信当前聊天切到正在读的群。间隔不要低于 2 秒。
