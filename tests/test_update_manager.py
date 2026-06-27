import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from backend.update_manager import (
    UpdateError,
    apply_manifest_update,
    load_manifest,
    normalize_relative_path,
    sha256_file,
)


class UpdateManagerTest(unittest.TestCase):
    def test_rejects_unsafe_paths(self):
        for value in ("../x.exe", "/x.exe", "C:/x.exe", "runtime/../x.exe"):
            with self.subTest(value=value):
                with self.assertRaises(UpdateError):
                    normalize_relative_path(value)

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
