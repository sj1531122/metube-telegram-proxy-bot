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
- 后续 Bot 开发所需的同仓库基础

设计文档见：

- `docs/superpowers/specs/2026-03-25-telegram-bot-metube-design.md`

在 Telegram Bot 代码落地之前，如果你想了解当前下载后端能力，请参考上游 MeTube 项目文档。

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
- an initial bot MVP skeleton under `bot/`
- unit tests for config loading, URL parsing, persistence, MeTube API calls, Telegram API calls, and service orchestration

Design document:

- `docs/superpowers/specs/2026-03-25-telegram-bot-metube-design.md`

Until the Telegram bot implementation lands, refer to the upstream MeTube project for backend runtime details.

### Credits / Upstream

This project currently evolves from the MeTube codebase.

- Upstream: https://github.com/alexta69/metube
- Downloader core: https://github.com/yt-dlp/yt-dlp

Thanks to the MeTube and yt-dlp communities for the foundation.
