from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from aiohttp import web

DOWNLOAD_DIR_KEY = web.AppKey("download_dir", Path)


def create_download_app(download_dir: str | Path) -> web.Application:
    app = web.Application()
    app[DOWNLOAD_DIR_KEY] = Path(download_dir).resolve()
    app.router.add_get("/download/{filename:.*}", _handle_download)
    return app


async def _handle_download(request: web.Request) -> web.StreamResponse:
    download_dir = request.app[DOWNLOAD_DIR_KEY]
    requested_path = request.match_info.get("filename", "")
    candidate = (download_dir / requested_path).resolve()

    try:
        candidate.relative_to(download_dir)
    except ValueError as exc:
        raise web.HTTPNotFound() from exc

    if not candidate.exists() or not candidate.is_file():
        raise web.HTTPNotFound()

    return web.FileResponse(candidate)


@dataclass(slots=True)
class DownloadServerHandle:
    runner: web.AppRunner

    async def close(self) -> None:
        await self.runner.cleanup()


async def start_download_server(
    *,
    download_dir: str | Path,
    bind: str,
    port: int,
) -> DownloadServerHandle:
    app = create_download_app(download_dir)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, bind, port)
    await site.start()
    return DownloadServerHandle(runner=runner)
