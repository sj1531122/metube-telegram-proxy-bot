# MeTube Telegram Proxy Bot

Standalone Telegram download bot powered by MeTube as the download backend.

独立 Telegram 下载机器人，以 MeTube 作为下载后端。

## Verified Status

This repository is no longer just a design target. The current `main` branch has been implemented and manually verified in a real server deployment.

已验证通过的主流程：

- Telegram 发送链接后，Bot 将任务提交给远端 MeTube
- 下载完成后，Bot 回传可直接点击的下载链接
- Bot 与 MeTube 可分离部署，不要求在同一台机器上
- `systemd` 常驻运行方案已验证通过
- SQLite 任务持久化已验证通过
- 自动重试已验证通过：
  - 首次失败后只发送一次自动重试提示
  - 固定退避重试 5 次：`30 / 60 / 120 / 300 / 600` 秒
  - 成功重试后会清理旧的 failed history，避免被旧记录再次误判
- YouTube 短链接与跟踪参数规范化匹配已验证通过：
  - `youtu.be/...`
  - `youtube.com/watch?...&si=...`

## 中文

### 项目简介

这个项目面向单用户、单聊天场景，目标很直接：

- 你把下载链接发给 Telegram Bot
- Bot 把任务提交到远端 MeTube
- MeTube 负责调用 `yt-dlp` 执行下载
- 下载完成后，Bot 把可直接访问的下载链接回发到 Telegram

这个项目适合下面这类部署方式：

- Telegram Bot 和 MeTube 分离部署
- MeTube 放在单独服务器上
- MeTube 所在网络已经配置好代理或可正常访问目标站点
- Telegram 只作为任务入口和结果通知通道

### 已验证功能

当前 `main` 分支已经验证通过的能力：

- Telegram 消息收取与 URL 提取
- 单聊天白名单限制
- 远端 MeTube `POST /add` 任务提交
- MeTube `GET /history` 轮询
- 下载完成后回传公网直链
- 音频与视频下载链接分别使用不同公开前缀
- SQLite 任务状态持久化
- 去重窗口控制，避免短时间重复提交
- 超时保护与基础日志记录
- `systemd` 后台常驻运行
- 失败自动重试
- YouTube 短链接标准化匹配

### 架构说明

系统边界如下：

1. Telegram Bot 接收消息并提取下载链接。
2. Bot 调用远端 MeTube API 提交任务。
3. MeTube 负责 `yt-dlp` 下载、文件落盘和历史记录维护。
4. Bot 通过轮询 MeTube 历史判断任务结果。
5. 成功后，Bot 向 Telegram 回发可直接打开的下载链接。

目标数据流：

`Telegram -> Bot -> MeTube API -> yt-dlp download -> public file URL -> Telegram`

推荐的公网暴露方式：

- 保护 API：
  - `/add`
  - `/history`
  - `/delete`
- 公开文件下载路径：
  - `/download/*`
  - `/audio_download/*`

### 自动重试行为

当前版本的自动重试策略已经落地并验证：

- 首次失败时：
  - Bot 不会立刻判定最终失败
  - 会发送一次提示：`Failed once, retrying automatically (1/5): ...`
- 后续不会连续刷屏发送每次重试通知
- 重试间隔固定为：
  - `30s`
  - `60s`
  - `120s`
  - `300s`
  - `600s`
- 如果后续某次成功：
  - 只发送最终成功消息
- 如果 5 次重试全部失败：
  - 才发送最终失败消息

### 环境变量

示例文件：

- `.env.example`

当前使用的关键变量：

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_ALLOWED_CHAT_ID`
- `METUBE_BASE_URL`
- `METUBE_AUTH_HEADER_NAME`
- `METUBE_AUTH_HEADER_VALUE`
- `PUBLIC_HOST_URL`
- `PUBLIC_HOST_AUDIO_URL`
- `BOT_SQLITE_PATH`
- `BOT_HTTP_TIMEOUT_SECONDS`
- `BOT_POLL_INTERVAL_SECONDS`
- `BOT_TASK_TIMEOUT_SECONDS`
- `BOT_DEDUPE_WINDOW_SECONDS`

说明：

- 如果你的反向代理不保护 MeTube API，可以把 `METUBE_AUTH_HEADER_NAME` 和 `METUBE_AUTH_HEADER_VALUE` 留空
- `PUBLIC_HOST_URL` 和 `PUBLIC_HOST_AUDIO_URL` 必须是 Telegram 客户端可以直接访问的公网地址
- 代码直接读取环境变量，不会自动解析 `.env`

### 最小运行方式

1. 复制环境变量模板：

```bash
cp .env.example .env
```

2. 填入真实值后加载环境变量：

```bash
set -a
source .env
set +a
```

3. 直接启动 Bot：

```bash
python3 -m bot.main
```

4. 在 Telegram 中发送一个下载链接。

预期行为：

- 先收到：`Queued: <url>`
- 下载成功后收到：`Finished: <title>` 加直链
- 如果首次下载失败且可重试：
  - 收到一次自动重试提示
- 如果最终失败：
  - 收到失败原因

### systemd 部署

仓库内已提供部署模板：

- `deploy/systemd/metube-telegram-bot.service`

当前模板假设：

- 代码部署在 `/opt/metube-telegram-proxy-bot`
- 环境文件在 `/opt/metube-telegram-proxy-bot/.env`
- 直接使用系统 Python 运行 `python3 -m bot.main`

部署步骤：

1. 复制 service 文件：

```bash
sudo cp deploy/systemd/metube-telegram-bot.service /etc/systemd/system/metube-telegram-bot.service
```

2. 重载并启动：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now metube-telegram-bot
```

3. 查看状态：

```bash
sudo systemctl status metube-telegram-bot
```

4. 查看日志：

```bash
sudo journalctl -u metube-telegram-bot -f
```

### 验证流程

建议按两步验证：

1. 先发一个稳定链接：
   - 验证基础提交、下载完成、直链回传是否正常
2. 再发一个容易受代理波动影响的链接：
   - 验证首次失败后是否进入自动重试
   - 验证只发送一次重试提示
   - 验证最终成功或最终失败消息是否符合预期

### 当前范围

当前版本的明确范围：

- 单用户
- 单聊天
- 轮询模式，不是 webhook
- 依赖已可用的远端 MeTube
- 不处理多租户、权限分级或复杂交互命令

### 后续可选优化

当前主流程已经可用，后续如果继续演进，比较合理的方向是：

- 增加 `/status`、`/last` 之类的查询命令
- 将重试策略改为可配置环境变量
- 增加更细的错误分类与日志
- 增加 webhook 模式
- 增加多用户或多聊天支持

### Upstream

本项目基于 MeTube 演进，并继续使用 `yt-dlp` 作为下载核心。

- MeTube: https://github.com/alexta69/metube
- yt-dlp: https://github.com/yt-dlp/yt-dlp

## English

### Overview

This project is a standalone Telegram download bot for a single-user workflow:

- send a media URL to a Telegram bot
- let the bot submit the job to a remote MeTube instance
- let MeTube handle the actual `yt-dlp` download
- send a direct download URL back to Telegram after completion

It is designed for deployments where:

- the Telegram bot and MeTube run on different machines
- MeTube already has the required proxy/network access
- Telegram is used as the submission and notification channel

### Verified Features

The current `main` branch has been implemented and manually validated for:

- Telegram message intake and URL extraction
- single-chat allowlist control
- remote MeTube task submission via `POST /add`
- polling-based completion tracking via `GET /history`
- direct public download links returned to Telegram
- separate public prefixes for video and audio downloads
- SQLite task persistence
- short-window duplicate suppression
- timeout handling and runtime logging
- `systemd` background deployment
- automatic retry for transient download failures
- YouTube short-link normalization for task/history matching

### Retry Behavior

The verified retry behavior is:

- on the first MeTube failure, the bot sends one retry notice:
  - `Failed once, retrying automatically (1/5): ...`
- it retries up to 5 times with fixed backoff:
  - `30 / 60 / 120 / 300 / 600` seconds
- it does not spam Telegram with one message per retry
- after a successful re-submit, it clears the stale failed MeTube history entry
- it only sends a final failure message after the retry budget is exhausted

### Architecture

System flow:

1. Telegram Bot receives the message and extracts URLs.
2. The bot submits the job to remote MeTube.
3. MeTube performs the `yt-dlp` download and stores files.
4. The bot polls MeTube history for task state changes.
5. The bot sends a direct downloadable URL back to Telegram.

Data flow:

`Telegram -> Bot -> MeTube API -> yt-dlp download -> public file URL -> Telegram`

Recommended public routing:

- protect:
  - `/add`
  - `/history`
  - `/delete`
- expose publicly:
  - `/download/*`
  - `/audio_download/*`

### Environment

Example file:

- `.env.example`

Key variables:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_ALLOWED_CHAT_ID`
- `METUBE_BASE_URL`
- `METUBE_AUTH_HEADER_NAME`
- `METUBE_AUTH_HEADER_VALUE`
- `PUBLIC_HOST_URL`
- `PUBLIC_HOST_AUDIO_URL`
- `BOT_SQLITE_PATH`
- `BOT_HTTP_TIMEOUT_SECONDS`
- `BOT_POLL_INTERVAL_SECONDS`
- `BOT_TASK_TIMEOUT_SECONDS`
- `BOT_DEDUPE_WINDOW_SECONDS`

Notes:

- leave the MeTube auth header pair empty if your reverse proxy does not protect the API
- `PUBLIC_HOST_URL` and `PUBLIC_HOST_AUDIO_URL` must be directly reachable from the Telegram client
- the code reads environment variables directly and does not auto-load `.env`

### Minimal Run

```bash
cp .env.example .env
set -a
source .env
set +a
python3 -m bot.main
```

Expected behavior:

- first reply: `Queued: <url>`
- on success: `Finished: <title>` plus a direct download URL
- on first retryable failure: one retry notice
- on final failure: a failure message with the last known reason

### systemd Deployment

Template file:

- `deploy/systemd/metube-telegram-bot.service`

The current template assumes:

- repository path: `/opt/metube-telegram-proxy-bot`
- env file path: `/opt/metube-telegram-proxy-bot/.env`
- runtime entrypoint: `/usr/bin/python3 -m bot.main`

Deploy:

```bash
sudo cp deploy/systemd/metube-telegram-bot.service /etc/systemd/system/metube-telegram-bot.service
sudo systemctl daemon-reload
sudo systemctl enable --now metube-telegram-bot
sudo systemctl status metube-telegram-bot
sudo journalctl -u metube-telegram-bot -f
```

### Scope and Limits

Current scope:

- single user
- single chat
- polling-based bot, not webhook-based
- requires an already working remote MeTube instance
- not a multi-tenant platform

### Possible Next Improvements

- add `/status` or recent-task query commands
- make retry policy configurable via environment variables
- improve error classification and operational logs
- support webhook mode
- extend beyond single-user deployment

### Upstream

- MeTube: https://github.com/alexta69/metube
- yt-dlp: https://github.com/yt-dlp/yt-dlp
