from pathlib import Path

from experimental.production_poc.adapters.service_probes import tail_log_files


def test_tail_log_files_skips_permission_error(monkeypatch, tmp_path: Path) -> None:
    readable = tmp_path / "readable.log"
    readable.write_text("line1\nline2\n", encoding="utf-8")

    blocked = tmp_path / "blocked.log"
    blocked.write_text("secret\n", encoding="utf-8")

    original_exists = Path.exists
    original_is_file = Path.is_file
    original_read_text = Path.read_text

    def _exists(path: Path) -> bool:
        if path == blocked:
            raise PermissionError("blocked")
        return original_exists(path)

    def _is_file(path: Path) -> bool:
        return original_is_file(path)

    def _read_text(path: Path, *args, **kwargs) -> str:  # noqa: ANN002, ANN003
        if path == blocked:
            raise PermissionError("blocked")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "exists", _exists)
    monkeypatch.setattr(Path, "is_file", _is_file)
    monkeypatch.setattr(Path, "read_text", _read_text)

    excerpts = tail_log_files([blocked, readable], max_lines=5)

    assert str(readable) in excerpts
    assert excerpts[str(readable)] == ["line1", "line2"]
    assert str(blocked) not in excerpts
