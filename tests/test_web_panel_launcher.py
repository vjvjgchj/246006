import json
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

from backend.update_manager import sha256_file


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class PanelLauncherTest(unittest.TestCase):
    def test_launcher_prefers_qml_panel_entry_with_web_fallback(self):
        launcher = (PROJECT_ROOT / "NekoLauncher.ps1").read_text(encoding="utf-8")

        self.assertIn("6_run_qml_panel.vbs", launcher)
        self.assertIn("6_run_web_panel.vbs", launcher)
        self.assertLess(launcher.index("6_run_qml_panel.vbs"), launcher.index("6_run_web_panel.vbs"))

    def test_qml_entry_files_are_present_for_main_chain(self):
        for required in (
            "6_run_qml_panel.vbs",
            "run_panel_hidden.pyw",
            "gui_qml_trial.py",
            "keyauth.py",
            "backend/qml_bridge.py",
            "qml/Main.qml",
            "keyauth_login.py",
        ):
            with self.subTest(required=required):
                self.assertTrue((PROJECT_ROOT / required).exists())

    def test_web_entry_is_pure_python_controller(self):
        hidden = (PROJECT_ROOT / "run_web_panel_hidden.pyw").read_text(encoding="utf-8")

        self.assertIn("WebPanelController", hidden)
        self.assertNotIn("PySide6", hidden)
        self.assertNotIn("QmlBridge", hidden)

    def test_web_entry_does_not_delete_qml_main_chain(self):
        hidden = (PROJECT_ROOT / "run_web_panel_hidden.pyw").read_text(encoding="utf-8")

        self.assertNotIn("_cleanup_retired_qml_paths", hidden)
        self.assertNotIn("Removed retired QML", hidden)

    def test_manifest_generator_keeps_qml_by_default(self):
        generator = (PROJECT_ROOT / "tools" / "make_github_update_manifest.py").read_text(encoding="utf-8")

        self.assertIn("WEB_ONLY_DELETE", generator)
        self.assertIn("--web-only-delete", generator)
        self.assertIn('"qml"', generator)
        self.assertIn('"backend/qml_bridge.py"', generator)
        self.assertIn('"6_run_qml_panel.vbs"', generator)
        self.assertIn('"keyauth.py"', generator)
        self.assertIn('"keyauth_login.py"', generator)
        self.assertNotIn("--no-web-only-delete", generator)

    def test_stable_qml_package_contains_keyauth_dependency(self):
        manifest_path = PROJECT_ROOT / "updates" / "stable.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        package_url = manifest["packages"][0]["url"]
        self.assertNotIn("delete", manifest)
        self.assertFalse(package_url.startswith("http"), package_url)

        package_path = (manifest_path.parent / package_url).resolve()
        self.assertTrue(package_path.exists(), package_path)
        with zipfile.ZipFile(package_path, "r") as archive:
            names = set(archive.namelist())

        self.assertIn("keyauth.py", names)
        self.assertIn("keyauth_login.py", names)
        self.assertIn("gui_qml_trial.py", names)

    def test_powershell_launcher_applies_explicit_delete_list(self):
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
