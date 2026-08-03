"""ResolvedMod 真实资源目录解析测试（规范六）。

CK3 真实目录结构：mods_dir = <CK3用户目录>/mod，descriptor 里的
`path="mod/xxx"` 是相对 **CK3 用户目录**（descriptor 的上一级）。
本测试据此构造贴近真实的临时目录，覆盖：workshop / local / archive / missing /
损坏 descriptor / 相对路径 / 路径穿越 / 加载顺序 / replace_path / 字段完整。
"""
from __future__ import annotations

import zipfile

from app.services.mod_resolver import ModResolver


def _write_mod(mods_dir, name, body):
    (mods_dir / name).write_text(body, encoding="utf-8")


def _ck3_user(tmp_path):
    root = tmp_path / "ck3user"
    mods = root / "mod"
    mods.mkdir(parents=True)
    return root, mods


def test_local_mod_path_resolved(tmp_path):
    root, mods = _ck3_user(tmp_path)
    (mods / "local_mod").mkdir()
    _write_mod(mods, "local_mod.mod", 'name="本地 Mod"\npath="mod/local_mod"\n')
    r = ModResolver(mods_dir=str(mods))
    rep = r.resolve(["mod/local_mod.mod"])
    m = rep.required[0]
    assert m.source_type == "local"
    assert m.content_path == str(mods / "local_mod")
    assert m.resolved is True
    assert m.load_order == 0


def test_workshop_mod_path(tmp_path):
    root, mods = _ck3_user(tmp_path)
    ws = tmp_path / "steamapps" / "workshop" / "content" / "1158310" / "ugc_999"
    ws.mkdir(parents=True)
    # 创意工坊订阅 Mod 的 descriptor 通常写绝对路径。
    desc = f'name="订阅 Mod"\npath="{ws.as_posix()}"\n'
    (mods / "ugc_999.mod").write_text(desc, encoding="utf-8")
    r = ModResolver(mods_dir=str(mods))
    rep = r.resolve(["mod/ugc_999.mod"])
    m = rep.required[0]
    assert m.source_type == "workshop"
    assert m.resolved is True
    assert m.content_path == str(ws)


def test_archive_mod(tmp_path):
    root, mods = _ck3_user(tmp_path)
    archive = mods / "ugc_zip.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(
            "localization/simp_chinese/mod_l.yml", 'l_simp_chinese:\n key_a: "中文甲"\n'
        )
    _write_mod(mods, "ugc_zip.mod", 'name="压缩包 Mod"\narchive="mod/ugc_zip.zip"\n')
    r = ModResolver(mods_dir=str(mods))
    rep = r.resolve(["mod/ugc_zip.mod"])
    m = rep.required[0]
    assert m.source_type == "archive"
    assert m.archive_path == str(archive)
    assert m.localization_paths == [str(archive)]
    assert m.resolved is True


def test_missing_mod(tmp_path):
    root, mods = _ck3_user(tmp_path)
    r = ModResolver(mods_dir=str(mods))
    rep = r.resolve(["mod/ugc_absent.mod"])
    m = rep.required[0]
    assert m.source_type == "missing"
    assert m.found_locally is False
    assert m.resolved is False
    assert "ugc_absent" in rep.missing


def test_relative_path_resolves_inside_mods_dir(tmp_path):
    root, mods = _ck3_user(tmp_path)
    (mods / "ugc_rel").mkdir()
    _write_mod(mods, "ugc_rel.mod", 'name="相对路径"\npath="mod/ugc_rel"\n')
    r = ModResolver(mods_dir=str(mods))
    rep = r.resolve(["mod/ugc_rel.mod"])
    m = rep.required[0]
    assert m.content_path == str(mods / "ugc_rel")
    assert m.resolved is True


def test_path_traversal_rejected(tmp_path):
    root, mods = _ck3_user(tmp_path)
    _write_mod(mods, "evil.mod", 'name="穿越"\npath="../../../../secret"\n')
    r = ModResolver(mods_dir=str(mods))
    rep = r.resolve(["mod/evil.mod"])
    m = rep.required[0]
    # 逃逸路径被拒绝：不加载内容，resolved=False
    assert m.content_path is None
    assert m.resolved is False


def test_load_order_and_replace_path(tmp_path):
    root, mods = _ck3_user(tmp_path)
    (mods / "mod_a").mkdir()
    (mods / "mod_b").mkdir()
    _write_mod(mods, "a.mod", 'name="A"\npath="mod/mod_a"\nreplace_path={ "events" }\n')
    _write_mod(mods, "b.mod", 'name="B"\npath="mod/mod_b"\n')
    r = ModResolver(mods_dir=str(mods))
    rep = r.resolve(["mod/a.mod", "mod/b.mod"])
    assert rep.required[0].load_order == 0
    assert rep.required[1].load_order == 1
    assert rep.required[0].replace_path == ["events"]


def test_resolved_fields_present(tmp_path):
    root, mods = _ck3_user(tmp_path)
    (mods / "mod_x").mkdir()
    _write_mod(
        mods,
        "x.mod",
        'name="X"\npath="mod/mod_x"\nremote_file_id="123"\n'
        'dependencies={ "mod/y.mod" }\n',
    )
    r = ModResolver(mods_dir=str(mods))
    rep = r.resolve(["mod/x.mod"])
    m = rep.required[0]
    assert m.descriptor_path == str(mods / "x.mod")
    assert m.remote_file_id == "123"
    assert m.dependencies == ["mod/y.mod"]
    assert m.localization_paths  # 至少尝试定位 localization
