# Directory Structure

> 当前仓库后端代码的真实组织方式。适用于 Flask Web 入口，以及它复用的共享核心模块。

---

## Overview

这个项目的后端不是传统的 `routes/services/repositories` 分层，而是：

- `server.py`：兼容入口，只负责导出和启动 Flask app
- `web/`：Flask Web 侧实现细节
- 根目录共享模块：`sources/`、`download_manager.py`、`config.py`、`favorites.py`

关键原则：

- Web 侧编排逻辑放到 `web/`
- 站点抓取逻辑继续留在 `sources/`
- 下载核心继续留在 `download_manager.py`
- 本地配置/收藏持久化继续留在 `config.py` / `favorites.py`

不要为了“看起来更标准”再造一套 service / repository 架构。

---

## Directory Layout

```text
.
├── server.py                  # Flask 兼容入口；导出 app / create_app
├── web/
│   ├── __init__.py            # 对外导出 app, create_app
│   ├── app.py                 # Flask app 创建与 routes 装配
│   ├── state.py               # Config / Favorites / Sources / DownloadManager 单例与共享缓存状态
│   ├── utils.py               # Web 侧通用 helper（源解析、章节范围、文件名、统计等）
│   ├── listing_cache.py       # 热门/最新列表池、后台扩展、去重
│   ├── image_cache.py         # 图片代理缓存、预取、session 复用
│   ├── zip_stream.py          # 浏览器流式 ZIP 下载封装
│   ├── routes_pages.py        # 页面路由
│   ├── routes_sources.py      # 搜索、热门、最新、详情、源健康等 API
│   ├── routes_images.py       # 图片代理与批量预取 API
│   ├── routes_download.py     # 手动下载、下载状态、下载历史 API
│   ├── routes_favorites.py    # 收藏、追更、追更 ZIP API
│   └── routes_config.py       # 配置、健康检查、统计 API
├── sources/                   # 漫画源 adapter
├── download_manager.py        # 下载核心
├── config.py                  # 本地配置 JSON
└── favorites.py               # 收藏与下载/追更日志 JSON
```

---

## Module Organization

### 1. `server.py` 必须保持薄入口

允许内容：

- `sys.path` 兼容处理
- `from web import app, create_app`
- `__main__` 启动逻辑

不应再把以下实现细节放回 `server.py`：

- `@app.route(...)` 路由主体
- 大段缓存/线程/预取逻辑
- ZIP 流式下载实现

### 2. `web/state.py` 放共享 Web 运行态

适合放这里的内容：

- Flask 侧共享单例
- 日志缓冲区
- 列表缓存、源健康缓存
- 图片缓存与下载中状态

如果某个 helper 需要读写这些共享状态，优先通过 `state` 传递，不要重新定义新的全局变量。

### 3. `web/routes_*.py` 按领域拆路由

新增 API 时，优先按领域落点：

- 页面相关 → `routes_pages.py`
- 搜索/详情/源相关 → `routes_sources.py`
- 图片代理/预取 → `routes_images.py`
- 下载相关 → `routes_download.py`
- 收藏/追更相关 → `routes_favorites.py`
- 配置/健康/统计 → `routes_config.py`

如果只是新增某个领域内的一条 API，不要新建一个只有单个函数的新模块。

### 4. 可复用的 Web helper 放到独立模块

出现以下情况时，优先抽到独立 helper，而不是继续堆在 routes 文件里：

- 多个路由共享同一段缓存逻辑
- 多个路由共享同一段 ZIP/下载辅助逻辑
- 同类线程/并发逻辑需要单独维护

当前已存在的真实落点：

- 列表池 → `listing_cache.py`
- 图片缓存 → `image_cache.py`
- ZIP 流 → `zip_stream.py`
- 小型通用工具 → `utils.py`

---

## Naming Conventions

- Web 目录文件名使用小写下划线：`routes_download.py`
- 路由模块统一使用 `register(app, state)` 暴露注册入口
- 涉及共享运行态的函数，参数里显式接收 `state`
- 仅兼容入口使用 `app` 顶层导出；实现模块不要依赖跨文件隐式全局

---

## Examples

- `web/app.py`：薄装配层示例
- `web/routes_download.py`：下载 API 与 ZIP 响应编排示例
- `web/listing_cache.py`：把重型缓存/后台扩展逻辑从路由文件下沉的示例
