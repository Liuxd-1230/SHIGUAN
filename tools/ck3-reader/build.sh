#!/usr/bin/env bash
# 构建 ck3-reader sidecar。
#
# 关键：ck3save 的 build.rs 在检测到环境变量 CK3_IRONMAN_TOKENS 指向一份
# "token 表" 文件时，才会把 token-id -> 名称 映射编译进二进制；否则 EnvTokens
# 为空，melt 时遇到未知 key 会把整段 value 跳过（仅输出 25 字节 header）。
#
# 本项目提交一份 **占位全量 token 表** tokens/ck3_tokens.txt（65536 条
# id -> tXXXX，由 gen_tokens.py 生成，不依赖游戏安装），保证任意二进制存档
# 都能完整 melt。若用户后续用 rakaly 从 Ck3.exe 导出真实 token 表，把它路径
# 传给 CK3_IRONMAN_TOKENS 即可获得可读字段名（解析逻辑无需改动）。
#
# Windows（Git Bash / WSL）下必须用 Windows 风格路径，否则 build.rs 找不到文件。
set -euo pipefail

cd "$(dirname "$0")"

TOKENS_FILE="$(pwd -W 2>/dev/null || pwd)/tokens/ck3_tokens.txt"
if [ ! -f "$TOKENS_FILE" ]; then
  echo "缺少 token 表：$TOKENS_FILE（先运行 python gen_tokens.py）" >&2
  exit 1
fi

export CK3_IRONMAN_TOKENS="$TOKENS_FILE"
echo "CK3_IRONMAN_TOKENS=$CK3_IRONMAN_TOKENS"
cargo build --release
echo "构建完成：target/release/ck3-reader.exe"
