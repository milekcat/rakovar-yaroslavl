"""The build must validate editable sources without restoring stale ZIP files."""
from pathlib import Path

from prepare_render import REQUIRED, validate_sources


def source_tree(root: Path) -> None:
    for name in REQUIRED:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("editable source\n", encoding="utf-8")


def test_prepare_preserves_sources_without_an_archive(tmp_path):
    source_tree(tmp_path)
    before = {name: (tmp_path / name).read_bytes() for name in REQUIRED}
    assert validate_sources(tmp_path) == []
    assert validate_sources(tmp_path) == []
    assert {name: (tmp_path / name).read_bytes() for name in REQUIRED} == before


def test_prepare_reports_missing_sources(tmp_path):
    source_tree(tmp_path)
    (tmp_path / "static/admin.js").unlink()
    assert "missing or empty source: static/admin.js" in validate_sources(tmp_path)


def test_prepare_rejects_missing_or_escaping_static_paths(tmp_path):
    source_tree(tmp_path)
    (tmp_path / "templates/storefront.html").write_text(
        "{{ url_for('static', filename='missing.svg') }}"
        "{{ url_for('static', filename='../README.md') }}",
        encoding="utf-8",
    )
    errors = validate_sources(tmp_path)
    assert len(errors) == 2
    assert any("missing.svg" in error for error in errors)
    assert any("../README.md" in error for error in errors)
