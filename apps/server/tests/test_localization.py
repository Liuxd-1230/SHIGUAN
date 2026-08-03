"""LocalizationLoader 单测（规范八：zh-Hans → english → key 回退）。"""
from app.services.localization import LocalizationLoader


def _make_loader() -> LocalizationLoader:
    loader = LocalizationLoader()
    # 模拟 game/localization/simp_chinese/culture.yml
    loader._ingest_file_str = None  # placeholder (avoid lint)
    return loader


def test_zh_hans_over_english(tmp_path):
    f = tmp_path / "culture.yml"
    f.write_text(
        'l_simp_chinese:\n asian_han_chinese: "汉文化"\n\n'
        'l_english:\n asian_han_chinese: "Han Chinese"\n',
        encoding="utf-8",
    )
    loader = LocalizationLoader()
    loader.load_dir(tmp_path)
    assert loader.resolve("asian_han_chinese", ["zh-Hans", "en"]) == "汉文化"
    # 仅英文回退
    assert loader.resolve("asian_han_chinese", ["en"]) == "Han Chinese"


def test_fallback_to_key_when_missing(tmp_path):
    f = tmp_path / "x.yml"
    f.write_text('l_english:\n some_key: "Some Value"\n', encoding="utf-8")
    loader = LocalizationLoader()
    loader.load_dir(tmp_path)
    # 简中缺失 → 英文命中
    assert loader.resolve("some_key") == "Some Value"
    # 完全未知 → 返回 None（调用方展示原 key）
    assert loader.resolve("unknown_key_xyz") is None


def test_mod_overrides_game(tmp_path):
    game = tmp_path / "game_loc"
    mod = tmp_path / "mod_loc"
    game.mkdir()
    mod.mkdir()
    (game / "l_simp_chinese.yml").write_text(
        'l_simp_chinese:\n trait_genius: "天才"\n', encoding="utf-8"
    )
    (mod / "l_simp_chinese.yml").write_text(
        'l_simp_chinese:\n trait_genius: " modified 天才"\n', encoding="utf-8"
    )
    loader = LocalizationLoader()
    loader.load_dir(game)
    base = loader.resolve("trait_genius")
    loader.load_dir(mod)
    assert loader.resolve("trait_genius") != base  # mod 覆盖生效
    assert "zh-Hans" in loader.loaded_languages


def test_malformed_lines_ignored(tmp_path):
    f = tmp_path / "bad.yml"
    f.write_text(
        'l_simp_chinese:\n good_key: "好"\n not_a_key_line\n another: "另一个"\n',
        encoding="utf-8",
    )
    loader = LocalizationLoader()
    loader.load_dir(tmp_path)
    assert loader.resolve("good_key") == "好"
    assert loader.resolve("another") == "另一个"
