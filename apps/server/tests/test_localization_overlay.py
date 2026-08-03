"""GameDataResolver 本地化叠加测试（规范六）：基础游戏 → 按 Mod 顺序覆盖。

覆盖：后加载 Mod 覆盖基础 key；zh-Hans → english 回退；archive Mod 只读读取。
"""
from __future__ import annotations

import types
import zipfile

from app.services.game_data_resolver import GameDataResolver


def _make_game(root):
    # GameDataResolver.load_game 读 <game_dir>/game/localization，故此处 game 目录保持单层。
    base_zh = root / "game" / "localization" / "simp_chinese"
    base_en = root / "game" / "localization" / "english"
    base_zh.mkdir(parents=True)
    base_en.mkdir(parents=True)
    (base_zh / "base.yml").write_text(
        'l_simp_chinese:\n shared: "基础中文"\n only_base: "仅基础"\n', encoding="utf-8"
    )
    (base_en / "base.yml").write_text(
        'l_english:\n shared: "Base EN"\n only_base: "Only Base"\n', encoding="utf-8"
    )
    return root


def _resolved_mod(content_path, localization_paths, load_order=0, source_type="local"):
    return types.SimpleNamespace(
        source_type=source_type,
        content_path=content_path,
        localization_paths=localization_paths,
        load_order=load_order,
        resolved=True,
    )


def test_base_then_mod_overlay(tmp_path):
    gdir = _make_game(tmp_path)
    mod_dir = tmp_path / "mod_over"
    mod_zh = mod_dir / "localization" / "simp_chinese"
    mod_zh.mkdir(parents=True)
    (mod_zh / "base.yml").write_text(
        'l_simp_chinese:\n shared: "覆盖中文"\n', encoding="utf-8"
    )
    r = GameDataResolver(game_dir=gdir)
    loader = r.build_localization(
        resolved_mods=[_resolved_mod(str(mod_dir), [str(mod_dir / "localization")])]
    )
    # 后加载的 Mod 覆盖基础 key
    assert loader.resolve("shared") == "覆盖中文"
    # 仅基础存在的 key 保留（Mod 没定义就不该被覆盖掉）
    assert loader.resolve("only_base") == "仅基础"
    # 英文回退
    assert loader.resolve("only_base", languages=["en"]) == "Only Base"


def test_zh_fallback_to_english(tmp_path):
    gdir = _make_game(tmp_path)
    r = GameDataResolver(game_dir=gdir)
    loader = r.build_localization(resolved_mods=[])
    # 仅中文有该 key 时回退链
    assert loader.resolve("shared") == "基础中文"


def test_archive_mod_localization(tmp_path):
    gdir = _make_game(tmp_path)
    archive = tmp_path / "mod_archive.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(
            "localization/simp_chinese/base.yml",
            'l_simp_chinese:\n shared: "压缩包中文"\n',
        )
    r = GameDataResolver(game_dir=gdir)
    loader = r.build_localization(
        resolved_mods=[_resolved_mod(None, [str(archive)], source_type="archive")]
    )
    assert loader.resolve("shared") == "压缩包中文"
