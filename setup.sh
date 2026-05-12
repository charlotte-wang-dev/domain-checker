#!/bin/bash
# domain-checker 一键安装
set -e

echo "🔧 Setting up domain-checker..."

# 创建虚拟环境
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
    echo "✅ Virtual environment created"
else
    echo "✅ Virtual environment exists"
fi

# 安装依赖
source .venv/bin/activate
pip install -r requirements.txt -q
echo "✅ Dependencies installed"

echo ""
echo "🎉 Done! Usage:"
echo ""
echo "  source .venv/bin/activate"
echo "  python3 domain_checker.py beatmaker"
echo ""
