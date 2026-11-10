from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .batch import BatchConfig, run_batch


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Calculate BDHEI from SPEI and STI station files.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    indices = subparsers.add_parser("indices", help="Calculate STI, SPEI-1/3 and BDHEI from monthly temperature/precipitation NetCDF.")
    indices.add_argument("--config", required=True, type=Path)

    compute = subparsers.add_parser("compute", help="Calculate BDHEI from existing station/grid indices.")
    compute.add_argument("--config", type=Path, help="Station/grid YAML config; spei_scale selects SPEI_1 or SPEI_3.")
    compute.add_argument("--spei-dir", type=Path)
    compute.add_argument("--sti-dir", type=Path)
    compute.add_argument("--output-dir", type=Path)
    compute.add_argument("--months", nargs="+", type=int, default=[6, 7, 8])
    compute.add_argument("--spei-scale", type=int, choices=(1, 3), help="1 = SPEI-1; 3 = SPEI-3 (default); overrides YAML when supplied.")
    compute.add_argument("--spei-column", help="Custom column name; otherwise derived from --spei-scale.")
    compute.add_argument("--sti-column", default="STI")
    compute.add_argument("--date-column", default="date")
    compute.add_argument("--output-column", default="BDHEI")
    compute.add_argument("--sti-suffix", default="_STI_M_03.xlsx")
    compute.add_argument("--spei-glob", default="*.xlsx")
    compute.add_argument("--eps", type=float, default=1e-6)
    compute.add_argument("--grid-m", type=int, default=20)
    return parser


def _load_config(path: Path) -> dict:
    import yaml

    config = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if not isinstance(config, dict):
        raise ValueError("configuration must be a YAML mapping")
    return config


def _main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "indices":
        from .climate import calculate_climate_from_config

        result = calculate_climate_from_config(_load_config(args.config), base_dir=Path.cwd())
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "compute":
        if args.config:
            if any((args.spei_dir, args.sti_dir, args.output_dir)):
                raise ValueError("use --config or the station directory arguments in one command")
            from .pipeline import calculate_from_config

            payload = _load_config(args.config)
            if args.spei_scale is not None:
                payload["spei_scale"] = args.spei_scale
            result = calculate_from_config(payload, base_dir=Path.cwd())
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if not all((args.spei_dir, args.sti_dir, args.output_dir)):
            raise ValueError("compute requires --config or --spei-dir, --sti-dir and --output-dir")
        config = BatchConfig(
            spei_dir=args.spei_dir,
            sti_dir=args.sti_dir,
            output_dir=args.output_dir,
            months=tuple(args.months),
            spei_column=args.spei_column,
            spei_scale=args.spei_scale if args.spei_scale is not None else (1 if args.spei_column == "SPEI_1" else 3),
            sti_column=args.sti_column,
            date_column=args.date_column,
            output_column=args.output_column,
            sti_suffix=args.sti_suffix,
            spei_glob=args.spei_glob,
            eps=args.eps,
            grid_m=args.grid_m,
        )
        run_batch(config)
        return 0

    return 1


def main(argv: list[str] | None = None) -> int:
    try:
        return _main(argv)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
