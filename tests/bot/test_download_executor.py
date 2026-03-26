import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase

from bot.download_executor import run_download


class FakeProcess:
    def __init__(self, *, stdout: str = "", stderr: str = "", returncode: int = 0, delay: float = 0.0):
        self._stdout = stdout.encode("utf-8")
        self._stderr = stderr.encode("utf-8")
        self.returncode = returncode
        self.delay = delay
        self.kill_called = False
        self.wait_called = False

    async def communicate(self):
        if self.delay:
            await asyncio.sleep(self.delay)
        return self._stdout, self._stderr

    def kill(self):
        self.kill_called = True
        self.returncode = -9

    async def wait(self):
        self.wait_called = True
        return self.returncode


class RunDownloadTests(IsolatedAsyncioTestCase):
    async def test_run_download_returns_title_and_relative_filename(self):
        with TemporaryDirectory() as tmp:
            download_dir = Path(tmp) / "downloads"
            download_dir.mkdir()
            final_file = download_dir / "movie.mp4"
            final_file.write_bytes(b"video")
            calls = []

            async def fake_process_factory(*args, **kwargs):
                calls.append((args, kwargs))
                return FakeProcess(
                    stdout=f"TITLE:Movie\nFILEPATH:{final_file}\n",
                    returncode=0,
                )

            result = await run_download(
                source_url="https://video.example/watch",
                download_dir=download_dir,
                timeout_seconds=30,
                process_factory=fake_process_factory,
            )

            self.assertTrue(result.ok)
            self.assertEqual(result.title, "Movie")
            self.assertEqual(result.filename, "movie.mp4")
            self.assertIsNone(result.error_text)
            command = calls[0][0]
            self.assertIn("yt-dlp", command)
            self.assertIn("--print", command)

    async def test_run_download_adds_proxy_flag_when_proxy_url_is_set(self):
        with TemporaryDirectory() as tmp:
            download_dir = Path(tmp) / "downloads"
            download_dir.mkdir()
            final_file = download_dir / "movie.mp4"
            final_file.write_bytes(b"video")
            calls = []

            async def fake_process_factory(*args, **kwargs):
                calls.append((args, kwargs))
                return FakeProcess(
                    stdout=f"TITLE:Movie\nFILEPATH:{final_file}\n",
                    returncode=0,
                )

            await run_download(
                source_url="https://video.example/watch",
                download_dir=download_dir,
                proxy_url="http://127.0.0.1:10809",
                timeout_seconds=30,
                process_factory=fake_process_factory,
            )

            command = list(calls[0][0])
            proxy_index = command.index("--proxy")
            self.assertEqual(command[proxy_index + 1], "http://127.0.0.1:10809")

    async def test_run_download_returns_stderr_text_for_failed_process(self):
        with TemporaryDirectory() as tmp:
            download_dir = Path(tmp) / "downloads"
            download_dir.mkdir()

            async def fake_process_factory(*args, **kwargs):
                return FakeProcess(
                    stderr="HTTP Error 429: Too Many Requests",
                    returncode=1,
                )

            result = await run_download(
                source_url="https://video.example/watch",
                download_dir=download_dir,
                timeout_seconds=30,
                process_factory=fake_process_factory,
            )

            self.assertFalse(result.ok)
            self.assertEqual(result.error_text, "HTTP Error 429: Too Many Requests")

    async def test_run_download_kills_process_when_timeout_is_hit(self):
        with TemporaryDirectory() as tmp:
            download_dir = Path(tmp) / "downloads"
            download_dir.mkdir()
            process = FakeProcess(delay=1.0)

            async def fake_process_factory(*args, **kwargs):
                return process

            result = await run_download(
                source_url="https://video.example/watch",
                download_dir=download_dir,
                timeout_seconds=0.01,
                process_factory=fake_process_factory,
            )

            self.assertFalse(result.ok)
            self.assertTrue(result.timed_out)
            self.assertTrue(process.kill_called)
            self.assertTrue(process.wait_called)
