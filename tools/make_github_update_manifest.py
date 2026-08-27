import argparse
import base64
import hashlib
import json
import os
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
]
DEFAULT_SIGNING_KEY = Path.home() / ".neko" / "update_signing_key.json"
SHA256_DIGEST_INFO_PREFIX = bytes.fromhex("3031300D060960864801650304020105000420")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def canonical_manifest_bytes(manifest: dict) -> bytes:
    unsigned = dict(manifest)
    unsigned.pop("signature", None)
    return json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def load_signing_key(path: Path) -> tuple[str, int, int]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        key_id = str(payload["key_id"]).strip()
        modulus = int.from_bytes(base64.b64decode(payload["n"], validate=True), "big")
        private_exponent = int.from_bytes(base64.b64decode(payload["d"], validate=True), "big")
    except Exception as exc:
        raise SystemExit(f"invalid update signing key {path}: {exc}") from exc
    if not key_id or modulus <= 0 or private_exponent <= 0:
        raise SystemExit(f"invalid update signing key values: {path}")
    return key_id, modulus, private_exponent


def sign_manifest(manifest: dict, signing_key_path: Path) -> None:
    key_id, modulus, private_exponent = load_signing_key(signing_key_path)
    key_size = (modulus.bit_length() + 7) // 8
    digest_info = SHA256_DIGEST_INFO_PREFIX + hashlib.sha256(canonical_manifest_bytes(manifest)).digest()
    padding_size = key_size - len(digest_info) - 3
    if padding_size < 8:
        raise SystemExit("update signing key is too small for RS256")
    encoded = b"\x00\x01" + (b"\xff" * padding_size) + b"\x00" + digest_info
    signature = pow(int.from_bytes(encoded, "big"), private_exponent, modulus).to_bytes(key_size, "big")
    manifest["signature"] = {
        "key_id": key_id,
        "algorithm": "RS256",
        "value": base64.b64encode(signature).decode("ascii"),
    }


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
    parser.add_argument("--asset-url", default="", help="Manifest asset URL. Defaults to the GitHub Release URL.")
    parser.add_argument("--notes", default="", help="Release notes shown by the updater.")
    parser.add_argument(
        "--web-only-delete",
        action="store_true",
        help="Add delete[] entries that remove the QML panel chain for an explicit Web-only release.",
    )
    parser.add_argument(
        "--delete",
        action="append",
        default=[],
        help="Project-relative path to remove. Can be repeated.",
    )
    parser.add_argument(
        "--signing-key",
        default=os.environ.get("NEKO_UPDATE_SIGNING_KEY", str(DEFAULT_SIGNING_KEY)),
        help="RSA private key JSON outside the project. Defaults to NEKO_UPDATE_SIGNING_KEY or ~/.neko/update_signing_key.json.",
    )
    parser.add_argument("--output", default=str(PROJECT_ROOT / "updates" / "stable.json"), help="Output manifest path.")
    args = parser.parse_args()

    version = args.version.strip() or args.tag.lstrip("v")
    manifest = {
        "version": version,
        "notes": args.notes,
        "preserve": DEFAULT_PRESERVE,
    }
    delete_paths = list(args.delete or [])
    if args.web_only_delete:
        delete_paths.extend(WEB_ONLY_DELETE)
    if delete_paths:
        manifest["delete"] = list(dict.fromkeys(path.replace("\\", "/") for path in delete_paths))

    if args.package.strip():
        local_package = Path(args.package).resolve()
        if not local_package.exists():
            raise SystemExit(f"package not found: {local_package}")
        asset_name = args.asset_name.strip() or local_package.name
        release_url = args.asset_url.strip() or f"https://github.com/{args.repo}/releases/download/{args.tag}/{asset_name}"
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
        release_url = args.asset_url.strip() or f"https://github.com/{args.repo}/releases/download/{args.tag}/{asset_name}"
        manifest["files"] = [
            {
                "path": args.target_path.replace("\\", "/"),
                "url": release_url,
                "sha256": sha256_file(local_file),
                "size": local_file.stat().st_size,
            }
        ]

    signing_key_path = Path(args.signing_key).expanduser().resolve()
    if not signing_key_path.exists():
        raise SystemExit(f"update signing key not found: {signing_key_path}")
    sign_manifest(manifest, signing_key_path)

    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote manifest: {output_path}")
    print(f"Release asset URL: {release_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
