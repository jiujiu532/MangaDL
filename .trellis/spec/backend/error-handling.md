# Error Handling

> 当前项目以“保活优先”为主，广泛使用 `try/except Exception`，少量位置仍存在 `bare except`。

---

## 总览

这个仓库当前 **没有统一的自定义异常体系**，也没有 Flask 全局 error handler。真实风格更接近：

1. **抓取/下载/缓存等外围 IO 出错时尽量兜住，不让整个流程崩掉**
2. **路由层按场景决定返回空结果、`{"error": ...}`，或 400/500**
3. **后台回调、预热、缓存清理等非关键路径常直接吞异常保活**

因此，当前 error handling 文档记录的是“在哪些地方宽松兜底、哪些地方向用户显式返回错误”的现实，而不是理想化的分层异常设计。

---

## 当前错误类型现状

### 1. 没有项目级自定义异常类

仓库里现在主要直接处理原生异常：

- 网络错误
- HTML 解析/数据提取错误
- `ValueError` / `TypeError`
- JSON 读写错误
- 文件系统错误

调用方通常并不区分具体异常类型，而是统一转成：

- 空列表 / `False`
- `task.error = str(e)`
- `jsonify({"error": str(exc)})`

### 2. 下载状态通过字段表达，而不是异常类型表达

下载失败主要不是靠抛特定异常通知上层，而是靠 `DownloadManager` 修改任务状态：

- `TaskStatus.FAILED`
- `task.error`
- `task_log.emit("[ERROR] ...")`

真实代码：

- `download_manager.py:309-314`：无图片时置为 `FAILED`
- `download_manager.py:388-391`：总兜底异常写入 `task.error`

---

## 主要处理模式

## 1. 广泛使用 `try/except Exception`

这是当前后端真实主流写法，不是例外。

典型场景：

- 单个 source 失败不影响其他 source：`web/routes_sources.py:36-43`
- 收藏追更单项失败返回状态对象而不是中断整个批量：`web/routes_favorites.py:79-83`
- 下载流程中单章节失败不拖垮整个下载线程：`download_manager.py:291-395`
- GUI worker 抓取失败通过 signal 返回错误：`workers.py:19-26`、`workers.py:75-81`

适用心智：**这是一个面向网络抓取的不稳定 IO 项目，容错优先级高于异常精细分类。**

## 2. 某些回调/后台动作会直接吞异常保活

当前有不少“异常发生了也不要打断主流程”的位置，典型包括：

- 配置/收藏 JSON 读写：`config.py:48-49`、`config.py:56-57`、`favorites.py:35-36`、`favorites.py:43-44`
- 简易 signal 回调：`download_manager.py:37-42`
- 下载完成后更新收藏历史：`web/state.py:62-73`
- source 预热缓存：`web/state.py:78-85`
- 批量检测中的单 future 超时或失败：`web/routes_sources.py:143-147`、`web/routes_favorites.py:112-119`

这些位置的共同特点：

- 失败通常不是主业务硬前置条件
- 目标是“页面继续用、下载继续跑、其他源继续返回”
- 当前仓库宁可牺牲可观测性，也不愿因为辅助逻辑异常导致整体中断

## 3. 少量位置仍存在 `bare except`

当前仓库还保留了两处值得明确记录的 `bare except`：

- `download_manager.py:514-515`
- `download_manager.py:530-531`

它们都位于 fallback 下载路径中，语义是：

- 备用源某张图片失败时直接跳过
- 整个备用源尝试异常时继续尝试下一个备用源

这类写法体现的是“故障转移链路不要被单点异常打断”。写 spec 时要如实记录，不要假装仓库已经完全禁用了 `bare except`。

---

## API 路由返回错误的真实模式

当前 Flask API **没有统一错误响应中间件**，而是各路由自行决定返回形态。

### 1. 参数缺失 / 调用前置条件不满足 → 返回 400

真实例子：

- `web/routes_sources.py:182-183`：`/api/speed-test` 参数不完整时返回 `{"error": "bad params"}, 400`
- `web/routes_sources.py:206-207`：`/api/detail` 缺少 `url` 返回 `400`
- `web/routes_sources.py:220-221`：`/api/chapter-images` 缺少 `url` 返回 `400`
- `web/routes_download.py:84-85`：zip 下载没章节返回 `400`
- `web/routes_favorites.py:191-192`：追更 zip 没有下载项返回 `400`

### 2. 外部抓取或处理失败 → 返回 500 + 错误文本

真实例子：

- `web/routes_sources.py:209-214`：详情抓取失败返回 `{"error": str(exc)}`, 500`
- `web/routes_sources.py:223-235`：章节图片抓取失败返回 `{"error": str(exc)}`, 500`

这说明当前 API 没有错误码枚举，也没有稳定的机器可读 `code` 字段；前端更多是展示自然语言错误消息。

### 3. 可降级的接口返回空结果或状态对象，不一定报 500

真实例子：

- `web/routes_sources.py:26-27`：空查询直接返回空列表
- `web/routes_sources.py:42-43`：单源搜索异常时返回该源空结果
- `web/routes_sources.py:101-103`、`135-137`：跨源探测把异常折叠成 `offline` / `error` 状态对象
- `web/routes_favorites.py:82-83`：单个收藏项检查失败返回 `{status: "error", message: ...}`，整个批量继续
- `web/routes_favorites.py:263-276`：快速检查异常时直接按“无更新”处理

也就是说：**批量接口更常把错误内联进结果对象，而不是让整个 HTTP 请求失败。**

---

## 下载与后台流程的处理原则

### 1. 单章节失败不等于全局失败

`DownloadManager` 的核心策略是把异常限制在章节维度：

- `download_manager.py:257-264`：预取失败只记日志并缓存空列表
- `download_manager.py:305-307`：预取失败后再同步抓一次，做降级
- `download_manager.py:372-386`：全部图片失败时才标记章节失败
- `download_manager.py:380-383`：主源失败再尝试 fallback source

### 2. 单图片失败允许重试，仍失败则跳过

真实代码：

- `download_manager.py:336-350`：单图最多重试 3 次
- 如果仍失败，不抛到全局，而是让该 future 返回 `False`

### 3. 回调失败不能反噬下载主线程

`SimpleSignal.emit()` 中的异常会被吞掉：`download_manager.py:37-42`。

这保证了 UI/Web 的日志回调、状态回调有问题时，不会让下载线程本体停止。

---

## 什么时候会“吞异常保活”

当前代码里，以下情况通常允许吞异常：

1. **缓存预热、封面预取、后台 preload** 这种辅助手段
2. **单个 source / 单个收藏项 / 单个章节** 的失败，不应拖垮整个批处理
3. **回调通知**，主流程已经完成核心动作，只差刷新 UI 或写日志
4. **本地 JSON 读写**，项目倾向于“不阻塞启动/操作”

相反，以下情况更倾向于显式返回错误：

1. HTTP 路由参数本身不合法
2. 单个详情页、章节图片页等前端明确依赖的接口失败
3. 下载任务本身已经无法继续，需要把失败状态暴露给前端

---

## 当前应遵循的现实做法

### 可接受

- 在网络抓取、多源聚合、批量遍历中继续使用 `try/except Exception` 做单项容错
- 在 API 中返回当前已有风格的 `{"error": "..."}` 或结果对象内 `status/message`
- 在后台保活逻辑里吞异常，但最好至少留下现有风格的日志/提示
- 将“是否失败”写进状态字段，而不是依赖上层统一异常框架

### 应避免

- 假设仓库已经有全局异常中间件或统一业务异常类
- 在共享模块里随意改抛异常语义，导致 `web/`、`app.py`、`workers.py` 同时失配
- 为了“代码更干净”去掉当前必要的容错包裹，结果一个 source 异常拖垮全局
- 无理由新增更多 `bare except`；仓库虽然存在，但仅在极少数 fallback 保活路径中出现

---

## 常见问题 / 风险点

- 过多 `except Exception: pass` 会让真实错误难排查，尤其是 `config.py`、`favorites.py` 的静默失败。
- 当前错误响应格式不统一，前端调用时要按接口逐个适配。
- `bare except` 仍存在于 fallback 分支，未来若做治理，需要先确认不能破坏“继续尝试其他源”的保活语义。
