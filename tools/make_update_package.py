import argparse
import hashlib
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EXCLUDES = [
    ".updates",
    "dist",
    "__pycache__",
    "release_assets",
    "runtime/config.txt",
    "runtime/logi_driver.dll",
    "gui_settings.json",
    "updates/stable.json",
    "qml",
    "backend/qml_bridge.py",
    "6_run_qml_panel.vbs",
    "run_panel_hidden.pyw",
    "gui_qml_trial.py",
    "keyauth_login.py",
]


def normalize_relative_path(value: str) -> str:
    path = str(value or "").replace("\\", "/").strip().strip("/")
    if not path:
        raise ValueError("empty relative path")
    if path.startswith("../") or "/../" in f"/{path}/":
        raise ValueError(f"unsafe relative path: {value}")
    if ":" in Path(path).parts[0]:
        raise ValueError(f"absolute path is not allowed: {value}")
    return path


def is_same_or_child(path: str, parent: str) -> bool:
    parent = parent.rstrip("/")
    return path == parent or path.startswith(parent + "/")


def should_exclude(rel_path: str, excludes: list[str]) -> bool:
    rel_lower = normalize_relative_path(rel_path).lower()
    parts = set(rel_lower.split("/"))
    if "__pycache__" in parts or rel_lower.endswith(".pyc"):
        return True
    for item in excludes:
        excluded = normalize_relative_path(item).lower()
        if is_same_or_child(rel_lower, excluded):
            return True
        if "/" not in excluded and excluded in parts:
            return True
    return False


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def collect_files(includes: list[str], excludes: list[str], output_path: Path) -> list[tuple[Path, str]]:
    files: list[tuple[Path, str]] = []
    output_resolved = output_path.resolve()
    for include in includes:
        rel_include = normalize_relative_path(include)
        source = (PROJECT_ROOT / rel_include).resolve()
        if not source.exists():
            raise FileNotFoundError(f"include path not found: {rel_include}")
        if source.is_file():
            candidates = [source]
        else:
            candidates = sorted(path for path in source.rglob("*") if path.is_file())
        for candidate in candidates:
            if candidate.resolve() == output_resolved:
                continue
            rel_path = str(candidate.relative_to(PROJECT_ROOT)).replace("\\", "/")
            if should_exclude(rel_path, excludes):
                continue
            files.append((candidate, rel_path))
    deduped = {}
    for path, rel_path in files:
        deduped[rel_path] = path
    return [(path, rel_path) for rel_path, path in sorted(deduped.items())]


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a Neko zip update package.")
    parser.add_argument("--output", required=True, help="Output zip path.")
    parser.add_argument(
        "--include",
        action="append",
        required=True,
        help="Project-relative file or directory to include. Can be repeated.",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="Project-relative file or directory to exclude. Can be repeated.",
    )
    args = parser.parse_args()

    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    excludes = DEFAULT_EXCLUDES + list(args.exclude or [])
    files = collect_files(args.include, excludes, output_path)
    if not files:
        raise SystemExit("no files selected for update package")

    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for source, rel_path in files:
            archive.write(source, rel_path)

    print(f"Wrote package: {output_path}")
    print(f"Files: {len(files)}")
    print(f"Size: {output_path.stat().st_size}")
    print(f"SHA256: {sha256_file(output_path)}")
    for _, rel_path in files:
        print(f"  {rel_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
