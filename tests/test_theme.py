from pathlib import Path

import pytest
import yaml

from engine.theme import THEMES_DIR, load_theme, load_themes


def test_every_theme_file_is_valid():
    themes = load_themes()
    assert "cat" in themes


def _write_variant(tmp_path: Path, **changes) -> Path:
    data = yaml.safe_load((THEMES_DIR / "cat.yaml").read_text(encoding="utf-8"))
    data.update(changes)
    path = tmp_path / f"{data['name']}.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


def test_missing_translation_is_rejected(tmp_path):
    data = yaml.safe_load((THEMES_DIR / "cat.yaml").read_text(encoding="utf-8"))
    gains = data["gains"]
    gains[0] = {"en": gains[0]["en"]}
    path = _write_variant(tmp_path, language="both", gains=gains)
    with pytest.raises(ValueError, match=r"gains\[0\] is missing its 'fa' text"):
        load_theme(path)


def test_english_only_theme_needs_no_farsi(tmp_path):
    data = yaml.safe_load((THEMES_DIR / "cat.yaml").read_text(encoding="utf-8"))
    gains = data["gains"]
    gains[0] = {"en": gains[0]["en"]}
    assert load_theme(_write_variant(tmp_path, language="en", gains=gains)).langs == ("en",)


def test_titles_out_of_order_are_rejected(tmp_path):
    data = yaml.safe_load((THEMES_DIR / "cat.yaml").read_text(encoding="utf-8"))
    titles = list(reversed(data["titles"]))
    with pytest.raises(ValueError, match="increasing order"):
        load_theme(_write_variant(tmp_path, titles=titles))


def test_unknown_field_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="extra"):
        load_theme(_write_variant(tmp_path, colour="orange"))


def test_name_must_match_file(tmp_path):
    path = _write_variant(tmp_path)
    renamed = path.with_name("dog.yaml")
    path.rename(renamed)
    with pytest.raises(ValueError, match="must match the file name"):
        load_theme(renamed)


TAAROF_HOOK = {"kind": "lost_turn", "chance": 0.1, "messages": [{"en": "After you!", "fa": "اول شما!"}]}


def test_hook_is_optional_and_validated(tmp_path):
    assert load_themes()["cat"].hook is None
    theme = load_theme(_write_variant(tmp_path, hook=TAAROF_HOOK))
    assert theme.hook.kind == "lost_turn" and theme.hook.chance == 0.1


def test_hook_messages_need_every_language(tmp_path):
    hook = {**TAAROF_HOOK, "messages": [{"en": "After you!"}]}
    with pytest.raises(ValueError, match=r"hook.messages\[0\] is missing its 'fa' text"):
        load_theme(_write_variant(tmp_path, hook=hook))


@pytest.mark.parametrize("change", [{"chance": 1.5}, {"chance": 0}, {"kind": "steal_turn"}, {"messages": []}])
def test_bad_hooks_are_rejected(tmp_path, change):
    with pytest.raises(ValueError):
        load_theme(_write_variant(tmp_path, hook={**TAAROF_HOOK, **change}))
