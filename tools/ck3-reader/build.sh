#!/usr/bin/env bash
# 构建 ck3-reader sidecar。
#
# 关键：ck3save 的 build.rs 在检测到环境变量 CK3_IRONMAN_TOKENS 指向一份
# "token 表" 文件时，才会把 token-id -> 名称 映射编译进二进制；否则 EnvTokens
# 为空，melt 时遇到未知 key 会把整段 value 跳过（仅输出 25 字节 header）。
#
# 令牌表有两种：
#
#   1. tokens/ck3_tokens_real.txt —— **真实**表（id -> 真实字段名，如 first_name）。
#      属于 Paradox 游戏资产，禁止随仓库分发，因此被 .gitignore 排除。
#      用户从自己安装的游戏里提取：
#          python extract_tokens.py --verify
#      有了它，melt 出来的明文才有可读字段名，人物档案才能解析出真实语义。
#
#   2. tokens/ck3_tokens.txt —— **占位**表（65536 条 id -> tXXXX，随仓库提交，
#      由 gen_tokens.py 生成，不依赖游戏安装）。保证任意二进制存档都能完整
#      melt（不丢数据），但字段名不可读，只能做结构化诊断。
#
# 本脚本优先使用真实表，缺失时回退到占位表并给出提示。
#
# Windows（Git Bash / WSL）下必须用 Windows 风格路径，否则 build.rs 找不到文件。
set -euo pipefail

cd "$(dirname "$0")"

BASE="$(pwd -W 2>/dev/null || pwd)"
REAL_TOKENS="$BASE/tokens/ck3_tokens_real.txt"
PLACEHOLDER_TOKENS="$BASE/tokens/ck3_tokens.txt"

if [ -f "tokens/ck3_tokens_real.txt" ]; then
  TOKENS_FILE="$REAL_TOKENS"
  echo "使用真实令牌表（字段名可读）"
elif [ -f "tokens/ck3_tokens.txt" ]; then
  TOKENS_FILE="$PLACEHOLDER_TOKENS"
  echo "使用占位令牌表（字段名为 tXXXX，不可读）。"
  echo "如需真实字段名，请先运行：python extract_tokens.py --verify"
else
  echo "缺少 token 表：先运行 python gen_tokens.py（占位）或 python extract_tokens.py（真实）" >&2
  exit 1
fi

export CK3_IRONMAN_TOKENS="$TOKENS_FILE"
echo "CK3_IRONMAN_TOKENS=$CK3_IRONMAN_TOKENS"
cargo build --release
echo "构建完成：target/release/ck3-reader.exe"
