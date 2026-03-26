from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class DownloadResult:
    ok: bool
    title: str | None
    filename: str | None
    error_text: str | None
    timed_out: bool = False


async def run_download(
    *,
    source_url: str,
    download_dir: str | Path,
    proxy_url: str | None = None,
    timeout_seconds: float,
    process_factory=asyncio.create_subprocess_exec,
) -> DownloadResult:
    download_root = Path(download_dir).resolve()
    command = [
        "yt-dlp",
        "--no-progress",
        "--newline",
        "--print",
        "before_dl:TITLE:%(title)s",
        "--print",
        "after_move:FILEPATH:%(filepath)s",
        "-P",
        str(download_root),
        "-o",
        "%(title)s.%(ext)s",
    ]
    if proxy_url:
        command.extend(["--proxy", proxy_url])
    command.append(source_url)

    process = await process_factory(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        return DownloadResult(
            ok=False,
            title=None,
            filename=None,
            error_text="download timed out",
            timed_out=True,
        )

    stdout_text = stdout.decode("utf-8", errors="replace")
    stderr_text = stderr.decode("utf-8", errors="replace").strip() or None
    title = None
    filename = None

    for line in stdout_text.splitlines():
        if line.startswith("TITLE:"):
            title = line.removeprefix("TITLE:").strip() or None
        elif line.startswith("FILEPATH:"):
            raw_path = line.removeprefix("FILEPATH:").strip()
            if raw_path:
                try:
                    filename = str(Path(raw_path).resolve().relative_to(download_root))
                except ValueError:
                    filename = Path(raw_path).name

    if process.returncode == 0:
        return DownloadResult(
            ok=True,
            title=title,
            filename=filename,
            error_text=None,
        )

    return DownloadResult(
        ok=False,
        title=title,
        filename=filename,
        error_text=stderr_text or "download failed",
    )
