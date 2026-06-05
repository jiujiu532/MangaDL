# Logging Guidelines

> 当前项目没有统一 `logging` 框架，真实现状是 `print`、下载事件回调、Web 侧 `log_buffer`、Qt signal 并存。

---

## 总览

这个仓库的日志体系是逐步演化出来的，目前至少有 4 套并存方式：

1. **直接 `print(...)`**：启动提示、缓存预热、预取进度
2. **`DownloadManager.task_log.emit(...)`**：下载过程事件流
3. **Web 侧 `state.log_buffer`**：把下载日志缓存给 `/api/download/logs`
4. **GUI / Worker signal**：不是严格日志，而是把错误或结果通过 signal 往 UI 层传

真实代码入口：

- `server.py:19`：启动时 `print`
- `download_manager.py:125-128`：定义 `task_log` / `task_updated` / `all_done`
- `web/state.py:49-56`：把 `task_log` 写进 `log_buffer`
- `web/routes_download.py:123-126`：通过 API 返回日志缓冲
- `workers.py:25-26`、`workers.py:52-53`、`workers.py:80-81`：错误通过 signal 往 GUI 抛

当前 spec 要记录的是这种混合模式，不要写成“本项目统一使用 Python logging”。

---

## 现有日志通道

### 1. `print`：偏启动信息、后台预热、开发期可见输出

真实例子：

- `server.py:19`：启动 Web 服务时输出地址
- `web/state.py:83-85`：预热热门/最新列表时输出成功或 warning
- `web/image_cache.py:92`、`web/image_cache.py:146`：封面/阅读器预取进度直接 `print`

特点：

- 面向控制台开发者，而不是前端用户
- 没有统一格式、时间戳、模块名
- 适合一次性提示，不适合复杂追踪

### 2. `task_log.emit`：下载流程的主事件流

下载相关最核心的“日志”其实都走 `DownloadManager.task_log`：

- `download_manager.py:250`：`[PREFETCH]` 开始预取
- `download_manager.py:262`：预取失败
- `download_manager.py:298`：`[START]` 章节开始
- `download_manager.py:306`：`[FALLBACK]` 预取缓存失效后同步获取
- `download_manager.py:374-386`：`[OK]` / `[PARTIAL]` / `[FAILOVER]` / `[FAIL]`
- `download_manager.py:391`：`[ERROR]` 总兜底错误
- `download_manager.py:436-439`：`[ADAPTIVE]` 并发调节
- `download_manager.py:487`、`527-528`：备用源下载切换与成功

这些消息本质上是字符串事件，不是结构化日志对象。

### 3. Web 侧 `log_buffer`：SSE/轮询风格前端消费缓存

虽然当前接口是 `GET /api/download/logs` 返回数组，但它承担的是“前端持续查看下载日志”的角色。

真实代码：

- `web/state.py:22-23`：维护 `log_buffer` 与锁
- `web/state.py:52-56`：追加日志，最多保留 200 条
- `web/routes_download.py:123-126`：复制缓冲区后返回给前端

特点：

- 是 **内存缓冲**，不是持久化日志
- 有上限，旧日志会被丢弃
- 生命周期随进程结束而消失

### 4. signal callback：面向 GUI 的事件反馈

GUI 侧不少“日志语义”并不落文本，而是直接发 signal：

- `workers.py:25-26`：搜索失败发 `error`
- `workers.py:52-53`：多源搜索失败发 `source_error`
- `workers.py:80-81`：详情获取失败发 `error`
- `app.py:726-817` 一带会连接 `dl_manager.task_log` 到 UI（通过 `_connect_dl_signals` / `_on_task_log`）

这类通道更像“状态通知”，但在当前项目里也承担了一部分日志职责。

---

## 当前的“级别”不是标准 logging level

项目没有系统性使用 `debug/info/warning/error` 枚举，而是用消息前缀表达语义。

### 真实常见前缀

- `[START]`：开始处理某章节或任务
- `[PREFETCH]`：预取阶段事件
- `[FALLBACK]`：降级路径
- `[FAILOVER]` / `[FAILOVER OK]`：切换备用源
- `[OK]`：成功完成
- `[PARTIAL]`：部分成功，但流程继续
- `[FAIL]`：明确失败
- `[ERROR]`：异常兜底
- `[ADAPTIVE]`：并发调整信息
- `[追更]`：收藏追更批量下载开始

真实代码：

- `download_manager.py:250-282`
- `download_manager.py:298-391`
- `download_manager.py:436-439`
- `web/routes_favorites.py:157-158`

### 如何理解这些前缀

- `[OK]` / `[START]` / `[PREFETCH]` 更接近 `info`
- `[PARTIAL]` / `[FALLBACK]` / `[FAILOVER]` 更接近 `warning`
- `[FAIL]` / `[ERROR]` 更接近 `error`

但这是语义映射，不代表项目已有正式 logging level 机制。

---

## 应记录什么

### 1. 下载过程关键节点

当前最强调的日志领域就是下载：

- 任务开始
- 预取是否成功
- 是否走降级/备用源
- 成功数量与失败数量
- 自适应并发调整

真实例子见 `download_manager.py` 上述各段。

### 2. 追更与下载历史

这里有一类“日志”不是控制台文本，而是业务日志，直接持久化到 `favorites.json`：

- `favorites.py:204-223`：`update_log` / `download_log`
- `web/routes_download.py:29-36`、`94-102`：手动下载写入 `download_log`
- `web/routes_favorites.py:168-182`、`210-224`：追更下载写入 `update_log` 与 `download_log`

它们是“可回看业务记录”，不能和 `print` / `log_buffer` 混为一谈。

### 3. 后台预热/缓存行为

当前也会记录预热缓存与封面缓存进度：

- `web/state.py:83-85`
- `web/image_cache.py:92`
- `web/image_cache.py:146`

这类信息主要用于观察后台行为，而不是用户可见审计。

---

## 当前不具备的能力

以下都不是当前仓库现状：

- 统一 `logging.getLogger(__name__)`
- 结构化 JSON logging
- 自动时间戳 / trace id / request id
- 文件日志轮转
- 统一的 error/warn/info formatter

写 spec 或改代码时，不要默认这些机制已经存在。

---

## 可接受的改动方式

### 可接受

- 继续在下载事件里使用 `task_log.emit("[TAG] ...")`
- Web 侧继续通过 `state.log_buffer` 暴露最近下载日志
- 启动提示、预热提示继续用轻量 `print`
- 对业务回放需求，优先写入 `favorites.py` 的 `update_log` / `download_log`

### 应避免

- 在一个改动里混入全新的日志框架，但不把旧通道一起迁完
- 把 `task_log` 的字符串格式随意改掉，导致 Web / GUI 展示逻辑失配
- 把本应进 `download_log` / `update_log` 的业务记录只打到控制台，导致历史不可追溯
- 假设 `log_buffer` 是持久化存储；它只是内存环形缓冲

---

## 风险与后续补充点

- `print`、`task_log`、业务日志三套体系边界不完全统一，排查问题时要分清“临时控制台输出”和“可回看历史”。
- 当前没有脱敏机制，不过仓库目前也几乎不处理用户敏感信息；后续若加账号/Token，不能直接沿用现有随手打印模式。
- `log_buffer` 最多 200 条，长时间下载时早期日志会被顶掉，这属于当前真实限制。
