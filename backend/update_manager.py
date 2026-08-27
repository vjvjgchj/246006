import base64
import hashlib
import hmac
import json
import os
import re
import shutil
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, List, Optional
from urllib.parse import urljoin, urlparse


DEFAULT_PROTECTED_PATHS = {
    ".updates",
    "runtime/config.txt",
    "runtime/logi_driver.dll",
    "gui_settings.json",
}

UPDATE_PUBLIC_KEY_ID = "neko-update-2026-08-27"
UPDATE_PUBLIC_KEY_MODULUS = (
    "ulf+JmecuyfFay9/OYn9U4sNY+vndzW9dEPhRSxjCgkoPRdri8LKyQzyFNUYeKlmXim9jEwTjrfuszRcQThHj7Mf4csMXrUCHd/L4fawM6mHt97picczt5eAQr7GeqoGbJyJKbnlfa2HIqDXjsIHrsl8tzhwqS7Ii2XHbz7pRQgY6Ggz+zIGmoBgBut4WS481vwrTxE2fx1S79A0AmTNJjrhXjP3P61A+bPhmGSJGqodJMEJ0ZetMc9a80bHDpyQWfzuxmTmN8Kvc14WLZftmelgChm7hkwsslmCvLKUo9oQ7Y/CXb0f2mgY8SseroQWnOYlWfnIX3uo5qYA5OcEClVWNjZnA2ubM97YbQr2m8gsfM5KUDGv2tG0SczD27exzv3UyzI5uAiHnaXGM6cvjPM6HL3MP5sYAIMxsvFP0g/W2Fv9/OT5wEAwe7xYLXsgSJ4AXA9lfmrLmoUg4SvlxKh2mRjhpfMCGdi4CCdCqs9VKr4ZeF1XwiU3BDhsffvx"
)
UPDATE_PUBLIC_KEY_EXPONENT = 65537
SHA256_DIGEST_INFO_PREFIX = bytes.fromhex("3031300D060960864801650304020105000420")
WINDOWS_SHORT_NAME_RE = re.compile(r"^[^~]{1,6}~\d+(?:\.[^.]{0,3})?$")
SAFE_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class UpdateError(RuntimeError):
    pass


@dataclass(frozen=True)
class UpdateFile:
    path: str
    url: str
    sha256: str
    size: Optional[int] = None


@dataclass(frozen=True)
class UpdatePackage:
    name: str
    url: str
    sha256: str
    size: Optional[int] = None


@dataclass(frozen=True)
class UpdateManifest:
    version: str
    notes: str
    files: List[UpdateFile]
    packages: List[UpdatePackage]
    preserve: List[str]
    delete: List[str]


def normalize_relative_path(value: str) -> str:
    path = str(value or "").replace("\\", "/")
    if path != path.strip() or not path:
        raise UpdateError("empty update path")
    if path.startswith("/"):
        raise UpdateError(f"unsafe update path: {value}")

    parts = []
    for part in path.split("/"):
        if part in ("", "."):
            continue
        if (
            part == ".."
            or part.endswith((".", " "))
            or ":" in part
            or WINDOWS_SHORT_NAME_RE.fullmatch(part)
        ):
            raise UpdateError(f"unsafe update path: {value}")
        parts.append(part)
    if not parts:
        raise UpdateError(f"unsafe update path: {value}")
    return "/".join(parts)


def normalize_manifest_version(value: object) -> str:
    version = str(value or "").strip() or "unknown"
    if not SAFE_VERSION_RE.fullmatch(version):
        raise UpdateError(f"unsafe update version: {value}")
    return version


def safe_project_path(project_root: Path, relative_path: str) -> Path:
    root = project_root.resolve()
    candidate = (root / normalize_relative_path(relative_path)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise UpdateError(f"update path escapes project root: {relative_path}") from exc
    return candidate


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _read_url_bytes(url: str, timeout: int = 30) -> bytes:
    parsed = urlparse(url)
    if parsed.scheme in ("", "file"):
        path = Path(urllib.request.url2pathname(parsed.path) if parsed.scheme == "file" else url)
        return path.read_bytes()
    if parsed.scheme not in ("http", "https"):
        raise UpdateError(f"unsupported update URL scheme: {parsed.scheme}")
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.read()


def _canonical_manifest_bytes(payload: dict) -> bytes:
    unsigned = dict(payload)
    unsigned.pop("signature", None)
    return json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _verify_remote_manifest_signature(payload: dict) -> None:
    signature = payload.get("signature")
    if not isinstance(signature, dict):
        raise UpdateError("remote update manifest is unsigned")
    if signature.get("key_id") != UPDATE_PUBLIC_KEY_ID or signature.get("algorithm") != "RS256":
        raise UpdateError("remote update manifest signature metadata is invalid")
    try:
        raw_signature = base64.b64decode(str(signature["value"]), validate=True)
    except Exception as exc:
        raise UpdateError("remote update manifest signature is invalid") from exc

    modulus = int.from_bytes(base64.b64decode(UPDATE_PUBLIC_KEY_MODULUS, validate=True), "big")
    key_size = (modulus.bit_length() + 7) // 8
    if len(raw_signature) != key_size:
        raise UpdateError("remote update manifest signature has an invalid length")
    digest_info = SHA256_DIGEST_INFO_PREFIX + hashlib.sha256(_canonical_manifest_bytes(payload)).digest()
    padding_size = key_size - len(digest_info) - 3
    expected = b"\x00\x01" + (b"\xff" * padding_size) + b"\x00" + digest_info
    actual = pow(int.from_bytes(raw_signature, "big"), UPDATE_PUBLIC_KEY_EXPONENT, modulus).to_bytes(key_size, "big")
    if not hmac.compare_digest(actual, expected):
        raise UpdateError("remote update manifest signature verification failed")


def _download_url_to_path(url: str, target: Path, timeout: int = 30) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    parsed = urlparse(url)
    if parsed.scheme in ("", "file"):
        path = Path(urllib.request.url2pathname(parsed.path) if parsed.scheme == "file" else url)
        shutil.copy2(path, target)
        return
    if parsed.scheme not in ("http", "https"):
        raise UpdateError(f"unsupported update URL scheme: {parsed.scheme}")
    with urllib.request.urlopen(url, timeout=timeout) as response, target.open("wb") as handle:
        shutil.copyfileobj(response, handle, length=1024 * 1024)


def _is_same_or_child(path: str, parent: str) -> bool:
    parent = parent.rstrip("/")
    return path == parent or path.startswith(parent + "/")


def _ensure_updatable_path(
    project_root: Path,
    relative_path: str,
    protected_paths: Iterable[str],
    preserve_paths: Iterable[str],
) -> str:
    rel_path = normalize_relative_path(relative_path)
    rel_lower = rel_path.lower()
    for blocked in set(protected_paths) | set(preserve_paths):
        blocked_lower = normalize_relative_path(blocked).lower()
        if _is_same_or_child(rel_lower, blocked_lower):
            raise UpdateError(f"refusing to update protected file: {rel_path}")
    safe_project_path(project_root, rel_path)
    return rel_path


def _ensure_deletable_path(
    project_root: Path,
    relative_path: str,
    protected_paths: Iterable[str],
    preserve_paths: Iterable[str],
) -> str:
    rel_path = normalize_relative_path(relative_path)
    rel_lower = rel_path.lower()
    for blocked in set(protected_paths) | set(preserve_paths):
        blocked_lower = normalize_relative_path(blocked).lower()
        if _is_same_or_child(rel_lower, blocked_lower) or _is_same_or_child(blocked_lower, rel_lower):
            raise UpdateError(f"refusing to delete protected file: {rel_path}")
    safe_project_path(project_root, rel_path)
    return rel_path


def _safe_package_filename(name: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", str(name or "").strip()).strip("._-")
    return f"{safe or 'package'}.zip"


def _staged_update_paths(stage_root: Path) -> List[str]:
    if not stage_root.exists():
        return []
    return sorted(
        str(path.relative_to(stage_root)).replace("\\", "/")
        for path in stage_root.rglob("*")
        if path.is_file()
    )


def _extract_package_to_stage(
    project_root: Path,
    stage_root: Path,
    package_path: Path,
    package_name: str,
    protected_paths: Iterable[str],
    preserve_paths: Iterable[str],
) -> None:
    try:
        archive = zipfile.ZipFile(package_path)
    except zipfile.BadZipFile as exc:
        raise UpdateError(f"invalid update package zip: {package_name}") from exc

    with archive:
        for entry in archive.infolist():
            if entry.is_dir():
                continue
            rel_path = _ensure_updatable_path(project_root, entry.filename, protected_paths, preserve_paths)
            target = safe_project_path(stage_root, rel_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(entry, "r") as source, target.open("wb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)


def load_manifest(manifest_url: str) -> UpdateManifest:
    raw = _read_url_bytes(manifest_url)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise UpdateError(f"invalid update manifest: {exc}") from exc
    if not isinstance(payload, dict):
        raise UpdateError("invalid update manifest: expected an object")

    if urlparse(manifest_url).scheme.lower() in ("http", "https"):
        _verify_remote_manifest_signature(payload)

    files = []
    for entry in payload.get("files", []):
        try:
            rel_path = normalize_relative_path(entry["path"])
            file_url = str(entry["url"]).strip()
            file_hash = str(entry["sha256"]).strip().upper()
        except KeyError as exc:
            raise UpdateError(f"manifest file entry missing {exc}") from exc
        if len(file_hash) != 64:
            raise UpdateError(f"invalid sha256 for {rel_path}")
        files.append(UpdateFile(path=rel_path, url=file_url, sha256=file_hash, size=entry.get("size")))

    packages = []
    for entry in payload.get("packages", []):
        try:
            package_name = str(entry["name"]).strip()
            package_url = str(entry["url"]).strip()
            package_hash = str(entry["sha256"]).strip().upper()
        except KeyError as exc:
            raise UpdateError(f"manifest package entry missing {exc}") from exc
        if not package_name:
            raise UpdateError("manifest package entry has empty name")
        if len(package_hash) != 64:
            raise UpdateError(f"invalid sha256 for package {package_name}")
        packages.append(UpdatePackage(name=package_name, url=package_url, sha256=package_hash, size=entry.get("size")))

    if not files and not packages:
        raise UpdateError("manifest has no update files or packages")

    return UpdateManifest(
        version=normalize_manifest_version(payload.get("version")),
        notes=str(payload.get("notes", "")).strip(),
        files=files,
        packages=packages,
        preserve=[normalize_relative_path(item) for item in payload.get("preserve", [])],
        delete=[normalize_relative_path(item) for item in (payload.get("delete", []) or payload.get("remove", []))],
    )


def _resolve_file_url(manifest_url: str, file_url: str) -> str:
    parsed = urlparse(file_url)
    if parsed.scheme:
        return file_url
    return urljoin(manifest_url, file_url)


def stage_update(
    project_root: Path,
    manifest_url: str,
    manifest: UpdateManifest,
    protected_paths: Iterable[str] = DEFAULT_PROTECTED_PATHS,
) -> Path:
    normalized_protected = {normalize_relative_path(item).lower() for item in protected_paths}
    normalized_preserve = {normalize_relative_path(item).lower() for item in manifest.preserve}
    for update_file in manifest.files:
        _ensure_updatable_path(project_root, update_file.path, normalized_protected, normalized_preserve)

    stage_root = project_root / ".updates" / "staging" / manifest.version
    if stage_root.exists():
        shutil.rmtree(stage_root)
    stage_root.mkdir(parents=True, exist_ok=True)

    for update_file in manifest.files:
        rel_path = _ensure_updatable_path(project_root, update_file.path, normalized_protected, normalized_preserve)
        target = safe_project_path(stage_root, rel_path)
        resolved_url = _resolve_file_url(manifest_url, update_file.url)
        _download_url_to_path(resolved_url, target)
        actual_hash = sha256_file(target)
        if actual_hash != update_file.sha256:
            raise UpdateError(
                f"sha256 mismatch for {update_file.path}: expected {update_file.sha256}, got {actual_hash}"
            )
        if update_file.size is not None and target.stat().st_size != int(update_file.size):
            raise UpdateError(f"size mismatch for {update_file.path}")

    if manifest.packages:
        download_root = project_root / ".updates" / "downloads" / manifest.version
        if download_root.exists():
            shutil.rmtree(download_root)
        download_root.mkdir(parents=True, exist_ok=True)

        for update_package in manifest.packages:
            package_path = download_root / _safe_package_filename(update_package.name)
            resolved_url = _resolve_file_url(manifest_url, update_package.url)
            _download_url_to_path(resolved_url, package_path)
            actual_hash = sha256_file(package_path)
            if actual_hash != update_package.sha256:
                raise UpdateError(
                    f"sha256 mismatch for package {update_package.name}: "
                    f"expected {update_package.sha256}, got {actual_hash}"
                )
            if update_package.size is not None and package_path.stat().st_size != int(update_package.size):
                raise UpdateError(f"size mismatch for package {update_package.name}")
            _extract_package_to_stage(
                project_root,
                stage_root,
                package_path,
                update_package.name,
                normalized_protected,
                normalized_preserve,
            )

    if not _staged_update_paths(stage_root):
        raise UpdateError("manifest staged no update files")

    return stage_root


def apply_staged_update(
    project_root: Path,
    manifest: UpdateManifest,
    stage_root: Path,
    validate: Optional[Callable[[], None]] = None,
) -> Path:
    backup_root = project_root / ".updates" / "backups" / f"{manifest.version}_{time.strftime('%Y%m%d_%H%M%S')}"
    backup_root.mkdir(parents=True, exist_ok=True)

    replaced_files = []
    deleted_paths = []
    try:
        normalized_protected = {normalize_relative_path(item).lower() for item in DEFAULT_PROTECTED_PATHS}
        normalized_preserve = {normalize_relative_path(item).lower() for item in manifest.preserve}
        for rel_path in _staged_update_paths(stage_root):
            rel_path = _ensure_updatable_path(project_root, rel_path, normalized_protected, normalized_preserve)
            source = safe_project_path(stage_root, rel_path)
            target = safe_project_path(project_root, rel_path)
            backup = safe_project_path(backup_root, rel_path)

            if not source.exists():
                raise UpdateError(f"staged file missing: {rel_path}")
            backup.parent.mkdir(parents=True, exist_ok=True)
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                shutil.copy2(target, backup)
            os.replace(source, target)
            replaced_files.append(rel_path)

        for rel_path in manifest.delete:
            rel_path = _ensure_deletable_path(project_root, rel_path, normalized_protected, normalized_preserve)
            target = safe_project_path(project_root, rel_path)
            backup = safe_project_path(backup_root, rel_path)
            if not target.exists():
                continue

            if target.is_dir():
                backup.parent.mkdir(parents=True, exist_ok=True)
                if backup.exists():
                    shutil.rmtree(backup)
                shutil.copytree(target, backup)
                shutil.rmtree(target)
            else:
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, backup)
                target.unlink()
            deleted_paths.append(rel_path)

        if validate:
            validate()

        version_file = project_root / ".updates" / "current_version.txt"
        version_file.parent.mkdir(parents=True, exist_ok=True)
        version_file.write_text(manifest.version, encoding="utf-8")
        return backup_root
    except Exception:
        rollback_update(project_root, backup_root, replaced_files)
        rollback_update(project_root, backup_root, deleted_paths)
        raise


def rollback_update(project_root: Path, backup_root: Path, files: Optional[Iterable[str]] = None) -> None:
    if files is None:
        files = [
            str(path.relative_to(backup_root)).replace("\\", "/")
            for path in backup_root.rglob("*")
            if path.is_file()
        ]
    for rel_path in files:
        backup = safe_project_path(backup_root, rel_path)
        target = safe_project_path(project_root, rel_path)
        if backup.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(backup, target)
        elif target.exists():
            target.unlink()


def apply_manifest_update(
    project_root: Path,
    manifest_url: str,
    validate: Optional[Callable[[], None]] = None,
) -> Path:
    manifest = load_manifest(manifest_url)
    stage_root = stage_update(project_root, manifest_url, manifest)
    return apply_staged_update(project_root, manifest, stage_root, validate=validate)
