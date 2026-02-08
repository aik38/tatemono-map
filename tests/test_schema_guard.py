import subprocess

from tatemono_map.db.schema import TABLE_SCHEMAS


def test_raw_sources_uses_content_column_only():
    raw_sources = next(schema for schema in TABLE_SCHEMAS if schema.name == "raw_sources")
    assert "content" in raw_sources.columns
    assert "raw_html" not in raw_sources.columns


def test_no_raw_html_reference_in_repo():
    result = subprocess.run(["git", "grep", "-n", "raw_html", "--", "src", "scripts", "templates"], capture_output=True, text=True)
    assert result.returncode == 1, result.stdout
