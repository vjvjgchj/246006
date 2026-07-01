import argparse
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPO = "vjvjgchj/246006"
DEFAULT_TARGET_PATH = "runtime/TRT_ZeroCopy_Pipeline.exe"
DEFAULT_PRESERVE = [
    "runtime/config.txt",
    "runtime/logi_driver.dll",
    "gui_settings.json",
]
WEB_ONLY_DELETE = [
    "qml",
    "backend/qml_bridge.py",
    "6_run_qml_panel.vbs",
    "run_panel_hidden.pyw",
    "gui_qml_trial.py",
    "keyauth.py",
    "keyauth_login.py",
]


def sha256_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a GitHub Releases update manifest for Neko.")
    parser.add_argument("--repo", default=DEFAULT_REPO, help="GitHub repo in owner/name form.")
    parser.add_argument("--tag", required=True, help="GitHub Release tag, for example v2026.06.27.1.")
    parser.add_argument("--version", default="", help="Client-facing version. Defaults to tag without leading v.")
    parser.add_argument("--file", default=str(PROJECT_ROOT / DEFAULT_TARGET_PATH), help="Local file to publish in legacy files[] mode.")
    parser.add_argument("--target-path", default=DEFAULT_TARGET_PATH, help="Destination path inside the Neko package.")
    parser.add_argument("--package", default="", help="Local zip package to publish in packages[] mode.")
    parser.add_argument("--package-name", default="core", help="Package name used by packages[] mode.")
    parser.add_argument("--asset-name", default="", help="Release asset name. Defaults to local file name.")
    parser.add_argument("--notes", default="", help="Release notes shown by the updater.")
    parser.add_argument(
        "--web-only-delete",
        action="store_true",
        help="Add delete[] entries that remove the QML panel chain for an explicit Web-only release.",
    )
    parser.add_argument("--output", default=str(PROJECT_ROOT / "updates" / "stable.json"), help="Output manifest path.")
    args = parser.parse_args()

    version = args.version.strip() or args.tag.lstrip("v")
    manifest = {
        "version": version,
        "notes": args.notes,
        "preserve": DEFAULT_PRESERVE,
    }
    if args.web_only_delete:
        manifest["delete"] = WEB_ONLY_DELETE

    if args.package.strip():
        local_package = Path(args.package).resolve()
        if not local_package.exists():
            raise SystemExit(f"package not found: {local_package}")
        asset_name = args.asset_name.strip() or local_package.name
        release_url = f"https://github.com/{args.repo}/releases/download/{args.tag}/{asset_name}"
        manifest["packages"] = [
            {
                "name": args.package_name.strip() or "core",
                "url": release_url,
                "sha256": sha256_file(local_package),
                "size": local_package.stat().st_size,
            }
        ]
    else:
        local_file = Path(args.file).resolve()
        if not local_file.exists():
            raise SystemExit(f"file not found: {local_file}")
        asset_name = args.asset_name.strip() or local_file.name
        release_url = f"https://github.com/{args.repo}/releases/download/{args.tag}/{asset_name}"
        manifest["files"] = [
            {
                "path": args.target_path.replace("\\", "/"),
                "url": release_url,
                "sha256": sha256_file(local_file),
                "size": local_file.stat().st_size,
            }
        ]

    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote manifest: {output_path}")
    print(f"Release asset URL: {release_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
