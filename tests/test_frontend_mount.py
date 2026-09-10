"""The API selects a built Vue console without breaking source-only checkouts."""

from pathlib import Path

from app import main


def test_web_root_prefers_vue_bundle_when_built(monkeypatch, tmp_path: Path):
    vue = tmp_path / "frontend" / "dist"
    legacy = tmp_path / "web"
    vue.mkdir(parents=True)
    legacy.mkdir()
    (vue / "index.html").write_text("<div id='app'></div>", encoding="utf-8")
    monkeypatch.setattr(main, "VUE_WEB_ROOT", vue)
    monkeypatch.setattr(main, "LEGACY_WEB_ROOT", legacy)

    assert main._resolve_web_root() == vue


def test_web_root_falls_back_to_legacy_without_bundle(monkeypatch, tmp_path: Path):
    vue = tmp_path / "frontend" / "dist"
    legacy = tmp_path / "web"
    legacy.mkdir()
    monkeypatch.setattr(main, "VUE_WEB_ROOT", vue)
    monkeypatch.setattr(main, "LEGACY_WEB_ROOT", legacy)

    assert main._resolve_web_root() == legacy


def test_ordinary_answer_ui_does_not_expose_engine_controls():
    root = Path(__file__).resolve().parents[1] / "frontend" / "src"
    user_surface = (root / "views" / "AnswerView.vue").read_text(encoding="utf-8")

    for technical_control in ("text_strategy", "visual_strategy", "orchestration"):
        assert technical_control not in user_surface


def test_engine_controls_exist_only_in_admin_operations_surface():
    root = Path(__file__).resolve().parents[1] / "frontend" / "src"
    admin_surface = (root / "views" / "OperationsView.vue").read_text(encoding="utf-8")
    shell = (root / "components" / "AppShell.vue").read_text(encoding="utf-8")

    for technical_control in ("text_strategy", "visual_strategy", "orchestration"):
        assert technical_control in admin_surface
    assert "role !== 'admin'" in shell
