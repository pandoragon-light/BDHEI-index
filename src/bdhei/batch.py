from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from copulas.univariate import GaussianKDE

from .copula_scores import score_candidate_copulas
from .core import calculate_bdhei


@dataclass(frozen=True)
class BatchConfig:
    spei_dir: Path
    sti_dir: Path
    output_dir: Path
    months: tuple[int, ...] = (6, 7, 8)
    spei_column: str | None = None
    sti_column: str = "STI"
    date_column: str = "date"
    output_column: str = "BDHEI"
    sti_suffix: str = "_STI_M_03.xlsx"
    spei_glob: str = "*.xlsx"
    eps: float = 1e-6
    grid_m: int = 20
    write_scores: bool = True
    spei_scale: int = 3

    def __post_init__(self) -> None:
        from .spei import validate_spei_scale

        scale = validate_spei_scale(self.spei_scale)
        if self.spei_column is None:
            object.__setattr__(self, "spei_column", f"SPEI_{scale}")


def parse_date_series(series: pd.Series) -> pd.Series:
    parsed = pd.to_datetime(series, format="%m/%d/%Y", errors="coerce")
    fallback_mask = parsed.isna()
    if fallback_mask.any():
        parsed.loc[fallback_mask] = pd.to_datetime(series.loc[fallback_mask], errors="coerce")
    return parsed


def _station_id_from_spei_file(path: Path) -> str:
    stem = path.stem
    if stem.endswith("_SPEI"):
        return stem[: -len("_SPEI")]
    return stem.split("_")[0]


def _load_and_filter(path: Path, date_column: str, months: tuple[int, ...]) -> pd.DataFrame:
    if path.suffix.lower() == ".csv":
        data = pd.read_csv(path)
    elif path.suffix.lower() in {".xlsx", ".xls"}:
        data = pd.read_excel(path)
    else:
        raise ValueError(f"Unsupported input file type: {path.suffix}")
    if date_column not in data.columns:
        raise KeyError(f"{path} has no '{date_column}' column.")
    data = data.copy()
    data[date_column] = parse_date_series(data[date_column])
    data = data.dropna(subset=[date_column])
    return data[data[date_column].dt.month.isin(months)].copy()


def _cdf_matrix(data: pd.DataFrame, drought_col: str, heat_col: str, eps: float) -> np.ndarray:
    drought_kde = GaussianKDE()
    heat_kde = GaussianKDE()
    drought_kde.fit(data[drought_col])
    heat_kde.fit(data[heat_col])
    drought_cdf = np.clip(drought_kde.cdf(data[drought_col].to_numpy()), eps, 1 - eps)
    heat_cdf = np.clip(heat_kde.cdf(data[heat_col].to_numpy()), eps, 1 - eps)
    return np.column_stack((drought_cdf, heat_cdf))


def process_station(spei_path: Path, sti_path: Path, config: BatchConfig) -> tuple[pd.DataFrame, pd.DataFrame]:
    spei_data = _load_and_filter(spei_path, config.date_column, config.months)
    sti_data = _load_and_filter(sti_path, config.date_column, config.months)

    merged = pd.merge(spei_data, sti_data, on=config.date_column)
    merged = merged.dropna(subset=[config.spei_column, config.sti_column]).reset_index(drop=True)
    if merged.empty:
        raise ValueError(f"No merged observations for station file {spei_path.name}.")

    result = calculate_bdhei(
        merged,
        drought_col=config.spei_column,
        heat_col=config.sti_column,
        output_col=config.output_column,
        eps=config.eps,
    )

    x = _cdf_matrix(result.data, config.spei_column, config.sti_column, eps=config.eps)
    scores = score_candidate_copulas(
        x,
        selected_copula_type=result.copula_type,
        station_id=_station_id_from_spei_file(spei_path),
        grid_m=config.grid_m,
    )
    return result.data, scores


def run_batch(config: BatchConfig) -> pd.DataFrame:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    sti_files = {path.name for path in config.sti_dir.glob("*") if not path.name.startswith("~$")}
    score_tables = []

    for spei_path in sorted(config.spei_dir.glob(config.spei_glob)):
        if spei_path.name.startswith("~$"):
            continue

        station_id = _station_id_from_spei_file(spei_path)
        sti_name = f"{station_id}{config.sti_suffix}"
        if sti_name not in sti_files:
            print(f"[SKIP] STI file for station {station_id} not found")
            continue

        sti_path = config.sti_dir / sti_name
        try:
            bdhei_data, score_df = process_station(spei_path, sti_path, config)
        except Exception as exc:
            print(f"[SKIP] {station_id}: {exc}")
            continue

        out_path = config.output_dir / f"{station_id}_BDHEI_BestCopula.xlsx"
        with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
            bdhei_data[
                [
                    config.date_column,
                    config.spei_column,
                    config.sti_column,
                    config.output_column,
                    "Copula_Type",
                    "Copula_Params",
                ]
            ].to_excel(writer, index=False, sheet_name="BDHEI")
            if config.write_scores:
                score_df.to_excel(writer, index=False, sheet_name="Copula_Compare")

        score_tables.append(score_df)
        print(f"[OK] Processed station {station_id}")

    if score_tables:
        all_scores = pd.concat(score_tables, ignore_index=True)
        if config.write_scores:
            all_scores.to_excel(config.output_dir / "Copula_scores_allstations.xlsx", index=False)
        return all_scores

    return pd.DataFrame()
