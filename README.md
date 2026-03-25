# MeTube Telegram Proxy Bot

Standalone Telegram download bot project powered by MeTube as the download backend.

独立 Telegram 下载机器人项目，以 MeTube 作为下载后端。

## 中文

### 项目定位

这个仓库的目标是构建一个独立的 Telegram 下载机器人：

- 你把链接发到 Telegram
- Bot 把任务提交到远端 MeTube
- MeTube 负责通过 yt-dlp 执行下载
- 下载完成后，Bot 把可直接访问的下载链接回发到 Telegram

这个项目同时考虑了代理环境、远端 MeTube 部署，以及 Telegram 与下载服务分离运行的场景。

### 当前状态

当前仓库还处于开发中，定位已经确定，但功能尚未全部落地：

- 当前代码主体仍然是 MeTube 基底代码
- Telegram Bot 已有 MVP 代码骨架，位于 `bot/`
- 任务提交、状态持久化、MeTube 轮询和 Telegram 回执的核心单元测试已就位
- README 现在描述的是仓库目标方向，而不是“已经全部完成的功能”

### 项目介绍

这个项目解决的问题很直接：

- 不再依赖手动打开 MeTube 页面提交下载
- 通过 Telegram 统一发送下载任务
- 由远端 MeTube 负责下载和文件托管
- 下载完成后，通过 Telegram 回传直链

MVP 目标是单用户、单聊天场景，不做多用户、多租户或复杂交互。

### 架构说明

系统边界如下：

1. Telegram Bot 与 MeTube 分离部署，不在同一台机器上。
2. Bot 负责接收 Telegram 消息、提取 URL、调用 MeTube API、轮询下载结果、发送回执。
3. MeTube 负责 yt-dlp 下载、文件落盘、下载历史和静态文件暴露。
4. 反向代理负责保护 `/add`、`/history` 等 API，同时公开 `/download/*`、`/audio_download/*` 文件路径，确保 Telegram 收到的是可直接点击的下载链接。

目标数据流：

`Telegram -> Bot -> MeTube API -> yt-dlp download -> public file URL -> Telegram`

### 开发中路线图

- [x] 仓库初始化与 GitHub 上传
- [x] 项目方向与架构设计
- [x] README 项目定位重写
- [ ] Telegram Bot MVP
- [ ] MeTube API 客户端封装
- [ ] SQLite 任务状态持久化
- [ ] 下载完成轮询与通知
- [ ] 公开下载链接与 API 鉴权分流
- [ ] 部署文档

### 当前仓库说明

当前仓库包含：

- MeTube 基础代码
- Telegram Bot 设计文档
- `.env.example` 示例配置
- 后续 Bot 开发所需的同仓库基础

设计文档见：

- `docs/superpowers/specs/2026-03-25-telegram-bot-metube-design.md`

环境变量示例见：

- `.env.example`

在 Telegram Bot 代码落地之前，如果你想了解当前下载后端能力，请参考上游 MeTube 项目文档。

### 最小运行说明

这份说明的目标不是完整部署，而是让你能跑通最小链路。

前提：

- 你已经创建好 Telegram Bot，并拿到 `TELEGRAM_BOT_TOKEN`
- 你知道自己的 Telegram `chat_id`
- 远端 MeTube 已可访问
- 如果 `/add` 和 `/history` 受保护，你已经准备好对应的鉴权头
- `PUBLIC_HOST_URL` 和 `PUBLIC_HOST_AUDIO_URL` 指向 Telegram 可直接访问的文件链接前缀

建议步骤：

1. 复制环境变量模板并填写真实值。

```bash
cp .env.example .env
```

2. 在 shell 中加载环境变量。

```bash
set -a
source .env
set +a
```

3. 启动 Bot。

```bash
python3 -m bot.main
```

4. 在 Telegram 中给 Bot 发送一个包含下载链接的消息。

5. 预期行为：
   - Bot 先回复 `Queued: <url>`
   - 下载完成后，Bot 再回复 `Finished: <title>` 和直链
   - 如果下载失败，Bot 会回复失败原因

最小公网接入建议：

- 反向代理保护：
  - `/add`
  - `/history`
- 公开下载路径：
  - `/download/*`
  - `/audio_download/*`

当前版本说明：

- 这是轮询版 MVP，不是 webhook
- 目前以单用户、单聊天为目标
- 运行前需要你自己先把 `.env` 中的值填好
- 如果你直接运行，会严格读取环境变量，不会自动解析 `.env` 文件

### systemd 部署说明

如果你已经按最小链路验证成功，可以直接用仓库内的 `systemd` 模板转为后台常驻运行。

模板文件：

- `deploy/systemd/metube-telegram-bot.service`

假设你的部署目录是 `/opt/metube-telegram-proxy-bot`，并且 `.env` 已经放在这个目录下。

1. 复制 service 文件到系统目录。

```bash
sudo cp deploy/systemd/metube-telegram-bot.service /etc/systemd/system/metube-telegram-bot.service
```

2. 重载 `systemd` 配置并启动服务。

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now metube-telegram-bot
```

3. 查看服务状态。

```bash
sudo systemctl status metube-telegram-bot
```

4. 实时查看日志。

```bash
sudo journalctl -u metube-telegram-bot -f
```

说明：

- 当前模板按源码方式运行，不需要先执行 `pip install .`
- 当前模板默认以 `root` 身份运行
- `WorkingDirectory` 固定为 `/opt/metube-telegram-proxy-bot`
- `EnvironmentFile` 固定为 `/opt/metube-telegram-proxy-bot/.env`
- `ExecStart` 固定为 `/usr/bin/python3 -m bot.main`

### 致谢 / Upstream

本项目当前基于 MeTube 代码演进而来。

- Upstream: https://github.com/alexta69/metube
- Downloader core: https://github.com/yt-dlp/yt-dlp

感谢 MeTube 与 yt-dlp 社区提供的基础能力。

## English

### Project Positioning

This repository is aimed at becoming a standalone Telegram download bot:

- send a media URL to Telegram
- let the bot submit the job to a remote MeTube instance
- let MeTube handle the actual yt-dlp download
- return a direct download link back to Telegram after completion

The project is designed for remote deployment, proxy-aware networking, and a clear separation between the Telegram bot and the download backend.

### Current Status

This repository is still under active development:

- the current codebase is still primarily MeTube-based
- the Telegram bot layer has not been fully implemented yet
- this README describes the target direction of the repository, not a fully finished feature set

### Overview

The goal is simple:

- avoid manually opening the MeTube web UI for every download
- submit download jobs through Telegram
- keep MeTube as the remote downloader and file host
- send a direct file URL back to Telegram once the download finishes

The MVP is intentionally scoped for a single-user, single-chat workflow.

### Architecture

The system boundary is:

1. Telegram Bot and MeTube are deployed on different machines.
2. The bot receives Telegram messages, extracts URLs, calls the MeTube API, polls job status, and sends replies.
3. MeTube handles yt-dlp downloads, file storage, history, and static file exposure.
4. A reverse proxy protects API routes such as `/add` and `/history`, while keeping `/download/*` and `/audio_download/*` publicly accessible so Telegram links can be opened directly.

Target flow:

`Telegram -> Bot -> MeTube API -> yt-dlp download -> public file URL -> Telegram`

### Roadmap

- [x] Repository initialization and GitHub publishing
- [x] Project direction and architecture design
- [x] README repositioning
- [ ] Telegram bot MVP
- [ ] MeTube API client wrapper
- [ ] SQLite task persistence
- [ ] Polling-based completion tracking and notifications
- [ ] Public download link and protected API split
- [ ] Deployment documentation

### Repository Notes

At this stage, the repository contains:

- the MeTube codebase
- the Telegram bot design document
- an `.env.example` file for end-to-end configuration
- an initial bot MVP skeleton under `bot/`
- unit tests for config loading, URL parsing, persistence, MeTube API calls, Telegram API calls, and service orchestration

Design document:

- `docs/superpowers/specs/2026-03-25-telegram-bot-metube-design.md`

Environment example:

- `.env.example`

Until the Telegram bot implementation lands, refer to the upstream MeTube project for backend runtime details.

### Minimal Run Guide

This is not a full deployment guide. It is the shortest path to run the current MVP flow end to end.

Prerequisites:

- you already created a Telegram bot and have a real `TELEGRAM_BOT_TOKEN`
- you know your Telegram `chat_id`
- your remote MeTube instance is reachable
- if `/add` and `/history` are protected, you already have the required auth header pair
- `PUBLIC_HOST_URL` and `PUBLIC_HOST_AUDIO_URL` point to direct file URLs reachable from Telegram

Suggested steps:

1. Copy the example environment file and fill in real values.

```bash
cp .env.example .env
```

2. Load the environment variables into your shell.

```bash
set -a
source .env
set +a
```

3. Start the bot.

```bash
python3 -m bot.main
```

4. Send a message containing a media URL to your Telegram bot.

Expected behavior:

- the bot first replies with `Queued: <url>`
- after completion, it replies with `Finished: <title>` and a direct download URL
- if the download fails, it replies with the failure reason

Minimal public routing recommendation:

- protect:
  - `/add`
  - `/history`
- expose publicly:
  - `/download/*`
  - `/audio_download/*`

Current limitations:

- this is a polling-based MVP, not a webhook-based bot
- it is currently scoped for a single user and a single chat
- you must fill in `.env` yourself before running
- the code reads environment variables directly and does not auto-load `.env`

### systemd Deployment

If the minimal end-to-end flow already works, you can switch the bot to a background `systemd` service using the template in this repository.

Template file:

- `deploy/systemd/metube-telegram-bot.service`

Assumptions:

- the repository is deployed at `/opt/metube-telegram-proxy-bot`
- your `.env` file already exists at `/opt/metube-telegram-proxy-bot/.env`

1. Copy the service file into the systemd directory.

```bash
sudo cp deploy/systemd/metube-telegram-bot.service /etc/systemd/system/metube-telegram-bot.service
```

2. Reload `systemd` and start the service.

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now metube-telegram-bot
```

3. Check service status.

```bash
sudo systemctl status metube-telegram-bot
```

4. Follow logs in real time.

```bash
sudo journalctl -u metube-telegram-bot -f
```

Notes:

- the current template runs directly from source, so `pip install .` is not required
- the current template runs as `root`
- `WorkingDirectory` is fixed to `/opt/metube-telegram-proxy-bot`
- `EnvironmentFile` is fixed to `/opt/metube-telegram-proxy-bot/.env`
- `ExecStart` is fixed to `/usr/bin/python3 -m bot.main`

### Credits / Upstream

This project currently evolves from the MeTube codebase.

- Upstream: https://github.com/alexta69/metube
- Downloader core: https://github.com/yt-dlp/yt-dlp

Thanks to the MeTube and yt-dlp communities for the foundation.
