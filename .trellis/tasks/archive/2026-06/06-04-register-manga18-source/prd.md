# 注册 manga18 漫画源

## Goal

修复 `sources/manga18.py` 已实现但未生效的问题，让 `Manga18Source` 被 `sources/__init__.py` 正式接入到全局漫画源列表中。这样 Web 端和其他复用 `get_all_sources()` 的调用方都能实际使用 Manga18 这个漫画源，而不是继续保留死代码。

## What I already know

- `sources/manga18.py` 已定义 `Manga18Source`，并实现了 `search`、`get_manga_info`、`get_chapters`、`get_chapter_images` 等核心方法。
- `sources/__init__.py` 当前只导入了 `MadaraSource`、`ManhwaHubSource`、`MangaDNASource`、`XToonSource`，没有导入 `Manga18Source`。
- `sources/__init__.py` 的 `get_all_sources()` 当前也没有返回 `Manga18Source()` 实例。
- `server.py` 通过 `from sources import get_all_sources` 构造全局 `sources` 列表，因此这里只要没注册，Web API 就永远不会使用 Manga18。
- 当前修复范围非常明确，只需要补齐导入和注册，不涉及 adapter 本身逻辑修改。

## Assumptions

- `Manga18Source` 当前实现已经满足 `MangaSource` 接口契约，不需要在本任务中额外修改其抓取逻辑。
- 现有调用方对新增一个源实例是兼容的，不需要额外调整数据结构。

## Open Questions

- 无阻塞问题。当前需求已足够明确，可直接进入实现。

## Requirements

- 在 `sources/__init__.py` 中导入 `Manga18Source`。
- 在 `sources/__init__.py` 的 `get_all_sources()` 返回列表中加入 `Manga18Source()`。
- 保持现有已注册源的顺序和风格一致，不做无关重构。
- 不修改 `sources/manga18.py` 本体逻辑。

## Acceptance Criteria

- [ ] `sources/__init__.py` 顶部存在 `Manga18Source` 的导入。
- [ ] `sources/__init__.py` 的 `get_all_sources()` 返回列表包含 `Manga18Source()`。
- [ ] `get_all_sources()` 调用结果中包含名称为 `Manga18` 的源实例。
- [ ] 本次修改不影响其他已注册漫画源。

## Definition of Done

- 代码修改完成且只涉及本次 bug 修复范围。
- 至少完成一次针对源注册结果的验证。
- 如产生新的真实规范认知，评估是否需要同步到 `.trellis/spec/`。

## Technical Approach

直接修复 `sources/__init__.py`：

1. 增加 `from .manga18 import Manga18Source`
2. 在 `get_all_sources()` 返回列表末尾加入 `Manga18Source()`
3. 运行最小验证，确认 `get_all_sources()` 已包含该源

这是与当前仓库结构最一致的修复方式，改动最小，也最符合现有 source 注册模式。

## Decision (ADR-lite)

**Context**: `Manga18Source` 已实现但未注册，导致功能不可达。

**Decision**: 通过补充 `sources/__init__.py` 的导入与实例注册来修复，而不是改动 source adapter 本体或新增动态发现机制。

**Consequences**: 改动小、风险低、行为清晰；同时保留当前“集中注册所有源”的项目模式。

## Out of Scope

- 不修改 `sources/manga18.py` 的抓取选择器、请求头或解析逻辑。
- 不调整 `get_all_sources()` 的整体架构。
- 不处理 Manga18 源是否在线、是否稳定、是否需要额外容错等运行期问题。

## Technical Notes

- 目标修改文件：`sources/__init__.py`
- 相关实现文件：`sources/manga18.py`
- 相关调用入口：`server.py`
- 该问题已经在 `.trellis/spec/backend/source-adapters.md` 中作为“文件已实现但未注册”的真实遗漏示例记录
