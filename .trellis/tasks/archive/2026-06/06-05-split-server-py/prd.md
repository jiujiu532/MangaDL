# 拆分 server.py

## Goal

把当前体量过大、职责过多的 `server.py` 拆分成更清晰的模块结构，降低维护成本，让后续功能迭代、质量治理和测试更容易推进，同时尽量保持现有 Flask Web 行为不变。

## What I already know

- 当前项目是一个 Python/Flask 漫画下载器，后端采用“共享核心模块 + 两个入口”的结构。
- `.trellis/spec/backend/index.md` 已明确：`server.py` 目前集中承担 Flask app 初始化、全局单例创建、路由定义、源聚合、缓存、SSE 日志、下载入口等多类职责。
- `server.py` 是一个超大单文件入口，已经明显超过普通单模块可维护范围。
- 当前项目没有现成的 `routes/`、`services/`、`repositories/` 目录结构，拆分不能机械套模板，必须适配现有单仓结构。
- 当前共享核心模块包括：`sources/`、`download_manager.py`、`config.py`、`favorites.py`。
- 用户当前目标只有一句“拆 server.py”，尚未说明拆分深度与最终目录形态。

## Assumptions

- 本任务应以“重组 Flask 侧代码边界”为主，而不是顺带重写 `sources/`、`download_manager.py` 等既有共享模块。
- 拆分时应优先保持现有 API 行为与页面行为兼容。
- 需要先确定拆分深度，再进入实现阶段。

## Open Questions

- 已确认：采用中等重构方案，引入 `web/` 或等价目录，按入口 / routes / state / helpers 拆分，但仍保持现有行为兼容。

## Requirements (evolving)

- 将 `server.py` 的多职责代码拆开，减少单文件复杂度。
- 保持现有 Flask API 和页面入口行为兼容。
- 复用已有共享模块，不为拆分而重写业务核心逻辑。
- 拆分方案需符合当前项目实际结构，而不是生搬硬套通用模板。
- 采用中等重构：允许新建 `web/` 一类目录，将 `server.py` 拆成薄入口 + 多个职责模块。
- 优先拆分的职责应包括：Flask app 初始化、路由集合、缓存/共享状态、图片代理/预取、下载相关 API、收藏/追更相关 API。
- 尽量避免对 `sources/`、`download_manager.py`、`config.py`、`favorites.py` 的业务逻辑做功能性修改。

## Acceptance Criteria (evolving)

- [ ] `server.py` 体量与职责明显收敛
- [ ] Flask 能正常启动
- [ ] 现有关键 API 路由仍可工作
- [ ] 新模块边界清晰，可读性提升
- [ ] 入口文件不再承载绝大多数实现细节
- [ ] 新目录/模块结构能让后续新增 API 时有明确落点

## Definition of Done

- 结构调整完成并通过基础运行验证
- 无功能性回归
- 若形成新的结构约定，更新 `.trellis/spec/`

## Out of Scope (tentative)

- 不主动重写 `sources/`、`download_manager.py` 的业务实现
- 不做与 server 拆分无关的大规模 UI 或下载逻辑重构
- 不借本任务顺手做风格大扫除或 Ruff 清零
- 不改造为完整的 Blueprint/service/repository 企业模板，除非拆分中证明当前结构无法支撑

## Technical Notes

- 目标主文件：`server.py`
- 已知相关模块：`sources/`、`download_manager.py`、`config.py`、`favorites.py`
- 已确定拆分层级：中等重构
- 候选结构方向：
  - `web/app.py`：Flask app 创建与全局装配
  - `web/state.py`：共享单例与缓存状态
  - `web/routes_*.py`：按领域拆路由（search/listing、images、download、favorites 等）
  - `server.py`：保留为兼容入口，负责启动或导出 app
