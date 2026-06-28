import json
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.update_manager import apply_manifest_update, sha256_file


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        project = base / "fake_neko"
        release = base / "fake_github_release"
        (project / "runtime").mkdir(parents=True)
        release.mkdir(parents=True)

        current_exe = project / "runtime" / "TRT_ZeroCopy_Pipeline.exe"
        protected_driver = project / "runtime" / "logi_driver.dll"
        current_exe.write_bytes(b"old local runtime exe")
        protected_driver.write_bytes(b"protected driver")

        release_package = release / "neko-core.zip"
        with zipfile.ZipFile(release_package, "w") as archive:
            archive.writestr("runtime/TRT_ZeroCopy_Pipeline.exe", b"new release runtime exe")
            archive.writestr("backend/web_panel_controller.py", "new web controller")
        (project / "qml").mkdir(parents=True)
        (project / "qml" / "Main.qml").write_text("legacy qml", encoding="utf-8")
        (project / "backend").mkdir(parents=True, exist_ok=True)
        (project / "backend" / "qml_bridge.py").write_text("legacy bridge", encoding="utf-8")
        manifest = release / "stable.json"
        manifest.write_text(
            json.dumps(
                {
                    "version": "smoke.1",
                    "notes": "Local package smoke test update",
                    "packages": [
                        {
                            "name": "core",
                            "url": release_package.as_uri(),
                            "sha256": sha256_file(release_package),
                            "size": release_package.stat().st_size,
                        }
                    ],
                    "delete": ["qml", "backend/qml_bridge.py", "6_run_qml_panel.vbs"],
                    "preserve": ["runtime/config.txt", "runtime/logi_driver.dll", "gui_settings.json"],
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        backup_root = apply_manifest_update(project, manifest.as_uri())
        assert current_exe.read_bytes() == b"new release runtime exe"
        assert (project / "backend" / "web_panel_controller.py").read_text(encoding="utf-8") == "new web controller"
        assert not (project / "qml").exists()
        assert not (project / "backend" / "qml_bridge.py").exists()
        assert protected_driver.read_bytes() == b"protected driver"
        assert (backup_root / "runtime" / "TRT_ZeroCopy_Pipeline.exe").read_bytes() == b"old local runtime exe"
        assert (backup_root / "qml" / "Main.qml").read_text(encoding="utf-8") == "legacy qml"

        print("Updater package smoke test passed")
        print(f"manifest: {manifest}")
        print(f"backup:   {backup_root}")
        print(f"project:  {project}")
        shutil.rmtree(project / ".updates" / "staging", ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
