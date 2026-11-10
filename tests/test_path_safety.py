from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(PROJECT_ROOT / "src"))

from bdhei.path_safety import privacy_safe_path, sanitize_metadata, validate_io_paths  # noqa: E402


class PathSafetyTests(unittest.TestCase):
    def test_input_and_output_collision_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "source.csv"
            source.write_text("value\n1\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "must all be different"):
                validate_io_paths(
                    inputs={"source": source},
                    outputs={"diagnostics": source},
                )
            self.assertEqual(source.read_text(encoding="utf-8"), "value\n1\n")

    def test_existing_output_requires_explicit_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            source = directory / "source.csv"
            output = directory / "output.csv"
            source.write_text("source", encoding="utf-8")
            output.write_text("existing", encoding="utf-8")
            with self.assertRaisesRegex(FileExistsError, "explicitly enable overwrite"):
                validate_io_paths(
                    inputs={"source": source},
                    outputs={"result": output},
                )
            validate_io_paths(
                inputs={"source": source},
                outputs={"result": output},
                overwrite=True,
            )

    def test_metadata_removes_absolute_parent_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory).resolve()
            inside = directory / "output" / "result.nc"
            outside = directory.parent / "private" / "input.nc"
            payload = sanitize_metadata(
                {"inside": str(inside), "outside": str(outside)},
                base_dir=directory,
            )
            self.assertEqual(payload["inside"], "output/result.nc")
            self.assertEqual(payload["outside"], "input.nc")
            self.assertEqual(privacy_safe_path(outside), "input.nc")


if __name__ == "__main__":
    unittest.main()
