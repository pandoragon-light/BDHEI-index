"""Small, explicit NetCDF I/O helpers used by the grid pipeline.

The numerical algorithms in this project operate on NumPy arrays, while the
files may be written either as the original NetCDF3 compatibility format or
as compressed/chunked NetCDF4 files.  Keeping the choice here prevents every
pipeline script from duplicating engine and encoding logic.
"""

from __future__ import annotations

import importlib
from pathlib import Path
import shutil
import tempfile
from contextlib import contextmanager
from typing import Any, Iterator, Mapping

import numpy as np


NETCDF3_FORMATS = {
    "NETCDF3_CLASSIC",
    "NETCDF3_64BIT",
    "NETCDF3_64BIT_OFFSET",
    "NETCDF3_64BIT_DATA",
}
NETCDF4_FORMATS = {"NETCDF4", "NETCDF4_CLASSIC"}
SUPPORTED_ENGINES = {"auto", "scipy", "netcdf4", "h5netcdf"}


def _package_available(name: str) -> bool:
    try:
        importlib.import_module(name)
    except Exception:
        # A package can be present but unusable because of a compiled-extension
        # ABI mismatch.  Treat that the same as an unavailable backend so
        # ``auto`` does not select a broken engine.
        return False
    return True


def resolve_netcdf_engine(engine: str, output_format: str | None = None) -> str:
    """Resolve and validate a NetCDF engine without silently changing modes."""

    requested_engine = str(engine).lower()
    if requested_engine not in SUPPORTED_ENGINES:
        raise ValueError(
            f"unsupported NetCDF engine {engine!r}; "
            f"choose one of {sorted(SUPPORTED_ENGINES)}"
        )
    normalized_format = str(output_format).upper() if output_format else None

    if requested_engine == "auto":
        if normalized_format in NETCDF4_FORMATS:
            if _package_available("netCDF4"):
                requested_engine = "netcdf4"
            elif _package_available("h5netcdf"):
                requested_engine = "h5netcdf"
            else:
                raise RuntimeError(
                    "NETCDF4 output requires the netCDF4 or h5netcdf package"
                )
        else:
            if _package_available("netCDF4"):
                requested_engine = "netcdf4"
            elif _package_available("h5netcdf"):
                requested_engine = "h5netcdf"
            else:
                requested_engine = "scipy"

    if requested_engine == "scipy" and normalized_format in NETCDF4_FORMATS:
        raise ValueError(
            f"the scipy engine cannot write {normalized_format}; "
            "use engine=netcdf4 or h5netcdf"
        )
    if requested_engine == "netcdf4" and not _package_available("netCDF4"):
        raise RuntimeError("the netCDF4 Python package is not available")
    if requested_engine == "h5netcdf" and not _package_available("h5netcdf"):
        raise RuntimeError("the h5netcdf Python package is not available")
    return requested_engine


def _needs_ascii_staging(path: Path, engine: str) -> bool:
    return engine in {"netcdf4", "h5netcdf"} and any(ord(character) > 127 for character in str(path))


@contextmanager
def open_netcdf(path: str | Path, *, engine: str = "scipy", **kwargs: Any) -> Iterator[Any]:
    """Open a NetCDF file with an explicit engine and cleanly close it.

    On this Windows host the native HDF5-backed readers cannot reliably open
    a path containing Chinese characters.  For those engines only, stage the
    file into the system temporary directory, then expose the same xarray
    object to the caller.  The user's source file is never changed.
    """

    import xarray as xr

    source_path = Path(path).resolve()
    if not source_path.exists():
        raise FileNotFoundError(source_path)
    actual_engine = resolve_netcdf_engine(str(engine).lower())
    if _needs_ascii_staging(source_path, actual_engine):
        with tempfile.TemporaryDirectory(prefix="bdhei_netcdf_read_") as temporary_directory:
            staged_path = Path(temporary_directory) / "input.nc"
            shutil.copy2(source_path, staged_path)
            with xr.open_dataset(staged_path, engine=actual_engine, **kwargs) as dataset:
                yield dataset
        return

    with xr.open_dataset(source_path, engine=actual_engine, **kwargs) as dataset:
        yield dataset


def _normalize_chunks(
    chunks: Mapping[str, int] | None,
) -> dict[str, int] | None:
    if chunks is None:
        return None
    if not isinstance(chunks, Mapping):
        raise ValueError("NetCDF chunks must be a mapping from dimension to positive integer")
    normalized: dict[str, int] = {}
    for dimension, size in chunks.items():
        integer_size = int(size)
        if integer_size <= 0:
            raise ValueError(f"NetCDF chunk size for {dimension!r} must be positive")
        normalized[str(dimension)] = integer_size
    return normalized


def _build_encoding(
    dataset: Any,
    *,
    engine: str,
    chunks: Mapping[str, int] | None,
    compression_level: int | None,
) -> dict[str, dict[str, Any]]:
    normalized_chunks = _normalize_chunks(chunks)
    if engine == "scipy":
        if normalized_chunks or compression_level is not None:
            raise ValueError(
                "NetCDF chunks/compression require the netcdf4 or h5netcdf engine"
            )
        return {}

    if compression_level is not None and not 0 <= int(compression_level) <= 9:
        raise ValueError("compression_level must be between 0 and 9")

    encoding: dict[str, dict[str, Any]] = {}
    for variable_name, variable in dataset.data_vars.items():
        variable_encoding: dict[str, Any] = {
            "zlib": True,
            "shuffle": True,
        }
        if np.issubdtype(np.dtype(variable.dtype), np.floating):
            variable_encoding["_FillValue"] = np.nan
        if compression_level is not None:
            variable_encoding["complevel"] = int(compression_level)
        if normalized_chunks:
            chunk_sizes: list[int] = []
            for dimension, dimension_size in zip(variable.dims, variable.shape):
                requested_size = normalized_chunks.get(dimension, int(dimension_size))
                chunk_sizes.append(min(requested_size, int(dimension_size)))
            variable_encoding["chunksizes"] = tuple(chunk_sizes)
        encoding[variable_name] = variable_encoding
    return encoding


def write_netcdf(
    dataset: Any,
    path: str | Path,
    *,
    engine: str = "scipy",
    output_format: str = "NETCDF3_64BIT",
    chunks: Mapping[str, int] | None = None,
    compression_level: int | None = None,
) -> dict[str, str | None]:
    """Write a dataset and return the actual I/O settings used.

    The default remains the historical SciPy/NetCDF3 path.  NetCDF4
    compression and chunking are opt-in so existing outputs and commands keep
    their compatibility behavior.
    """

    destination = Path(path).resolve()
    normalized_format = str(output_format).upper()
    if normalized_format not in NETCDF3_FORMATS | NETCDF4_FORMATS:
        raise ValueError(
            f"unsupported NetCDF format {output_format!r}; "
            f"choose one of {sorted(NETCDF3_FORMATS | NETCDF4_FORMATS)}"
        )
    actual_engine = resolve_netcdf_engine(engine, normalized_format)
    if actual_engine == "scipy" and normalized_format not in NETCDF3_FORMATS:
        raise ValueError("scipy output must use a NetCDF3 format")
    if actual_engine in {"netcdf4", "h5netcdf"} and normalized_format in NETCDF3_FORMATS:
        # Both engines can write NetCDF3 only through different compatibility
        # paths; keeping this explicit avoids an accidental format change.
        raise ValueError(
            f"{actual_engine} is reserved for NETCDF4 output in this helper; "
            "use engine=scipy for NetCDF3"
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    encoding = _build_encoding(
        dataset,
        engine=actual_engine,
        chunks=chunks,
        compression_level=compression_level,
    )
    if _needs_ascii_staging(destination, actual_engine):
        with tempfile.TemporaryDirectory(prefix="bdhei_netcdf_write_") as temporary_directory:
            staged_path = Path(temporary_directory) / "output.nc"
            dataset.to_netcdf(
                staged_path,
                engine=actual_engine,
                format=normalized_format,
                encoding=encoding,
            )
            shutil.copy2(staged_path, destination)
    else:
        dataset.to_netcdf(
            destination,
            engine=actual_engine,
            format=normalized_format,
            encoding=encoding,
        )
    return {
        "engine": actual_engine,
        "format": normalized_format,
        "chunks": str(_normalize_chunks(chunks)) if chunks is not None else None,
        "compression_level": str(compression_level) if compression_level is not None else None,
    }
