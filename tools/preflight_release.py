from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


IGNORED_DIRS = {
    ".deps",
    ".git",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "local",
    "output",
    "build",
    "dist",
}

REQUIRED_FILES = {
    ".gitignore",
    "CITATION.cff",
    "LICENSE",
    "README.md",
    "RELEASE_CHECKLIST.md",
    "pyproject.toml",
    "requirements.txt",
    "configs/example_run.ps1",
    "configs/research.template.ps1",
    "docs/method.md",
    "examples/README.md",
    "examples/output/.gitkeep",
    "examples/station_monthly_climate.csv",
    "README.zh-CN.md",
    "src/bdhei/__init__.py",
    "src/bdhei/cli.py",
    "src/bdhei/core.py",
    "src/bdhei/climate.py",
    "src/bdhei/spei.py",
    "src/bdhei/sti.py",
    "src/bdhei/grid_sti.py",
    "src/bdhei/grid_bdhei.py",
    "src/bdhei/netcdf_io.py",
    "src/bdhei/path_safety.py",
    "src/bdhei/station.py",
    "src/bdhei/common.py",
    "configs/netcdf_climate.example.yaml",
    "configs/era5_climate.example.yaml",
    "configs/station_climate.example.yaml",
    "tests/test_climate.py",
    "tests/test_cli.py",
    "tests/test_station.py",
    "tests/tmp/.gitkeep",
    "tools/preflight_release.py",
}

PRIVATE_PATH_PATTERNS = [
    re.compile(r"[A-Za-z]:\\"),
    re.compile(r"\\" + "DATA" + r"\\", re.IGNORECASE),
    re.compile(r"\." + "codex", re.IGNORECASE),
    re.compile(r"\b" + "560" + "38" + r"\b"),
]

GENERATED_SUFFIXES = {".pyc", ".pyo", ".xlsx", ".xls", ".nc", ".nc4"}


def to_posix_relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def is_release_file(root: Path, path: Path) -> bool:
    rel_parts = path.relative_to(root).parts
    if len(rel_parts) >= 2 and rel_parts[0] == "examples" and rel_parts[1] == "output":
        return rel_parts == ("examples", "output", ".gitkeep")
    if any(part in IGNORED_DIRS or part.endswith(".egg-info") for part in rel_parts):
        return False
    if path.suffix.lower() in {".pyc", ".pyo"}:
        return False
    return True


def iter_release_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if path.is_file() and is_release_file(root, path):
            files.append(path)
    return sorted(files, key=lambda item: to_posix_relative(root, item).lower())


def scan_private_paths(root: Path, files: list[Path]) -> list[str]:
    issues: list[str] = []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        rel = to_posix_relative(root, path)
        for lineno, line in enumerate(text.splitlines(), start=1):
            if any(pattern.search(line) for pattern in PRIVATE_PATH_PATTERNS):
                issues.append(f"{rel}:{lineno}: {line.strip()}")
    return issues


def scan_generated_outputs(root: Path, files: list[Path]) -> list[str]:
    issues = []
    for path in files:
        rel = to_posix_relative(root, path)
        if path.suffix.lower() in GENERATED_SUFFIXES:
            issues.append(rel)
        if rel.startswith("examples/output/") and rel != "examples/output/.gitkeep":
            issues.append(rel)
    return sorted(set(issues))


def git_visible_files(root: Path) -> tuple[list[str], str | None]:
    if not (root / ".git").exists():
        return [], None

    command = [
        "git",
        "-c",
        f"safe.directory={root.as_posix()}",
        "ls-files",
        "--cached",
        "--others",
        "--exclude-standard",
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            check=True,
            text=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        return [], str(exc)

    return sorted(line.strip() for line in completed.stdout.splitlines() if line.strip()), None


def main() -> int:
    parser = argparse.ArgumentParser(description="List release files and run public-repository preflight checks.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()

    root = args.root.resolve()
    release_files = iter_release_files(root)
    release_rel = [to_posix_relative(root, path) for path in release_files]

    print("Release file list:")
    for rel in release_rel:
        print(f"  {rel}")
    print(f"\nTotal release files: {len(release_rel)}")

    missing = sorted(REQUIRED_FILES - set(release_rel))
    unexpected_private_paths = scan_private_paths(root, release_files)
    generated_outputs = scan_generated_outputs(root, release_files)
    git_files, git_error = git_visible_files(root)

    failed = False
    if missing:
        failed = True
        print("\nMissing required files:")
        for rel in missing:
            print(f"  {rel}")

    if unexpected_private_paths:
        failed = True
        print("\nPrivate or machine-specific paths found in public files:")
        for issue in unexpected_private_paths:
            print(f"  {issue}")

    if generated_outputs:
        failed = True
        print("\nGenerated or output-like files found in release list:")
        for rel in generated_outputs:
            print(f"  {rel}")

    if git_error:
        failed = True
        print("\nCould not inspect Git file list:")
        print(f"  {git_error}")
    elif git_files:
        missing_from_git = sorted(set(release_rel) - set(git_files))
        extra_in_git = sorted(set(git_files) - set(release_rel))
        if missing_from_git or extra_in_git:
            failed = True
            print("\nGit-visible files differ from preflight release list:")
            if missing_from_git:
                print("  Missing from Git-visible list:")
                for rel in missing_from_git:
                    print(f"    {rel}")
            if extra_in_git:
                print("  Extra in Git-visible list:")
                for rel in extra_in_git:
                    print(f"    {rel}")
        else:
            print("\nGit-visible file list matches preflight release list.")

    if failed:
        print("\nPreflight failed.")
        return 1

    print("\nPreflight passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
