import json
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

from backend.update_manager import sha256_file


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class WebPanelLauncherTest(unittest.TestCase):
    def test_launcher_prefers_web_panel_entry(self):
        launcher = (PROJECT_ROOT / "NekoLauncher.ps1").read_text(encoding="utf-8")

        self.assertIn("6_run_web_panel.vbs", launcher)
        self.assertNotIn("6_run_qml_panel.vbs", launcher)

    def test_retired_qml_entry_files_are_removed(self):
        for retired in (
            "6_run_qml_panel.vbs",
            "run_panel_hidden.pyw",
            "gui_qml_trial.py",
            "backend/qml_bridge.py",
            "qml/Main.qml",
            "keyauth_login.py",
        ):
            with self.subTest(retired=retired):
                self.assertFalse((PROJECT_ROOT / retired).exists())

    def test_web_entry_is_pure_python_controller(self):
        hidden = (PROJECT_ROOT / "run_web_panel_hidden.pyw").read_text(encoding="utf-8")

        self.assertIn("WebPanelController", hidden)
        self.assertNotIn("PySide6", hidden)
        self.assertNotIn("QmlBridge", hidden)

    def test_web_entry_cleans_retired_qml_paths(self):
        hidden = (PROJECT_ROOT / "run_web_panel_hidden.pyw").read_text(encoding="utf-8")

        self.assertIn("_cleanup_retired_qml_paths", hidden)
        self.assertIn('"qml"', hidden)
        self.assertIn('"backend", "qml_bridge.py"', hidden)

    def test_manifest_generator_adds_web_only_delete_list(self):
        generator = (PROJECT_ROOT / "tools" / "make_github_update_manifest.py").read_text(encoding="utf-8")

        self.assertIn("DEFAULT_DELETE", generator)
        self.assertIn('"qml"', generator)
        self.assertIn('"backend/qml_bridge.py"', generator)
        self.assertIn('"6_run_qml_panel.vbs"', generator)
        self.assertIn('"keyauth_login.py"', generator)

    def test_powershell_launcher_applies_web_only_delete_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            install = tmp_path / "install"
            release = tmp_path / "release"
            install.mkdir()
            release.mkdir()
            (install / "runtime").mkdir()
            (install / "backend").mkdir()
            (install / "qml").mkdir()
            (install / "runtime" / "logi_driver.dll").write_bytes(b"driver")
            (install / "backend" / "qml_bridge.py").write_text("legacy", encoding="utf-8")
            (install / "qml" / "Main.qml").write_text("legacy", encoding="utf-8")
            (install / "6_run_qml_panel.vbs").write_text("legacy", encoding="utf-8")

            launcher = install / "NekoLauncher.ps1"
            shutil.copy2(PROJECT_ROOT / "NekoLauncher.ps1", launcher)

            package = release / "web.zip"
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr("6_run_web_panel.vbs", "web")

            manifest = release / "stable.json"
            manifest.write_text(
                json.dumps(
                    {
                        "version": "launcher-delete.1",
                        "packages": [
                            {
                                "name": "web",
                                "url": package.as_uri(),
                                "sha256": sha256_file(package),
                                "size": package.stat().st_size,
                            }
                        ],
                        "delete": ["qml", "backend/qml_bridge.py", "6_run_qml_panel.vbs"],
                        "preserve": ["runtime/logi_driver.dll"],
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(launcher),
                    "-ManifestUrl",
                    str(manifest),
                    "-InstallDir",
                    str(install),
                    "-NoLaunch",
                    "-Force",
                ],
                cwd=str(PROJECT_ROOT),
                text=True,
                capture_output=True,
                timeout=60,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse((install / "qml").exists())
            self.assertFalse((install / "backend" / "qml_bridge.py").exists())
            self.assertFalse((install / "6_run_qml_panel.vbs").exists())
            self.assertEqual((install / "6_run_web_panel.vbs").read_text(encoding="utf-8"), "web")
            self.assertEqual((install / "runtime" / "logi_driver.dll").read_bytes(), b"driver")


if __name__ == "__main__":
    unittest.main()
