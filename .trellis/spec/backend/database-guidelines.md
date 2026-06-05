# Database Guidelines

> 当前仓库没有传统数据库；这里记录的是“本地 JSON 文件持久化”的真实现状。

---

## 总览

这个项目目前 **无数据库、无 ORM、无 migration、无 repository layer**。

真实持久化方式只有两类：

1. **配置文件**：`config.py` 写入 `~/.manga_downloader/config.json`
2. **业务状态文件**：`favorites.py` 写入 `~/.manga_downloader/favorites.json`

也就是说，这里的“数据层”不是 SQL/NoSQL，而是进程内字典 + JSON 文件落盘。

真实代码入口：

- `config.py:8-9` 定义 `CONFIG_DIR` / `CONFIG_FILE`
- `config.py:33-56` 负责 `config.json` 的读写
- `favorites.py:10-11` 定义 `FAVORITES_FILE`
- `favorites.py:21-44` 负责 `favorites.json` 的读写

### 当前不存在的东西

以下能力目前都 **不存在**，写 spec 或改代码时不要假设已经有：

- SQLAlchemy / Peewee / Django ORM
- Alembic / migration 脚本
- 表结构、索引、事务
- repository / DAO / unit of work
- 独立数据库连接池

如果后续要引入真正数据库，那是架构演进，不属于当前仓库既有约定。

---

## 当前数据文件与职责

### `config.json`

由 `Config` 管理，主要保存运行配置：

- 下载目录：`download_dir`
- 并发设置：`chapter_concurrency`、`image_concurrency`
- 代理设置：`proxy_mode`、`proxy_host`、`proxy_port`
- UI/Web 共用设置：`theme`、窗口位置、搜索历史

真实例子：

- `config.py:11-25` 定义默认字段 `DEFAULTS`
- `web/routes_config.py:12-21` 将配置以 API 形式返回给前端
- `web/routes_config.py:23-33` 接收配置更新后回写到 `Config`

### `favorites.json`

由 `FavoritesManager` 管理，实际承担的不只是“收藏夹”，还包括业务日志和下载状态：

- 分组：`groups`
- 收藏项：`items`
- 追更日志：`update_log`
- 下载日志：`download_log`
- 每个收藏项中的 `download_history`

真实例子：

- `favorites.py:18` 初始化 `_data`
- `favorites.py:98-125` 更新单漫画 `download_history`
- `favorites.py:204-223` 维护 `update_log` / `download_log`
- `web/routes_favorites.py:168-182`、`web/routes_download.py:29-36` 在下载或追更时写入日志

---

## 读写模式

### 1. 启动时整文件读取到内存

`Config` 与 `FavoritesManager` 都是在实例化时一次性 `load()`，之后主要操作内存中的 `_data`。

真实代码：

- `config.py:29-31`：`__init__()` 中立即 `load()`
- `favorites.py:17-19`：`__init__()` 中立即 `load()`

### 2. 修改后整文件覆盖写回

当前没有增量更新、append-only log 或局部 patch；保存时直接 `json.dump(self._data, ...)` 覆盖整个文件。

真实代码：

- `config.py:51-56`
- `favorites.py:38-43`
- `favorites.py:270-285` 的导入最终也是修改内存后 `save()`

这意味着：

- 适合当前“小体量本地工具”场景
- 不适合把高频、超大体量数据继续堆进 JSON
- 新字段优先遵循“内存结构可序列化为 JSON”这一现实约束

### 3. 默认值合并而不是 schema migration

项目没有 migration，兼容旧版本数据的方式是 **load 时补默认字段**。

真实代码：

- `config.py:38-46`：读取旧配置后补齐新增字段，并顺手做低并发值升级
- `favorites.py:26-33`：确保 `groups` / `items` / `update_log` / `download_log` 都存在

所以新增字段时，当前惯例是：

1. 在默认结构里补字段
2. 在 `load()` 时兼容旧文件缺失字段
3. 允许旧文件在第一次成功保存后自然升级

---

## 命名与结构约定

这里没有表名/列名规范，真实约定是 **JSON key 命名**。

### 顶层 key

- 配置项使用 `snake_case`，例：`download_dir`、`proxy_mode`、`search_history`
- 收藏业务字段也使用 `snake_case`，例：`update_log`、`download_log`、`download_history`

### 嵌套对象

- 章节范围日志字段：`from_chapter`、`to_chapter`
- 下载历史字段：`last_chapter`、`chapters`、`last_updated`、`last_version`
- 追更/下载日志条目以普通 `dict` 表示，不存在专门 model class

真实代码：

- `favorites.py:103-106`、`favorites.py:192-197`：`download_history` 结构
- `web/routes_download.py:29-36`
- `web/routes_favorites.py:168-182`、`web/routes_favorites.py:217-224`

### 文件路径约定

- 所有本地持久化文件统一放在 `~/.manga_downloader/`
- 不写入项目仓库目录
- 导出文件例外，由用户选择路径，例如 `favorites.py:270-276`

---

## 常见修改方式

### 可接受的方式

- 给 `DEFAULTS` 或 `_data` 增加可 JSON 序列化的新字段
- 在 `load()` 中补齐旧文件缺失字段
- 在路由层通过现有 `Config` / `FavoritesManager` 接口读写
- 继续把轻量运行状态、用户偏好、历史记录落到这两个 JSON 文件

### 当前应避免的方式

- 在 `web/` 路由里直接自己打开 `config.json` / `favorites.json` 绕过管理类
- 把不可 JSON 序列化对象塞进 `_data`
- 假设有事务、回滚或并发写保护
- 写文档时把本地 JSON 描述成“database layer”或“ORM model”

---

## 当前风险与已知限制

### 1. 读写失败大多静默吞掉

`config.py` 和 `favorites.py` 的 `load()` / `save()` 都是 `except Exception: pass`。

真实代码：

- `config.py:48-49`、`config.py:56-57`
- `favorites.py:35-36`、`favorites.py:43-44`

这表示当前项目更偏向“配置损坏时不要阻塞主流程”，但代价是：

- JSON 损坏时不一定能从 UI/Web 直接发现
- 保存失败时不会自动暴露给调用方

### 2. 没有多进程/多实例一致性保证

当前代码假设单机、单用户、低竞争写入。若同时开多个进程实例，最后写入者可能覆盖前一个实例的修改。

### 3. 数据结构由代码隐式定义

项目没有 schema 文件，也没有字段校验器；真实 schema 以 `DEFAULTS`、`FavoritesManager._data` 和 API 写法为准。

---

## 不要套用数据库项目模板

- 不要新增“表结构命名规范”之类与现状无关的内容。
- 不要要求 migration 命令、seed、事务回滚。
- 不要为了“更像后端”就强行引入 repository 抽象包装 JSON 读写。
- 不要忽略 `app.py`、`web/`、`favorites.py`、`config.py` 是共享同一份本地数据文件这一现实。
