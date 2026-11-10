"""Path validation and privacy-safe metadata helpers.

The public tool treats all inputs as read-only.  Outputs must be distinct from
every input and from one another, and existing outputs are rejected unless the
caller explicitly opts in to overwriting them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping


def validate_io_paths(
    *,
    inputs: Mapping[str, str | Path],
    outputs: Mapping[str, str | Path | None],
    overwrite: bool = False,
) -> tuple[dict[str, Path], dict[str, Path]]:
    """Resolve and validate input/output paths before any file is written."""

    resolved_inputs = {
        str(name): Path(path).resolve()
        for name, path in inputs.items()
    }
    resolved_outputs = {
        str(name): Path(path).resolve()
        for name, path in outputs.items()
        if path is not None
    }

    roles_by_path: dict[Path, list[str]] = {}
    for name, path in resolved_inputs.items():
        roles_by_path.setdefault(path, []).append(f"input:{name}")
    for name, path in resolved_outputs.items():
        roles_by_path.setdefault(path, []).append(f"output:{name}")

    collisions = {
        path: roles
        for path, roles in roles_by_path.items()
        if len(roles) > 1
    }
    if collisions:
        details = "; ".join(
            f"{path} ({', '.join(roles)})"
            for path, roles in sorted(collisions.items(), key=lambda item: str(item[0]))
        )
        raise ValueError(f"input and output paths must all be different: {details}")

    if not overwrite:
        existing = {
            name: path
            for name, path in resolved_outputs.items()
            if path.exists()
        }
        if existing:
            details = "; ".join(
                f"{name}={path}"
                for name, path in sorted(existing.items())
            )
            raise FileExistsError(
                "output already exists; choose a new path or explicitly enable "
                f"overwrite: {details}"
            )

    return resolved_inputs, resolved_outputs


def privacy_safe_path(path: str | Path, *, base_dir: str | Path | None = None) -> str:
    """Return a relative path or basename suitable for shared metadata."""

    resolved = Path(path).resolve()
    if base_dir is not None:
        try:
            return resolved.relative_to(Path(base_dir).resolve()).as_posix()
        except ValueError:
            pass
    return resolved.name


def sanitize_metadata(value: Any, *, base_dir: str | Path | None = None) -> Any:
    """Recursively replace absolute path strings with privacy-safe paths."""

    if isinstance(value, Mapping):
        return {
            str(key): sanitize_metadata(item, base_dir=base_dir)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize_metadata(item, base_dir=base_dir) for item in value]
    if isinstance(value, tuple):
        return [sanitize_metadata(item, base_dir=base_dir) for item in value]
    if isinstance(value, Path):
        return privacy_safe_path(value, base_dir=base_dir)
    if isinstance(value, str) and Path(value).is_absolute():
        return privacy_safe_path(value, base_dir=base_dir)
    return value
