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


def test_upper_l_name_key_does_not_break_language_partition(tmp_path):
    """回归：`L_ucja: "武恰"` 是大写 L 的人名条目，此前被 `re.IGNORECASE` 误判为语言头，
    导致文件后半（含 Maurizio）落入 ucja/ukasz 分区而解析不到。修复后须全部分入 zh-Hans。"""
    f = tmp_path / "names.yml"
    f.write_text(
        'l_simp_chinese:\n'
        ' A_bel: "阿拜尔"\n'
        ' L_ucja: "武恰"\n'
        ' L_ukasz: "武卡什"\n'
        ' Maurizio: "毛里齐奥"\n'
        ' Mun_won: "文元"\n',
        encoding="utf-8",
    )
    loader = LocalizationLoader()
    loader.load_dir(tmp_path)
    assert loader.resolve("A_bel") == "阿拜尔"
    assert loader.resolve("L_ucja") == "武恰"  # 作为名字条目，不再是语言头
    assert loader.resolve("L_ukasz") == "武卡什"
    # 关键：Maurizio 仍在 zh-Hans 分区可解析（之前会丢失）。
    assert loader.resolve("Maurizio") == "毛里齐奥"
    assert loader.resolve("Mun_won") == "文元"
    assert "ucja" not in loader.loaded_languages
    assert "ukasz" not in loader.loaded_languages


def test_version_number_key_format(tmp_path):
    """PDX 版本号格式 `key:0 "值"`（mod 本地化常见）此前被 `_ENTRY_RE` 漏掉。"""
    f = tmp_path / "dyn.yml"
    f.write_text('l_simp_chinese:\n dynn_liang205:0 "梁"\n dynn_chai200: 1 "柴"\n', encoding="utf-8")
    loader = LocalizationLoader()
    loader.load_dir(tmp_path)
    assert loader.resolve("dynn_liang205") == "梁"
    assert loader.resolve("dynn_chai200") == "柴"


def test_hyphen_key_and_spaces_after_colon(tmp_path):
    """连字符键（Abdul-Azeem）与 `key: "值"`（冒号后空格）此前解析不到。"""
    f = tmp_path / "n.yml"
    f.write_text(
        'l_simp_chinese:\n Abdul-Azeem: "阿卜杜勒‑阿齐姆"\n key_with_space : "带空格值"\n',
        encoding="utf-8",
    )
    loader = LocalizationLoader()
    loader.load_dir(tmp_path)
    assert loader.resolve("Abdul-Azeem") == "阿卜杜勒‑阿齐姆"
    assert loader.resolve("key_with_space") == "带空格值"
