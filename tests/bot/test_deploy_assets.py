from pathlib import Path
from unittest import TestCase


class DeployAssetTests(TestCase):
    def test_systemd_unit_exists_with_required_directives(self):
        repo_root = Path(__file__).resolve().parents[2]
        service_path = repo_root / "deploy" / "systemd" / "metube-telegram-bot.service"

        self.assertTrue(service_path.is_file(), f"missing service file: {service_path}")

        content = service_path.read_text(encoding="utf-8")
        self.assertIn("User=root", content)
        self.assertIn("WorkingDirectory=/opt/metube-telegram-proxy-bot", content)
        self.assertIn("EnvironmentFile=/opt/metube-telegram-proxy-bot/.env", content)
        self.assertIn("ExecStart=/usr/bin/python3 -m bot.main", content)
        self.assertIn("Restart=always", content)
        self.assertIn("RestartSec=5", content)
