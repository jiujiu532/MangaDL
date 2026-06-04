# 后端规范总索引

> 适用于当前仓库里的 Python/Flask 漫画下载器后端，以及与其直接耦合的 source adapter、下载流程、配置与本地数据模块。

---

## 项目后端现状

这个仓库不是典型的分层 Web API 工程，而是一个“**共享核心模块 + 两个入口**”的结构：

- `server.py`：Flask Web 后端，提供页面、JSON API、SSE、文件下载等能力。
- `app.py`：PyQt5 桌面 GUI，复用同一套 `sources/`、`download_manager.py`、`config.py`、`favorites.py`。
- `sources/`：各漫画站点适配层，负责抓取搜索结果、漫画详情、章节列表和章节图片。
- `download_manager.py`：下载任务核心，负责预取、并发下载、状态流转、回调。
- `config.py` / `favorites.py`：本地 JSON 持久化。
- `workers.py`：GUI 侧线程 worker，调用同一套 source 接口。

因此，后续补充后端规范时，优先记录“**共享模块如何被 Flask 与 GUI 共同使用**”这一真实结构，而不是套用常见的 `routes/services/repositories` 模板。

---

## 真实目录结构速览

```text
.
├── server.py                # Flask 入口，定义路由、缓存、源聚合、下载相关 API
├── app.py                   # PyQt5 GUI 入口，复用后端核心模块
├── download_manager.py      # 下载任务与并发控制核心
├── config.py                # 配置读写，本地 JSON 存储
├── favorites.py             # 收藏夹与下载历史，本地 JSON 存储
├── workers.py               # GUI 侧并发 worker
├── themes.py                # GUI 主题常量
├── sources/
│   ├── __init__.py          # 统一注册可用漫画源
│   ├── base.py              # MangaSource 抽象基类与共享 Session
│   ├── madara.py            # Madara/WP-Manga 通用源
│   ├── manhwahub.py         # ManhwaHub 源
│   ├── mangadna.py          # MangaDNA 源
│   ├── xtoon.py             # XToon 源
│   └── manga18.py           # 已实现但当前未注册的源
├── templates/
│   └── index.html           # Flask 页面模板
└── static/
    ├── app.js               # Web 前端脚本
    └── style.css            # Web 前端样式
```

---

## 后端模块分工

### 1. Flask 入口集中在 `server.py`

`server.py` 当前同时承担：

- Flask app 初始化，如 `app = Flask(...)`
- 全局单例创建，如 `Config()`、`FavoritesManager()`、`get_all_sources()`、`DownloadManager(...)`
- `/api/search`、`/api/sources` 等路由定义
- 源聚合、去重、分页池、健康状态缓存
- SSE 日志缓存与下载任务回调连接

这意味着当前代码风格是“**单文件编排 + 复用独立模块**”，新增后端能力时通常先判断：

- 是否只是 `server.py` 的接口/聚合逻辑
- 是否应下沉到 `sources/`、`download_manager.py`、`config.py`、`favorites.py`

### 2. 站点抓取逻辑集中在 `sources/`

所有站点接入都走 `sources/base.py` 里的 `MangaSource` 抽象基类；实际实现见：

- `sources/madara.py`
- `sources/manhwahub.py`
- `sources/mangadna.py`
- `sources/xtoon.py`
- `sources/manga18.py`

如果是新增漫画站点，不应把抓取逻辑写进 `server.py` 或 `workers.py`，而是补充新的 source adapter，并在 `sources/__init__.py` 注册。

### 3. 下载核心集中在 `download_manager.py`

下载相关业务不直接散落在 Flask 路由中，而是通过 `DownloadManager` 统一处理：

- 章节任务注册：`add_tasks(...)`
- 总体启动：`start()`
- 章节图片 URL 预取：`_prefetch_pipeline()`
- 图片下载：`_download_chapter(...)`
- 状态与日志回调：`task_updated`、`task_log`、`all_done`

`server.py` 与 `app.py` 都是调用者，不是下载实现本体。

### 4. 本地数据存储不是数据库，而是 JSON 文件

当前项目没有 ORM、migration、repository 层。持久化方式是：

- `config.py` → `~/.manga_downloader/config.json`
- `favorites.py` → `~/.manga_downloader/favorites.json`

因此，涉及“数据层”规范时，要按本地 JSON 配置/状态文件来描述，不要写成数据库项目的习惯用法。

---

## 规范索引

| 文档 | 作用 | 当前适用性 |
|---|---|---|
| [Directory Structure](./directory-structure.md) | 说明核心模块应该放在哪里 | 已有模板，后续应按本仓库实际结构补充 |
| [Database Guidelines](./database-guidelines.md) | 记录当前没有数据库、仅有本地 JSON 持久化的现实 | 需要按真实现状补充 |
| [Error Handling](./error-handling.md) | 记录当前项目大量使用宽泛 `except Exception` 的现状与边界 | 需要按真实现状补充 |
| [Logging Guidelines](./logging-guidelines.md) | 记录 `print`、SSE buffer、signal callback 混合日志方式 | 需要按真实现状补充 |
| [Quality Guidelines](./quality-guidelines.md) | 记录下载器项目里真实可接受的代码模式与校验方式 | 需要按真实现状补充 |
| [Source Adapters](./source-adapters.md) | 规范 `sources/` 下漫画源适配器的真实接入方式 | 本任务新增 |

---

## Pre-Development Checklist

在修改后端相关代码前，先确认本次改动落在哪一层：

- [ ] 如果改的是站点抓取、搜索、章节解析：先读 [Source Adapters](./source-adapters.md)
- [ ] 如果改的是 Flask API、缓存、聚合、下载入口：先读 `server.py` 对应代码，再参考本索引
- [ ] 如果改的是下载流程：先读 `download_manager.py`
- [ ] 如果改的是本地配置或收藏：先读 `config.py` / `favorites.py`
- [ ] 如果改动涉及共享数据结构，确认 `server.py`、`app.py`、`workers.py` 是否都依赖该结构

---

## 真实代码示例

### 示例 1：Flask 层只编排，不实现抓取细节

- `server.py:87` 的 `/api/search` 调用各源的 `search()`
- `server.py:161` 的 `_fetch_source_page()` 调用各源的 `get_popular()` / `get_latest()`

### 示例 2：GUI 与 Web 共享同一后端核心

- `app.py:12-17` 与 `server.py:11-16` 都导入 `sources`、`config`、`favorites`、`download_manager`
- `workers.py:77-79` 使用 `get_manga_info()` + `get_chapters()` 的统一接口

### 示例 3：源注册集中在 `sources/__init__.py`

- `sources/__init__.py:12-21` 返回可用源实例列表
- `sources/manga18.py` 虽然实现完整，但当前未被 `get_all_sources()` 注册

---

## 常见误区 / 不要套模板

- 不要在 spec 里假设项目已有 `Blueprint`、`service layer`、`repository layer`。
- 不要把 source 抓取细节直接塞进 `server.py`。
- 不要把当前 JSON 持久化说成数据库访问层。
- 不要忽略 `app.py` / `workers.py` 对共享接口的依赖；后端接口结构变化不只影响 Flask。

---

## Quality Check

完成后端改动后，至少自查：

- [ ] 是否遵循当前共享模块结构，而不是临时新增一套并行架构
- [ ] 是否复用了 `sources/base.py`、`download_manager.py` 等现有入口
- [ ] 是否保持 `search` / `info` / `chapters` / `images` 数据结构兼容
- [ ] 是否检查了 `sources/__init__.py` 的注册状态
- [ ] 文档是否描述真实代码现状，而不是理想化目标
