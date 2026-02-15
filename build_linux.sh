#!/bin/bash
# Linux 构建脚本 — 在 Linux 机器上运行
# 依赖: python3, pip

set -e

echo "=== 安装依赖 ==="
pip3 install pyinstaller flask beautifulsoup4 requests --quiet

echo "=== 构建 Linux 二进制文件 ==="
python3 -m PyInstaller --onefile \
    --name "MangaScraper" \
    --add-data "templates:templates" \
    --add-data "static:static" \
    --add-data "sources:sources" \
    --hidden-import "sources.madara" \
    --hidden-import "sources.manga18" \
    --hidden-import "sources.mangadna" \
    --hidden-import "sources.manhwahub" \
    --hidden-import "sources.xtoon" \
    --hidden-import "bs4" \
    --hidden-import "concurrent.futures" \
    --console \
    server.py

echo "=== 构建完成 ==="
echo "二进制文件: dist/MangaScraper"
ls -lh dist/MangaScraper
