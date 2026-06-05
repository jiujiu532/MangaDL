# Quality Guidelines

> 当前项目的质量标准以“保持现有共享接口稳定 + 通过基础 Ruff 校验 + 不破坏 Web/GUI 共用模块”为主。

---

## 总览

这个仓库不是重测试、重静态约束的大型服务端工程；它更像一个 **本地漫画下载器的共享核心代码库**。因此质量要求的重点不是追求抽象完美，而是：

1. **不要破坏现有共享模块契约**
2. **在当前代码风格里做增量修改**
3. **通过已有的 Ruff 基础规则**
4. **尊重 `server.py` → `web/` 的模块边界**

---

## 现有质量基线

### 1. 已接入 Ruff，但规则较温和

当前 lint 配置见 `pyproject.toml`：

- `pyproject.toml:1-3`：`line-length = 120`，目标版本 `py39`
- `pyproject.toml:10-11`：只启用 `E4`、`E7`、`E9`、`F`

这说明当前 Ruff 主要覆盖：

- 语法错误
- 明显的 pycodestyle 问题
- 未定义名称、部分 import/运行时错误类问题

**没有**启用一大批更激进的规则，所以不要把仓库写成“全面严格 lint 驱动”的样子。

### 2. 当前 Ruff 配置较基础，历史代码仍保留不少宽松写法

例如：

- 大量 `except Exception`
- 少量 `bare except`
- `print` 日志
- 较长函数，如 `download_manager.py`、`web/routes_favorites.py`

因此评估改动时，应以“新改动不要明显变差”为主，而不是要求一次性把整个旧仓库重构到理想形态。

---

## 模块边界要求

### 1. `server.py` 现在是薄入口，不再承载 Flask 细节

真实代码：

- `server.py:1-21` 只负责兼容入口、启动浏览器、调用 `web.app`
- `web/app.py:14-30` 负责真正的 `Flask` app 创建与 route 注册

这意味着：

- 新的 Flask route、状态管理、缓存逻辑，应优先放 `web/`
- 不要再把大量实现逻辑重新塞回 `server.py`

### 2. `web/` 内部已经按职责拆分

真实边界：

- `web/app.py`：组装 app 与注册路由
- `web/state.py`：Web 侧共享状态单例
- `web/routes_*.py`：按领域拆分的路由文件
- `web/image_cache.py` / `listing_cache.py` / `zip_stream.py` / `utils.py`：辅助能力

可接受改动是沿着现有边界扩展，而不是重新引入一套并行结构。

### 3. 共享模块接口契约不能随意改

以下模块被 Web 和 GUI 共用：

- `config.py`
- `favorites.py`
- `download_manager.py`
- `sources/`
- `workers.py`（依赖 `sources/` 的既有接口）

例如：

- `web/state.py:14-20` 依赖 `Config` / `FavoritesManager` / `DownloadManager`
- `app.py` 与 `workers.py` 也直接使用这些共享接口
- `workers.py:20`、`77-78` 依赖 source adapter 的 `search()`、`get_manga_info()`、`get_chapters()`

所以任何对这些共享模块的入参、返回结构、字段名变更，都必须先检查 Web 与 GUI 双方是否仍兼容。

---

## 当前仓库里“可接受”的代码模式

### 1. 在现有模块里做就近修改

例如：

- 路由逻辑去 `web/routes_sources.py`、`web/routes_download.py`、`web/routes_favorites.py`
- Web 全局状态去 `web/state.py`
- 下载调度逻辑去 `download_manager.py`
- 配置/收藏持久化去 `config.py` / `favorites.py`

### 2. 以现有数据结构为准做兼容扩展

例如新增配置项、日志字段、下载状态字段时：

- 优先补默认值
- 兼容旧 JSON 文件
- 保持 API 已有字段含义不变

### 3. 接受“保活优先”的容错方式

对于 source 抓取、并发批量检查、下载失败回退等不稳定 IO，当前项目接受：

- `try/except Exception`
- 单项失败不影响整批
- 错误内联到结果对象或状态字段

这属于当前代码风格的一部分，不应在局部改动中随意反转。

---

## 当前应避免的模式

### 1. 破坏 `server.py` / `web/` 已有边界

应避免：

- 把新 route 重新写回 `server.py`
- 在 `server.py` 重建一套 app 状态、缓存、下载逻辑

### 2. 随意改共享接口契约

应避免：

- 改 `sources/base.py` 约定的方法签名，却不同步所有 source adapter、GUI worker、Web route
- 修改 `FavoritesManager` / `Config` 的返回结构，导致前端或 GUI 读取旧字段失败
- 改 `DownloadManager.task_log`、`task_updated` 等回调语义，导致 `web/state.py` 或 GUI 信号连接失效

### 3. 为了“看起来更规范”强行过度抽象

当前项目没有 service/repository 分层，也没有 dependency injection 体系。应避免：

- 因小改动引入大批新抽象层
- 复制一套与 `web/` 并行的新后端架构
- 用理想化模式替换当前已广泛复用的共享模块

### 4. 把旧问题一次性扩散

仓库里已经存在一些历史宽松写法，但不意味着新改动可以继续无边界复制。比如：

- 旧代码有 `bare except`，不代表新位置也应该继续加
- 旧代码有 `print`，也不代表所有新业务日志都应该只打控制台

原则是：**与现状兼容，但不要让质量继续明显下滑。**

---

## 测试与验证现实

### 1. 当前主要依赖静态检查和手动回归

仓库里目前没有成体系的自动化测试约束文档；真实更常见的是：

- 跑 Ruff
- 手动验证 Flask Web 功能
- 手动验证下载、收藏、追更、source 可用性

### 2. 后端改动至少要自查这些跨层影响

- Web 路由是否仍能调用共享模块
- `favorites.json` / `config.json` 兼容旧数据
- 下载日志、追更日志、状态缓冲是否仍能更新
- source adapter 返回结构是否仍符合 Web 与 GUI 的共同预期

### 3. 有些改动天然需要双入口视角检查

如果改到这些区域，不能只看 Flask：

- `sources/`
- `download_manager.py`
- `config.py`
- `favorites.py`

因为 `app.py` / `workers.py` 也依赖它们。

---

## Reviewer / 自查清单

### 代码边界

- [ ] 是否保持 `server.py` 仍是薄入口
- [ ] 新实现是否放在 `web/` 现有职责位置，而不是绕开模块边界

### 共享契约

- [ ] 是否检查了 `config.py`、`favorites.py`、`download_manager.py`、`sources/` 的调用方
- [ ] 是否保留了已有返回字段、signal/callback、状态字段含义

### 兼容与风险

- [ ] 新字段是否兼容旧 JSON 数据
- [ ] 批量/并发流程里是否仍保持单项失败不拖垮全局
- [ ] 是否避免把单个 source 的异常升级成整批请求失败

### 基础质量

- [ ] 是否满足当前 Ruff 规则
- [ ] 是否没有引入明显无用 import、未定义变量、语法错误
- [ ] 是否避免无必要的大规模重构

---

## 一句话判断标准

在这个仓库里，高质量改动通常长这样：**沿用 `web/` + 共享核心模块的现有结构，小步修改，不破坏接口契约，能过基础 Ruff，并且不把单点异常放大成全局故障。**
