# Source Adapters 规范

> 适用于 `sources/` 目录下的漫画源适配器实现。这里记录的是当前仓库**已经在使用**的接入方式，不是理想化抽象层设计。

---

## 适用范围

当前已存在的 source adapter：

- `sources/base.py`
- `sources/madara.py`
- `sources/manhwahub.py`
- `sources/mangadna.py`
- `sources/xtoon.py`
- `sources/manga18.py`
- `sources/__init__.py`

这些模块同时被以下代码复用：

- `server.py`：Web API 搜索、热门/最新列表、详情抓取、下载
- `app.py`：GUI 搜索与详情展示
- `workers.py`：线程 worker 中的 `search()` / `get_manga_info()` / `get_chapters()` 调用
- `download_manager.py`：下载阶段调用 `get_chapter_images()` / `download_image()`

所以 source adapter 的接口一旦变化，会同时影响 Web、GUI、下载流程三个方向。

---

## 基类要求

### 新增漫画源必须继承 `MangaSource(ABC)`

真实基类定义在 `sources/base.py:40`：

```python
class MangaSource(ABC):
```

新增源不要自己定义一套无关接口，也不要只写普通工具函数后在外部拼装。现有代码都默认 source 是 `MangaSource` 子类实例。

### 必须实现的 4 个抽象方法

`sources/base.py` 当前强制要求实现以下 4 个方法：

1. `search(keyword: str) -> list[dict]`
2. `get_manga_info(manga_url: str) -> dict`
3. `get_chapters(manga_url: str, manga_id: str = None) -> list[dict]`
4. `get_chapter_images(chapter_url: str) -> list[str]`

对应定义见：

- `sources/base.py:52-55`
- `sources/base.py:57-60`
- `sources/base.py:62-65`
- `sources/base.py:67-69`

补充说明：

- `get_popular()` / `get_latest()` 在基类里有默认空实现，不是抽象方法。
- 但当前所有已注册源都实现了 `get_popular()` 和 `get_latest()`，因为 `server.py` 的列表接口会直接调用它们。

---

## HTTP 请求规范

### 统一使用基类提供的 `self.session`

`sources/base.py` 中 `_make_session()` 已经配置了：

- 默认请求头 `HEADERS`
- `requests.Session()`
- `HTTPAdapter`
- keep-alive
- retry（`Retry(total=3, backoff_factor=0.1, status_forcelist=[500, 502, 503, 504])`）
- 连接池（`pool_connections=80`, `pool_maxsize=150`）

基类 `__init__()` 会把 session 挂到实例上：

```python
self.session = _make_session()
```

因此新增源时：

- 必须使用 `self.session.get(...)` / `self.session.post(...)`
- **不要自行 `requests.get(...)` / `requests.post(...)`**
- **不要自己 new 一个新的 `requests.Session()`**，否则会绕过现有连接池和重试配置

真实例子：

- `sources/madara.py:26` 使用 `self.session.get(...)`
- `sources/madara.py:118` 使用 `self.session.post(...)`
- `sources/manhwahub.py:29`、`47`、`76` 都使用 `self.session.get(...)`
- `sources/mangadna.py:20` 使用 `self.session.get(...)`
- `sources/xtoon.py:65`、`87`、`127`、`172` 使用 `self.session.get(...)`
- `sources/manga18.py:28`、`61`、`92`、`111`、`131` 使用 `self.session.get(...)`

### 可以在现有 `self.session` 基础上补充 headers

如果站点有额外要求，可以像 `sources/manga18.py:18-24` 那样，在 `super().__init__()` 之后更新 `self.session.headers`，但仍然复用同一个 session。

`sources/xtoon.py:187-193` 也展示了另一种现状：下载图片时临时覆写 `Referer` headers，但底层仍然走 `self.session.get(...)`。

### 当前代码中的例外值得注意

`workers.py:118-119` 的健康检查直接用了 `requests.get(...)`，它不在 `sources/` 目录里，也没有复用基类 session。写 spec 时不把它当成新增 source 的范式，反而应视为 source 适配层之外的特殊调用。

---

## 命名与文件组织

### 文件命名

新增源文件放在：

```text
sources/<源名小写>.py
```

现有例子：

- `sources/madara.py`
- `sources/manhwahub.py`
- `sources/mangadna.py`
- `sources/xtoon.py`
- `sources/manga18.py`

### 类命名

类名使用驼峰（PascalCase），并以 `Source` 结尾。

现有例子：

- `MadaraSource`
- `ManhwaHubSource`
- `MangaDNASource`
- `XToonSource`
- `Manga18Source`

### 源元信息命名

source 类通常提供：

- `name`
- `base_url`
- `icon`

两种真实写法都存在：

1. **类属性固定值**
   - `sources/manhwahub.py:13-15`
   - `sources/mangadna.py:14-16`
   - `sources/xtoon.py:12-14`
   - `sources/manga18.py:14-16`

2. **构造函数参数化**
   - `sources/madara.py:14-18`
   - `sources/__init__.py:15-17` 用同一个 `MadaraSource` 实例化多个站点

如果多个站点共用同一种 CMS 结构，优先参考 `MadaraSource` 这种“一个实现 + 多个实例”的复用方式，不要复制一份几乎相同的文件。

---

## 方法返回结构约定

这些结构已经被 `server.py`、`workers.py`、`app.py`、`download_manager.py` 直接消费，新增源必须兼容。

### 1. `search()` 返回 `list[dict]`

约定结构：

```python
[
    {
        "title": str,
        "url": str,
        "cover": str | None,
        "genres": str,
    }
]
```

来源依据：

- `sources/base.py:53-55` 的注释
- `sources/madara.py:36-42`
- `sources/manhwahub.py:37-39`
- `sources/mangadna.py:50-53`
- `sources/xtoon.py:56-58`
- `sources/manga18.py:41-47`

注意事项：

- `genres` 当前真实现状通常是**字符串**，不是 `list[str]`
- 没有类型信息时，多数源返回空字符串 `""`
- `server.py:105-106` / `workers.py:21-24`、`59-62` 会再附加 `_source`、`_source_name`、`_source_icon` 等运行时字段，但这些不是 adapter 原始返回的必填字段

### 2. `get_manga_info()` 返回 `dict`

约定结构：

```python
{
    "title": str,
    "manga_id": str | None,
    "url": str,
    "cover": str | None,
    "description": str,
    "genres": str,
}
```

来源依据：

- `sources/base.py:58-60` 的注释
- `sources/madara.py:104-107`
- `sources/manhwahub.py:140-143`
- `sources/mangadna.py:135-138`
- `sources/xtoon.py:120-123`
- `sources/manga18.py:105-108`

现状说明：

- 只有 `MadaraSource` 比较稳定地返回 `manga_id`，因为它会给后续 AJAX 章节接口使用
- 其他源普遍返回 `manga_id: None`
- `genres` 在非 Madara 源里很多时候为空字符串

### 3. `get_chapters()` 返回 `list[dict]`

约定结构：

```python
[
    {
        "title": str,
        "url": str,
        "date": str,
    }
]
```

来源依据：

- `sources/base.py:63-65` 的注释
- `sources/madara.py:130-134`、`147-150`
- `sources/manhwahub.py:165-168`
- `sources/mangadna.py:166`
- `sources/xtoon.py:161`
- `sources/manga18.py:125`

关键约束：

- 基类注释已经标明章节列表应为“**正序**”
- 当前各实现也都在末尾执行 `chapters.reverse()`，例如：
  - `sources/madara.py:153`
  - `sources/manhwahub.py:170`
  - `sources/mangadna.py:167`
  - `sources/xtoon.py:167`
  - `sources/manga18.py:127`

所以新增源如果抓到的是站点默认倒序列表，也要在返回前翻转成正序。

### 4. `get_chapter_images()` 返回 `list[str]`

约定结构：

```python
["https://..."]
```

来源依据：

- `sources/base.py:68-69`
- `download_manager.py:258`、`307` 直接把返回值当作图片 URL 列表使用

现有实现共性：

- 先用站点特定 selector 提取图片
- 再过滤 logo、gif、占位图等无效资源
- 必要时补全相对路径为绝对 URL
- 多数实现会做去重

例子：

- `sources/madara.py:161-172`
- `sources/manhwahub.py:178-183`
- `sources/mangadna.py:176-187`
- `sources/xtoon.py:177-184`
- `sources/manga18.py:135-147`

---

## 已有实现里的真实模式

### 模式 1：同一 CMS 抽成通用 adapter

`sources/madara.py` 不是为单站点写的，而是抽象了 WordPress Madara / WP-Manga 类站点；`sources/__init__.py:15-17` 直接实例化三个站点。

适用场景：

- HTML 结构基本一致
- 搜索、详情、章节、图片读取逻辑接近
- 仅 `base_url`、`name`、`icon` 不同

### 模式 2：单站点 adapter 内允许多级 fallback

由于目标站常变，现有实现允许在单个方法里写“主方案 + fallback 方案”：

- `sources/manhwahub.py:20-94` 的 `search()` 有 3 种策略
- `sources/mangadna.py:25-67` 的 `search()` 有主选择器 + fallback
- `sources/manga18.py:48-57` 的 `search()` 有 fallback

这类写法在当前项目中是正常现状，不需要强行抽成更复杂的 parser framework。

### 模式 3：章节和图片结果通常要去重

现有源经常维护 `seen = set()` 去重，防止重复卡片、重复章节、重复图片：

- `sources/manhwahub.py:151-163`
- `sources/mangadna.py:149-166`
- `sources/xtoon.py:21-29`、`132-140`
- `sources/manga18.py:115-125`
- `sources/madara.py:166-171`

新增源如果站点结构容易重复输出，应保留这一习惯。

---

## 接入检查项

新增 source adapter 时，至少检查以下事项：

- [ ] 文件是否位于 `sources/<小写名>.py`
- [ ] 类是否继承 `MangaSource`
- [ ] 是否实现 `search` / `get_manga_info` / `get_chapters` / `get_chapter_images`
- [ ] 是否统一使用 `self.session`
- [ ] `search()` / `get_manga_info()` / `get_chapters()` 返回结构是否与现有代码兼容
- [ ] `get_chapters()` 是否保证正序
- [ ] 是否在 `sources/__init__.py` 的 `get_all_sources()` 中注册

### 当前仓库里的真实遗漏示例

`sources/manga18.py` 文件存在，`Manga18Source` 也已实现完整，但 `sources/__init__.py:12-21` 的 `get_all_sources()` 目前没有把它加入返回列表。

这说明当前项目里“**文件写好了但没注册**”是真实会发生的遗漏。以后新增源时，注册步骤必须单独核对。

---

## 不要这样做

- 不要在 source 文件里直接使用裸 `requests.get(...)`
- 不要自己重新创建新的 `Session`
- 不要返回与现有调用方不兼容的数据结构，例如把 `genres` 改成 list、把章节项改成自定义对象
- 不要把新站点逻辑直接写进 `server.py`
- 不要忘记 `sources/__init__.py` 注册
- 不要假设所有站点都支持 `manga_id`；只有确实需要时才提取

---

## 真实代码参考点

- 抽象基类：`sources/base.py`
- 通用 CMS 复用：`sources/madara.py`
- 多策略搜索 fallback：`sources/manhwahub.py`
- 自定义 CMS + 章节过滤：`sources/mangadna.py`
- 特殊 Referer 图片下载：`sources/xtoon.py`
- 已实现但未注册的源：`sources/manga18.py`
- 源注册入口：`sources/__init__.py`

---

## Quality Check

写完或修改 source adapter 后，快速自查：

- [ ] 抽象方法是否全部实现
- [ ] 网络请求是否全部走 `self.session`
- [ ] 返回结构是否兼容现有 `server.py` / `workers.py` / `download_manager.py`
- [ ] 是否处理了重复链接、占位图、相对路径等站点噪音
- [ ] 是否已经在 `sources/__init__.py` 注册
