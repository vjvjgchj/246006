import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from backend.update_manager import (
    DEFAULT_PROTECTED_PATHS,
    UpdateError,
    _ensure_updatable_path,
    apply_manifest_update,
    load_manifest,
    normalize_relative_path,
    sha256_file,
)


class UpdateManagerTest(unittest.TestCase):
    def test_rejects_unsafe_paths(self):
        for value in (
            "../x.exe",
            "/x.exe",
            "C:/x.exe",
            "runtime/../x.exe",
            ".",
            "runtime/logi_driver.dll.",
            "runtime/logi_driver.dll ",
            "runtime/logi_driver.dll:stream",
            "runtime/LOGI_D~1.DLL",
        ):
            with self.subTest(value=value):
                with self.assertRaises(UpdateError):
                    normalize_relative_path(value)

    def test_normalizes_equivalent_relative_paths_before_protection_checks(self):
        self.assertEqual(normalize_relative_path("./runtime//./logi_driver.dll"), "runtime/logi_driver.dll")

    def test_resolved_protected_path_identity_is_checked(self):
        project_root = Path(__file__).resolve().parents[1]
        with self.assertRaises(UpdateError):
            _ensure_updatable_path(
                project_root,
                "runtime/logi_driver.dll",
                DEFAULT_PROTECTED_PATHS,
                (),
            )

    def test_rejects_manifest_versions_that_escape_update_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "stable.json"
            payload = Path(tmp) / "payload.bin"
            payload.write_bytes(b"payload")
            for version in ("../outside", "..\\..\\outside", "C:\\Temp\\stage", "."):
                with self.subTest(version=version):
                    manifest.write_text(
                        json.dumps(
                            {
                                "version": version,
                                "files": [
                                    {
                                        "path": "runtime/payload.bin",
                                        "url": payload.as_uri(),
                                        "sha256": sha256_file(payload),
                                    }
                                ],
                            }
                        ),
                        encoding="utf-8",
                    )
                    with self.assertRaises(UpdateError):
                        load_manifest(manifest.as_uri())

    def test_remote_manifest_requires_a_valid_signature(self):
        raw = json.dumps(
            {
                "version": "unsigned.1",
                "files": [
                    {
                        "path": "runtime/TRT_ZeroCopy_Pipeline.exe",
                        "url": "https://example.invalid/core.exe",
                        "sha256": "0" * 64,
                    }
                ],
            }
        ).encode("utf-8")
        with patch("backend.update_manager._read_url_bytes", return_value=raw):
            with self.assertRaises(UpdateError):
                load_manifest("https://example.invalid/stable.json")

    def test_current_stable_manifest_has_a_valid_remote_signature(self):
        manifest_path = Path(__file__).resolve().parents[1] / "updates" / "stable.json"
        raw = manifest_path.read_bytes()
        manifest_url = "https://gitee.com/w246006/246006/raw/main/updates/stable.json"

        with patch("backend.update_manager._read_url_bytes", return_value=raw):
            loaded = load_manifest(manifest_url)

        self.assertEqual(loaded.version, json.loads(raw.decode("utf-8"))["version"])

    def test_current_stable_manifest_signature_rejects_tampering(self):
        manifest_path = Path(__file__).resolve().parents[1] / "updates" / "stable.json"
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        payload["notes"] = str(payload.get("notes", "")) + " tampered"
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        with patch("backend.update_manager._read_url_bytes", return_value=raw):
            with self.assertRaises(UpdateError):
                load_manifest("https://gitee.com/w246006/246006/raw/main/updates/stable.json")

    def test_applies_update_and_preserves_protected_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            release = Path(tmp) / "release"
            (root / "runtime").mkdir(parents=True)
            release.mkdir()
            (root / "runtime" / "TRT_ZeroCopy_Pipeline.exe").write_bytes(b"old exe")
            (root / "runtime" / "logi_driver.dll").write_bytes(b"driver must stay")
            new_exe = release / "TRT_ZeroCopy_Pipeline.exe"
            new_exe.write_bytes(b"new exe")
            manifest = release / "stable.json"
            manifest.write_text(
                json.dumps(
                    {
                        "version": "test.1",
                        "files": [
                            {
                                "path": "runtime/TRT_ZeroCopy_Pipeline.exe",
                                "url": new_exe.as_uri(),
                                "sha256": sha256_file(new_exe),
                            }
                        ],
                        "preserve": ["runtime/config.txt", "runtime/logi_driver.dll", "gui_settings.json"],
                    }
                ),
                encoding="utf-8",
            )

            backup_root = apply_manifest_update(root, manifest.as_uri())

            self.assertEqual((root / "runtime" / "TRT_ZeroCopy_Pipeline.exe").read_bytes(), b"new exe")
            self.assertEqual((root / "runtime" / "logi_driver.dll").read_bytes(), b"driver must stay")
            self.assertEqual((backup_root / "runtime" / "TRT_ZeroCopy_Pipeline.exe").read_bytes(), b"old exe")

    def test_refuses_to_update_preserved_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            release = Path(tmp) / "release"
            root.mkdir()
            release.mkdir()
            payload = release / "config.txt"
            payload.write_text("bad", encoding="utf-8")
            manifest = release / "stable.json"
            manifest.write_text(
                json.dumps(
                    {
                        "version": "test.2",
                        "files": [
                            {
                                "path": "runtime/config.txt",
                                "url": payload.as_uri(),
                                "sha256": sha256_file(payload),
                            }
                        ],
                        "preserve": ["runtime/config.txt"],
                    }
                ),
                encoding="utf-8",
            )

            loaded = load_manifest(manifest.as_uri())
            self.assertEqual(loaded.version, "test.2")
            with self.assertRaises(UpdateError):
                apply_manifest_update(root, manifest.as_uri())

    def test_applies_package_update_and_preserves_protected_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            release = Path(tmp) / "release"
            (root / "runtime").mkdir(parents=True)
            (root / "backend").mkdir(parents=True)
            release.mkdir()

            (root / "runtime" / "TRT_ZeroCopy_Pipeline.exe").write_bytes(b"old exe")
            (root / "runtime" / "logi_driver.dll").write_bytes(b"driver must stay")
            (root / "backend" / "qml_bridge.py").write_text("old bridge", encoding="utf-8")

            package = release / "neko-core.zip"
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr("runtime/TRT_ZeroCopy_Pipeline.exe", b"new exe")
                archive.writestr("backend/qml_bridge.py", "new bridge")

            manifest = release / "stable.json"
            manifest.write_text(
                json.dumps(
                    {
                        "version": "package.1",
                        "notes": "Package update test",
                        "packages": [
                            {
                                "name": "core",
                                "url": package.as_uri(),
                                "sha256": sha256_file(package),
                                "size": package.stat().st_size,
                            }
                        ],
                        "preserve": ["runtime/config.txt", "runtime/logi_driver.dll", "gui_settings.json"],
                    }
                ),
                encoding="utf-8",
            )

            backup_root = apply_manifest_update(root, manifest.as_uri())

            self.assertEqual((root / "runtime" / "TRT_ZeroCopy_Pipeline.exe").read_bytes(), b"new exe")
            self.assertEqual((root / "backend" / "qml_bridge.py").read_text(encoding="utf-8"), "new bridge")
            self.assertEqual((root / "runtime" / "logi_driver.dll").read_bytes(), b"driver must stay")
            self.assertEqual((backup_root / "runtime" / "TRT_ZeroCopy_Pipeline.exe").read_bytes(), b"old exe")
            self.assertEqual((backup_root / "backend" / "qml_bridge.py").read_text(encoding="utf-8"), "old bridge")

    def test_applies_delete_manifest_entries_with_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            release = Path(tmp) / "release"
            (root / "runtime").mkdir(parents=True)
            (root / "backend").mkdir(parents=True)
            (root / "qml").mkdir(parents=True)
            release.mkdir()

            (root / "qml" / "Main.qml").write_text("legacy qml", encoding="utf-8")
            (root / "backend" / "qml_bridge.py").write_text("legacy bridge", encoding="utf-8")
            (root / "6_run_qml_panel.vbs").write_text("legacy launcher", encoding="utf-8")
            (root / "backend" / "web_panel_controller.py").write_text("retired web controller", encoding="utf-8")
            (root / "backend" / "mobile_control_server.py").write_text("retired mobile server", encoding="utf-8")
            (root / "6_run_web_panel.vbs").write_text("retired web launcher", encoding="utf-8")
            (root / "run_web_panel_hidden.pyw").write_text("retired hidden web launcher", encoding="utf-8")
            (root / "runtime" / "logi_driver.dll").write_bytes(b"driver must stay")

            package = release / "qml-only.zip"
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr("qml/Main.qml", "new qml")
                archive.writestr("backend/qml_bridge.py", "new bridge")
                archive.writestr("6_run_qml_panel.vbs", "new qml launcher")

            manifest = release / "stable.json"
            manifest.write_text(
                json.dumps(
                    {
                        "version": "qml-only.1",
                        "packages": [
                            {
                                "name": "qml-only",
                                "url": package.as_uri(),
                                "sha256": sha256_file(package),
                            }
                        ],
                        "delete": [
                            "backend/web_panel_controller.py",
                            "backend/mobile_control_server.py",
                            "6_run_web_panel.vbs",
                            "run_web_panel_hidden.pyw",
                        ],
                        "preserve": ["runtime/config.txt", "runtime/logi_driver.dll", "gui_settings.json"],
                    }
                ),
                encoding="utf-8",
            )

            backup_root = apply_manifest_update(root, manifest.as_uri())

            self.assertEqual((root / "qml" / "Main.qml").read_text(encoding="utf-8"), "new qml")
            self.assertEqual((root / "backend" / "qml_bridge.py").read_text(encoding="utf-8"), "new bridge")
            self.assertEqual((root / "6_run_qml_panel.vbs").read_text(encoding="utf-8"), "new qml launcher")
            self.assertFalse((root / "backend" / "web_panel_controller.py").exists())
            self.assertFalse((root / "backend" / "mobile_control_server.py").exists())
            self.assertFalse((root / "6_run_web_panel.vbs").exists())
            self.assertFalse((root / "run_web_panel_hidden.pyw").exists())
            self.assertEqual((root / "runtime" / "logi_driver.dll").read_bytes(), b"driver must stay")
            self.assertEqual(
                (backup_root / "backend" / "web_panel_controller.py").read_text(encoding="utf-8"),
                "retired web controller",
            )

    def test_refuses_delete_of_protected_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            release = Path(tmp) / "release"
            (root / "runtime").mkdir(parents=True)
            release.mkdir()
            (root / "runtime" / "logi_driver.dll").write_bytes(b"driver must stay")

            package = release / "cleanup.zip"
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr("qml/Main.qml", "new qml")

            manifest = release / "stable.json"
            manifest.write_text(
                json.dumps(
                    {
                        "version": "cleanup.2",
                        "packages": [
                            {
                                "name": "cleanup",
                                "url": package.as_uri(),
                                "sha256": sha256_file(package),
                            }
                        ],
                        "delete": ["runtime/logi_driver.dll"],
                        "preserve": ["runtime/logi_driver.dll"],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaises(UpdateError):
                apply_manifest_update(root, manifest.as_uri())
            self.assertEqual((root / "runtime" / "logi_driver.dll").read_bytes(), b"driver must stay")

    def test_rolls_back_deleted_paths_when_validation_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            release = Path(tmp) / "release"
            (root / "backend").mkdir(parents=True)
            release.mkdir()
            (root / "backend" / "web_panel_controller.py").write_text("retired web controller", encoding="utf-8")
            (root / "6_run_web_panel.vbs").write_text("retired web launcher", encoding="utf-8")

            package = release / "qml-only.zip"
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr("qml/Main.qml", "new qml")

            manifest = release / "stable.json"
            manifest.write_text(
                json.dumps(
                    {
                        "version": "qml-only.rollback",
                        "packages": [
                            {
                                "name": "qml-only",
                                "url": package.as_uri(),
                                "sha256": sha256_file(package),
                            }
                        ],
                        "delete": ["backend/web_panel_controller.py", "6_run_web_panel.vbs"],
                    }
                ),
                encoding="utf-8",
            )

            def fail_validation():
                raise RuntimeError("validation failed")

            with self.assertRaises(RuntimeError):
                manifest_obj = load_manifest(manifest.as_uri())
                from backend.update_manager import apply_staged_update, stage_update

                stage = stage_update(root, manifest.as_uri(), manifest_obj)
                apply_staged_update(root, manifest_obj, stage, validate=fail_validation)

            self.assertEqual(
                (root / "backend" / "web_panel_controller.py").read_text(encoding="utf-8"),
                "retired web controller",
            )
            self.assertEqual((root / "6_run_web_panel.vbs").read_text(encoding="utf-8"), "retired web launcher")

    def test_refuses_package_with_protected_member(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            release = Path(tmp) / "release"
            (root / "runtime").mkdir(parents=True)
            release.mkdir()
            (root / "runtime" / "logi_driver.dll").write_bytes(b"driver must stay")

            package = release / "bad-package.zip"
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr("runtime/logi_driver.dll", b"bad driver")

            manifest = release / "stable.json"
            manifest.write_text(
                json.dumps(
                    {
                        "version": "package.2",
                        "packages": [
                            {
                                "name": "bad",
                                "url": package.as_uri(),
                                "sha256": sha256_file(package),
                            }
                        ],
                        "preserve": ["runtime/logi_driver.dll"],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaises(UpdateError):
                apply_manifest_update(root, manifest.as_uri())
            self.assertEqual((root / "runtime" / "logi_driver.dll").read_bytes(), b"driver must stay")

    def test_refuses_package_path_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            release = Path(tmp) / "release"
            root.mkdir()
            release.mkdir()

            package = release / "bad-path.zip"
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr("../evil.txt", "bad")

            manifest = release / "stable.json"
            manifest.write_text(
                json.dumps(
                    {
                        "version": "package.3",
                        "packages": [
                            {
                                "name": "bad-path",
                                "url": package.as_uri(),
                                "sha256": sha256_file(package),
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaises(UpdateError):
                apply_manifest_update(root, manifest.as_uri())
            self.assertFalse((Path(tmp) / "evil.txt").exists())


if __name__ == "__main__":
    unittest.main()
