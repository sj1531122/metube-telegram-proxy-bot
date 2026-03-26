from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import sys
import unittest


APP_DIR = Path(__file__).resolve().parents[2] / "app"

if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from ytdl import DownloadInfo, DownloadQueue


class FakeNotifier:
    async def added(self, dl):
        return None

    async def updated(self, dl):
        return None

    async def completed(self, dl):
        return None

    async def canceled(self, id):
        return None

    async def cleared(self, id):
        return None


class FakeProxyRuntime:
    def __init__(self, generation: int, fingerprint: str):
        self.current_generation = generation
        self.active_node_fingerprint = fingerprint


class FakeProxyFailover:
    def __init__(self, result: str):
        self.result = result
        self.calls: list[tuple[object, str]] = []

    async def handle_retryable_failure(self, *, task, error_text: str) -> str:
        self.calls.append((task, error_text))
        return self.result


class FakeDownload:
    def __init__(self, info):
        self.info = info
        self.tmpfilename = None
        self.canceled = False
        self.closed = False

    def close(self):
        self.closed = True


class DownloadQueueFailoverTests(unittest.IsolatedAsyncioTestCase):
    def make_config(self, root: Path):
        download_dir = root / "downloads"
        state_dir = root / "state"
        download_dir.mkdir()
        state_dir.mkdir()
        return SimpleNamespace(
            DOWNLOAD_DIR=str(download_dir),
            AUDIO_DOWNLOAD_DIR=str(download_dir),
            TEMP_DIR=str(download_dir),
            OUTPUT_TEMPLATE="%(title)s.%(ext)s",
            OUTPUT_TEMPLATE_CHAPTER="%(title)s - %(section_number)02d - %(section_title)s.%(ext)s",
            OUTPUT_TEMPLATE_PLAYLIST="%(playlist_title)s/%(title)s.%(ext)s",
            YTDL_OPTIONS={},
            STATE_DIR=str(state_dir),
            MAX_CONCURRENT_DOWNLOADS=1,
            CUSTOM_DIRS=True,
            CREATE_CUSTOM_DIRS=True,
            DELETE_FILE_ON_TRASHCAN=False,
        )

    def make_info(self, url: str = "https://video.example/watch") -> DownloadInfo:
        return DownloadInfo(
            "vid-1",
            "Video",
            url,
            "best",
            "mp4",
            "",
            "",
            "HTTP Error 429: Too Many Requests",
            None,
            0,
            False,
            "%(title)s.%(ext)s",
        )

    async def test_add_download_records_current_proxy_generation(self) -> None:
        with TemporaryDirectory() as tmp:
            config = self.make_config(Path(tmp))
            runtime = FakeProxyRuntime(generation=7, fingerprint="node-a")
            queue = DownloadQueue(config, FakeNotifier(), proxy_runtime=runtime, proxy_failover=None)
            info = self.make_info()

            await queue._DownloadQueue__add_download(info, False)

            self.assertEqual(queue.pending.get(info.url).info.proxy_generation_started, 7)

    async def test_handle_failed_download_calls_failover_coordinator_and_requeues_after_switch(self) -> None:
        with TemporaryDirectory() as tmp:
            config = self.make_config(Path(tmp))
            runtime = FakeProxyRuntime(generation=4, fingerprint="node-b")
            failover = FakeProxyFailover(result="switched_node")
            queue = DownloadQueue(config, FakeNotifier(), proxy_runtime=runtime, proxy_failover=failover)
            info = self.make_info()
            info.proxy_generation_started = 3
            download = FakeDownload(info)

            result = await queue._handle_failed_download(download)

            self.assertEqual(result, "requeued")
            self.assertEqual(len(failover.calls), 1)
            self.assertTrue(queue.queue.exists(info.url))
            self.assertEqual(queue.queue.get(info.url).info.proxy_generation_started, 4)

    async def test_handle_failed_download_does_not_retry_same_node_twice(self) -> None:
        with TemporaryDirectory() as tmp:
            config = self.make_config(Path(tmp))
            runtime = FakeProxyRuntime(generation=4, fingerprint="node-a")
            failover = FakeProxyFailover(result="retry_current_generation")
            queue = DownloadQueue(config, FakeNotifier(), proxy_runtime=runtime, proxy_failover=failover)
            info = self.make_info()
            info.proxy_generation_started = 4
            info.failover_attempts = 1
            info.attempted_node_fingerprints = ["node-a"]
            download = FakeDownload(info)

            result = await queue._handle_failed_download(download)

            self.assertEqual(result, "final_fail")
            self.assertFalse(queue.queue.exists(info.url))

    async def test_handle_failed_download_stops_after_three_distinct_nodes(self) -> None:
        with TemporaryDirectory() as tmp:
            config = self.make_config(Path(tmp))
            runtime = FakeProxyRuntime(generation=5, fingerprint="node-d")
            failover = FakeProxyFailover(result="retry_current_generation")
            queue = DownloadQueue(config, FakeNotifier(), proxy_runtime=runtime, proxy_failover=failover)
            info = self.make_info()
            info.proxy_generation_started = 5
            info.failover_attempts = 3
            info.attempted_node_fingerprints = ["node-a", "node-b", "node-c"]
            download = FakeDownload(info)

            result = await queue._handle_failed_download(download)

            self.assertEqual(result, "final_fail")
            self.assertFalse(queue.queue.exists(info.url))


if __name__ == "__main__":
    unittest.main()
