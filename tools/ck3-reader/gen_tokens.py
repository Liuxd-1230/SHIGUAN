#!/usr/bin/env python3
"""生成占位全量 CK3 token 表（id -> tXXXX）。

ck3save 的 build.rs 需要一份 "token 表" 文件（每行 `id tNAME`，空白分隔），
编译进 EnvTokens。本脚本生成 65536 条占位映射（id 0..65535 -> t0000..tffff），
让任意二进制 CK3 存档都能被完整 melt（占位名 tXXXX，不影响按 id 解析）。

若用户用 rakaly 从 Ck3.exe 导出真实 token 表（id -> 可读名），直接替换
tokens/ck3_tokens.txt 即可获得可读字段名；解析逻辑无需改动。
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "tokens", "ck3_tokens.txt")


def main() -> None:
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        for i in range(0x10000):
            f.write(f"{i} t{i:04x}\n")
    print(f"写入 {OUT}（{0x10000} 条）")


if __name__ == "__main__":
    main()
