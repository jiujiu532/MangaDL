<div align="center">

# 📚 MangaDL

**功能强大的漫画下载器 & 在线阅读器**

一站式漫画搜索、在线阅读、批量下载、追更管理工具

![screenshot](screenshot.png)

[![Docker Build](https://github.com/jiujiu532/MangaDL/actions/workflows/docker-build.yml/badge.svg)](https://github.com/jiujiu532/MangaDL/actions)

</div>

## ✨ 功能特性

- 🔍 **多源搜索** — 支持 ManhwaHub、MangaDNA、ManhwaClub、Manga18、XToon 等多个漫画源
- 📖 **在线阅读** — 内置阅读器，支持懒加载、章节切换、键盘快捷键
- ⬇️ **批量下载** — 高并发章节/图片下载，自适应并发控制
- ⭐ **收藏管理** — 收藏分组、追更检测、一键批量更新
- 📋 **下载记录** — 追更记录 & 下载历史，章节范围详情  
- 🌙 **暗色主题** — 精美暗色/亮色主题切换
- 🐳 **Docker 部署** — 一行命令部署，数据持久化

## 🚀 快速开始

### 方式一：直接运行

**Windows**
```bash
# 下载 Release 中的 MangaScraper.exe，双击运行
# 或使用 Python
pip install -r requirements.txt
python server.py
```

**Linux / macOS**
```bash
pip install -r requirements.txt
python server.py
```

启动后访问 `http://localhost:5000`

### 方式二：Docker 部署（推荐）

```bash
docker run -d \
  --name mangadl \
  -p 5000:5000 \
  -v ./manga:/data/manga \
  -v ./config:/root/.manga_downloader \
  ghcr.io/jiujiu532/mangadl:latest
```

### Docker Compose

```yaml
services:
  mangadl:
    image: ghcr.io/jiujiu532/mangadl:latest
    container_name: mangadl
    ports:
      - "5000:5000"
    volumes:
      - ./manga:/data/manga
      - ./config:/root/.manga_downloader
    restart: unless-stopped
```

```bash
docker compose up -d
```

## ⌨️ 快捷键

| 快捷键 | 功能 |
|--------|------|
| `Space` | 向下翻页 |
| `Home` | 跳到顶部 |
| `End` | 跳到底部 |
| `←` `→` | 上一章 / 下一章 |
| `Esc` | 关闭阅读器 |

## 🔧 配置说明

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| 下载目录 | `~/manga` | 漫画保存路径 |
| 章节并发 | 50 | 同时下载章节数 |
| 图片并发 | 300 | 同时下载图片数 |
| 代理 | 无 | 支持 HTTP/SOCKS5 代理 |

配置文件保存在 `~/.manga_downloader/config.json`

## 📁 项目结构

```
├── server.py          # Flask Web 服务器
├── config.py          # 配置管理
├── favorites.py       # 收藏 & 下载记录
├── download_manager.py # 下载引擎
├── sources/           # 漫画源适配器
│   ├── base.py        # 基础类
│   ├── madara.py      # Madara/WP-Manga 通用
│   ├── manhwahub.py   # ManhwaHub
│   ├── mangadna.py    # MangaDNA
│   ├── manga18.py     # Manga18
│   └── xtoon.py       # XToon
├── static/            # 前端资源
├── templates/         # HTML 模板
├── Dockerfile
└── requirements.txt
```

## 📜 开源协议

MIT License
