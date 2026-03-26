from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase

from aiohttp.test_utils import TestClient, TestServer

from bot.download_server import create_download_app


class DownloadServerTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmpdir = TemporaryDirectory()
        self.addAsyncCleanup(self._cleanup_tmpdir)
        self.download_dir = Path(self._tmpdir.name) / "downloads"
        self.download_dir.mkdir()

        app = create_download_app(self.download_dir)
        self.server = TestServer(app)
        await self.server.start_server()
        self.addAsyncCleanup(self.server.close)
        self.client = TestClient(self.server)
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)

    async def _cleanup_tmpdir(self) -> None:
        self._tmpdir.cleanup()

    async def test_serves_root_download_file(self):
        file_path = self.download_dir / "movie.mp4"
        file_path.write_bytes(b"video")

        response = await self.client.get("/download/movie.mp4")

        self.assertEqual(response.status, 200)
        self.assertEqual(await response.read(), b"video")

    async def test_serves_nested_download_file(self):
        nested_dir = self.download_dir / "playlist"
        nested_dir.mkdir()
        file_path = nested_dir / "movie.mp4"
        file_path.write_bytes(b"video")

        response = await self.client.get("/download/playlist/movie.mp4")

        self.assertEqual(response.status, 200)
        self.assertEqual(await response.read(), b"video")

    async def test_rejects_directory_traversal(self):
        response = await self.client.get("/download/../../etc/passwd")

        self.assertEqual(response.status, 404)
