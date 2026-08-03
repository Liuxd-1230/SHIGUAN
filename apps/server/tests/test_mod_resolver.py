"""ModResolver 单测：解析 .mod 描述符、缺失/损坏/非 Steam 本地 Mod、版本不匹配。"""
from app.services.mod_resolver import ModResolver


_SAMPLE_MOD = '''
name="UI 美化补全"
path="mod/my_mod"
remote_file_id=3598735569
dependencies={
	"mod/ugc_2222302033.mod"
	"mod/ugc_2879799963.mod"
}
supported_version="1.19.*"
'''


_CORRUPT_MOD = '''
name="损坏的 Mod
path="mod/broken
'''


def test_parse_mod_file():
    resolved = ModResolver._parse_mod_file(_SAMPLE_MOD)
    assert resolved["name"] == "UI 美化补全"
    assert resolved["path"] == "mod/my_mod"
    assert resolved["remote_file_id"] == "3598735569"
    assert "mod/ugc_2222302033.mod" in resolved["dependencies"]
    assert "mod/ugc_2879799963.mod" in resolved["dependencies"]


def test_resolve_missing_without_local_mods_dir():
    resolver = ModResolver(mods_dir=None)
    report = resolver.resolve(["mod/ugc_3598735569.mod", "mod/ugc_2222302033.mod"])
    assert report.required_count == 2
    assert report.found_count == 0
    assert set(report.missing) == {"ugc_3598735569", "ugc_2222302033"}
    # 名称回退为 mod_id（绝不伪造）
    assert report.required[0].name == "ugc_3598735569"
    assert report.required[0].found_locally is False


def test_resolve_found_local(tmp_path):
    # 非 Steam 本地 Mod：直接放一个 .mod 文件（非 ugc_ 前缀）
    (tmp_path / "local_mod.mod").write_text(
        'name="本地测试 Mod"\npath="mod/local_mod"\n', encoding="utf-8"
    )
    resolver = ModResolver(mods_dir=str(tmp_path))
    report = resolver.resolve(["mod/local_mod.mod"])
    assert report.found_count == 1
    assert report.missing_count == 0
    assert report.required[0].found_locally is True
    assert report.required[0].name == "本地测试 Mod"


def test_resolve_corrupted_descriptor(tmp_path):
    (tmp_path / "broken.mod").write_text(_CORRUPT_MOD, encoding="utf-8")
    resolver = ModResolver(mods_dir=str(tmp_path))
    report = resolver.resolve(["mod/broken.mod"])
    assert report.corrupted_count == 1
    assert "broken" in report.corrupted
    # 损坏不阻塞：仍计入 required，found=True（文件存在）
    assert report.required[0].found_locally is True
    assert report.required[0].corrupted is True


def test_resolve_version_mismatch(tmp_path):
    (tmp_path / "old.mod").write_text(
        'name="老版本 Mod"\nsupported_version="1.10.*"\n', encoding="utf-8"
    )
    resolver = ModResolver(mods_dir=str(tmp_path))
    report = resolver.resolve(["mod/old.mod"], save_game_version="1.19.0.6")
    assert "old" in report.version_mismatch


def test_resolve_unknown_mod_field_no_crash(tmp_path):
    # descriptor 含未知字段，不应导致解析失败
    (tmp_path / "weird.mod").write_text(
        'name="奇怪 Mod"\nunknown_field={ custom_node="x" }\n', encoding="utf-8"
    )
    resolver = ModResolver(mods_dir=str(tmp_path))
    report = resolver.resolve(["mod/weird.mod"])
    assert report.found_count == 1
    assert report.corrupted_count == 0
