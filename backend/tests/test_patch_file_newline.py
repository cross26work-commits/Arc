from pathlib import Path


def test_unified_diff_is_written_with_lf(
    tmp_path: Path,
) -> None:
    patch_path = tmp_path / "proposed.patch"

    patch_text = (
        "diff --git a/src/example.py "
        "b/src/example.py\n"
        "--- a/src/example.py\n"
        "+++ b/src/example.py\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    )

    patch_path.write_text(
        patch_text,
        encoding="utf-8",
        newline="\n",
    )

    data = patch_path.read_bytes()

    assert b"\r\n" not in data
    assert data.endswith(b"\n")
