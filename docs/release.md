# Release Preparation

Use this page as the final preflight workflow before updating the public repository, creating a release, or pushing a tag.

## Public And Private Files

Public files live in the normal project folders:

- `src/`
- `tests/`
- `docs/`
- `configs/`
- `examples/`

Private machine-specific files belong in:

- `local/`

The `local/` directory is ignored by Git. Keep paths to private data, local Python installations, and full research datasets there.

Generated files should also stay out of the repository:

- `.deps/`
- `output/`
- `examples/output/*`, except `examples/output/.gitkeep`
- `__pycache__/`
- `.pytest_cache/`

## Preflight Command

Run:

```powershell
python tools\preflight_release.py
```

The script prints the release file list and fails if it finds:

- private machine paths in public files;
- generated Excel outputs;
- dependency folders;
- missing required project files.

If the directory has already been initialized with Git, the script also compares Git-visible files with the preflight release list.

If `python` is not available on the command line, run the script with your local interpreter path.

## Verification Commands

Run the automated public tests (including NetCDF climate input and SPEI-1/3):

```powershell
python -m unittest discover -s tests -v
```

Run the public example:

```powershell
bdhei compute `
  --spei-dir "examples\sample_spei" `
  --sti-dir "examples\sample_sti" `
  --output-dir "examples\output" `
  --spei-glob "*.csv" `
  --sti-suffix "_STI_M_03.csv" `
  --months 6 7 8
```

Run the local regression checks only on the machine that has the original research data:

```powershell
python tests\regression_check.py `
  --station-id "PRIVATE_REFERENCE_SITE" `
  --spei-file "path\to\reference_spei_file.xlsx" `
  --sti-file "path\to\reference_sti_file.xlsx" `
  --reference-output "path\to\reference_output.xlsx" `
  --reference-sheet "reference_sheet_name" `
  --reference-column "reference_column_name" `
  --tolerance 0.0001
```

```powershell
python tests\compare_directory_outputs.py `
  --reference-dir "path\to\legacy_reference_outputs" `
  --reference-pattern "{station_id}_legacy_reference.xlsx" `
  --reference-sheet "reference_sheet_name" `
  --reference-column "reference_column_name" `
  --new-dir "path\to\new_BDHEI_outputs" `
  --tolerance 0.001
```

## Before GitHub

Before uploading:

1. Run `python tools\preflight_release.py`.
2. Confirm `RELEASE_CHECKLIST.md` is complete.
3. Confirm `CITATION.cff` matches the final published paper metadata.
4. Confirm only shareable sample data is included.
5. Create the local Git repository and inspect `git status --short --ignored`.
6. Run `git add --dry-run .` and confirm it matches the preflight list.
