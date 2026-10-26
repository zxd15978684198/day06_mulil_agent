#!/usr/bin/env bash
# 本地运行与 CI 完全一致的密钥检查（.github/workflows/ci.yml 的 Secret check）。
#
# Windows 上必须强制 UTF-8：Python 默认按系统编码（简中环境是 GBK）打开文件，
# 遇到 UTF-8 中文注释会抛 UnicodeDecodeError，detect-secrets 会把它当成二进制
# 静默跳过，结果就是本地假通过、CI 真失败。
set -euo pipefail

cd "$(dirname "$0")/.."
export PYTHONUTF8=1

git ls-files -z | xargs -0 uv run --locked detect-secrets-hook --baseline .secrets.baseline
