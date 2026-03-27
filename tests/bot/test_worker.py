from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase

from bot.download_executor import DownloadResult
from bot.models import STATE_FAILED, STATE_FINISHED, STATE_RETRYING, STATE_TIMEOUT
from bot.store import TaskStore
from bot.worker import DownloadWorker


class FakeDownloadRunner:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return self.results.pop(0)


class FakeProxyRuntime:
    def __init__(self, *, generation: int = 1, fingerprints: list[str] | None = None):
        self.current_generation = generation
        self._fingerprints = list(fingerprints or ["node-a"])
        self.active_node_fingerprint = self._fingerprints[0] if self._fingerprints else None
        self.failed_calls = []
        self.switch_calls = []

    def mark_current_node_failed(self, *, reason: str, now: float) -> None:
        self.failed_calls.append((self.active_node_fingerprint, reason, now))

    async def switch_to_next_node(self, *, reason: str) -> bool:
        self.switch_calls.append(reason)
        if len(self._fingerprints) <= 1:
            return False
        self._fingerprints.pop(0)
        self.active_node_fingerprint = self._fingerprints[0]
        self.current_generation += 1
        return True


class DownloadWorkerTests(IsolatedAsyncioTestCase):
    def make_config(self, root: Path):
        download_dir = root / "downloads"
        download_dir.mkdir()
        return SimpleNamespace(
            download_dir=str(download_dir),
            public_download_base_url="https://downloads.example.com/download",
            task_timeout_seconds=600,
            poll_interval_seconds=1.0,
            cookies_file=None,
            ytdlp_extra_args=(),
        )

    async def test_run_one_task_marks_successful_download_finished(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root)
            store = TaskStore(root / "tasks.sqlite3")
            task_id = store.create_task(
                chat_id=1,
                telegram_message_id=10,
                source_url="https://video.example/watch",
            )
            runner = FakeDownloadRunner(
                [
                    DownloadResult(
                        ok=True,
                        title="Movie",
                        filename="movie.mp4",
                        error_text=None,
                    )
                ]
            )
            worker = DownloadWorker(
                config=config,
                store=store,
                download_runner=runner,
                proxy_runtime=None,
                time_fn=lambda: 100.0,
            )

            worked = await worker.run_one_task()

            task = store.get_task(task_id)
            self.assertTrue(worked)
            self.assertEqual(task.state, STATE_FINISHED)
            self.assertEqual(task.title, "Movie")
            self.assertEqual(task.filename, "movie.mp4")
            self.assertEqual(
                task.download_url,
                "https://downloads.example.com/download/movie.mp4",
            )
            self.assertEqual(task.finished_at, 100.0)

    async def test_run_one_task_passes_runtime_parity_inputs_to_download_runner(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root)
            config.cookies_file = "/run/secrets/cookies.txt"
            config.ytdlp_extra_args = ("--format", "bv*+ba/b")
            store = TaskStore(root / "tasks.sqlite3")
            store.create_task(
                chat_id=1,
                telegram_message_id=10,
                source_url="https://video.example/watch",
            )
            runner = FakeDownloadRunner(
                [
                    DownloadResult(
                        ok=True,
                        title="Movie",
                        filename="movie.mp4",
                        error_text=None,
                    )
                ]
            )
            worker = DownloadWorker(
                config=config,
                store=store,
                download_runner=runner,
                proxy_runtime=FakeProxyRuntime(),
                time_fn=lambda: 100.0,
            )

            await worker.run_one_task()

            self.assertEqual(
                runner.calls[0],
                {
                    "source_url": "https://video.example/watch",
                    "download_dir": str(root / "downloads"),
                    "proxy_url": "http://127.0.0.1:10809",
                    "cookies_file": "/run/secrets/cookies.txt",
                    "extra_args": ("--format", "bv*+ba/b"),
                    "timeout_seconds": 600,
                },
            )

    async def test_run_one_task_retries_transient_failure_on_same_node(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root)
            store = TaskStore(root / "tasks.sqlite3")
            task_id = store.create_task(
                chat_id=1,
                telegram_message_id=10,
                source_url="https://video.example/watch",
            )
            runner = FakeDownloadRunner(
                [
                    DownloadResult(
                        ok=False,
                        title=None,
                        filename=None,
                        error_text="Read timed out",
                    )
                ]
            )
            worker = DownloadWorker(
                config=config,
                store=store,
                download_runner=runner,
                proxy_runtime=None,
                time_fn=lambda: 100.0,
            )

            await worker.run_one_task()

            task = store.get_task(task_id)
            self.assertEqual(task.state, STATE_RETRYING)
            self.assertEqual(task.retry_count, 1)
            self.assertEqual(task.next_retry_at, 110.0)

    async def test_run_one_task_switches_node_and_requeues_retryable_proxy_failure(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root)
            store = TaskStore(root / "tasks.sqlite3")
            task_id = store.create_task(
                chat_id=1,
                telegram_message_id=10,
                source_url="https://video.example/watch",
            )
            runtime = FakeProxyRuntime(fingerprints=["node-a", "node-b"])
            runner = FakeDownloadRunner(
                [
                    DownloadResult(
                        ok=False,
                        title=None,
                        filename=None,
                        error_text="HTTP Error 429: Too Many Requests",
                    )
                ]
            )
            worker = DownloadWorker(
                config=config,
                store=store,
                download_runner=runner,
                proxy_runtime=runtime,
                time_fn=lambda: 100.0,
            )

            await worker.run_one_task()

            task = store.get_task(task_id)
            self.assertEqual(task.state, STATE_RETRYING)
            self.assertEqual(task.failover_attempts, 1)
            self.assertEqual(task.next_retry_at, 100.0)
            self.assertEqual(task.attempted_node_fingerprints, ["node-a"])
            self.assertEqual(runtime.failed_calls, [("node-a", "http error 429", 100.0)])
            self.assertEqual(runtime.switch_calls, ["http error 429"])

    async def test_run_one_task_stops_after_three_distinct_nodes(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root)
            store = TaskStore(root / "tasks.sqlite3")
            task_id = store.create_task(
                chat_id=1,
                telegram_message_id=10,
                source_url="https://video.example/watch",
            )
            store.update_task_state(
                task_id,
                STATE_RETRYING,
                failover_attempts=2,
                attempted_node_fingerprints=["node-a", "node-b", "node-c"],
            )
            runtime = FakeProxyRuntime(generation=3, fingerprints=["node-c", "node-d"])
            runner = FakeDownloadRunner(
                [
                    DownloadResult(
                        ok=False,
                        title=None,
                        filename=None,
                        error_text="HTTP Error 429: Too Many Requests",
                    )
                ]
            )
            worker = DownloadWorker(
                config=config,
                store=store,
                download_runner=runner,
                proxy_runtime=runtime,
                time_fn=lambda: 100.0,
            )

            await worker.run_one_task()

            task = store.get_task(task_id)
            self.assertEqual(task.state, STATE_FAILED)
            self.assertEqual(task.last_error, "HTTP Error 429: Too Many Requests")

    async def test_run_one_task_marks_timeout(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root)
            store = TaskStore(root / "tasks.sqlite3")
            task_id = store.create_task(
                chat_id=1,
                telegram_message_id=10,
                source_url="https://video.example/watch",
            )
            runner = FakeDownloadRunner(
                [
                    DownloadResult(
                        ok=False,
                        title=None,
                        filename=None,
                        error_text="download timed out",
                        timed_out=True,
                    )
                ]
            )
            worker = DownloadWorker(
                config=config,
                store=store,
                download_runner=runner,
                proxy_runtime=None,
                time_fn=lambda: 100.0,
            )

            await worker.run_one_task()

            task = store.get_task(task_id)
            self.assertEqual(task.state, STATE_TIMEOUT)
            self.assertEqual(task.last_error, "download timed out")
            self.assertEqual(task.finished_at, 100.0)
