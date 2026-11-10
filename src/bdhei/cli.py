from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Calculate SPEI, STI and BDHEI from monthly temperature and precipitation.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (("station-indices", "Calculate from station monthly temperature/precipitation tables."),
                            ("indices", "Calculate from gridded monthly temperature/precipitation NetCDF.")):
        command = subparsers.add_parser(name, help=help_text)
        command.add_argument("--config", required=True, type=Path, help="YAML configuration; spei_scale selects 1 or 3 months.")
    return parser


def _load_config(path: Path) -> dict:
    import yaml

    config = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if not isinstance(config, dict):
        raise ValueError("configuration must be a YAML mapping")
    return config


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = _load_config(args.config)
        expected_mode = "station" if args.command == "station-indices" else "grid"
        if str(config.get("mode", expected_mode)).lower() != expected_mode:
            raise ValueError(f"{args.command} requires mode={expected_mode}")
        if expected_mode == "station":
            from .station import calculate_station_from_config
            result = calculate_station_from_config(config, base_dir=Path.cwd())
        else:
            from .climate import calculate_climate_from_config
            result = calculate_climate_from_config(config, base_dir=Path.cwd())
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
