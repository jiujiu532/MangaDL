# 接入 Ruff lint 与格式化配置

## Goal

为当前 Python/Flask 漫画下载器项目接入一套温和的 Ruff 配置，统一提供 lint 和格式化能力，同时尽量避免对现有旧代码一上来报出过多高噪音问题。本任务只负责落地配置、安装清单和首次检查结果，不批量修复或重排现有代码。

## What I already know

- 仓库当前已有 `requirements.txt`，但还没有 `requirements-dev.txt`。
- 仓库当前没有 `pyproject.toml`。
- 用户明确要求使用 Ruff 作为单一工具，同时负责 lint 和格式化。
- 用户要求规则“适度、不过于严格”，行长度应宽松，避免一上来报几百个错。
- 用户要求本任务跑一次 `ruff check .`，只报告问题数量，不批量修改现有代码。
- 当前项目是已有代码仓库，不适合直接启用非常激进的规则集。

## Assumptions

- 项目现阶段接受仅接入基础质量门禁，不要求在本任务内清零历史问题。
- `requirements-dev.txt` 用于补充开发依赖，不替代现有 `requirements.txt`。
- Ruff 配置应优先覆盖常用基础问题与格式化能力，而不是一次性打开过多升级型规则。

## Open Questions

- 无阻塞问题。需求已清晰，可直接实现。

## Requirements

- 创建 `pyproject.toml`。
- 在 `pyproject.toml` 中写入一份适度、不过于严格的 Ruff 配置。
- Ruff 配置应兼顾 lint 与 format。
- 行长度设置为相对宽松，降低旧代码初次接入摩擦。
- 创建 `requirements-dev.txt`。
- 在 `requirements-dev.txt` 中加入 `ruff`。
- 运行一次 `ruff check .`。
- 仅报告当前问题数量，不在本任务中批量修改或重新格式化现有代码。

## Acceptance Criteria

- [ ] 仓库根目录存在 `pyproject.toml`，且包含 Ruff 配置。
- [ ] Ruff 配置为温和接入风格，不是高严格度全量规则。
- [ ] 仓库根目录存在 `requirements-dev.txt`，且包含 `ruff`。
- [ ] 已运行 `ruff check .`。
- [ ] 已记录当前 Ruff 问题数量。
- [ ] 本任务未批量改动现有业务代码，也未执行全仓格式化。

## Definition of Done

- 配置文件已创建并可被 Ruff 识别。
- 首次检查结果已得到并可向用户汇报。
- 改动范围仅限 Ruff 配置与开发依赖清单，外加必要的任务元数据。

## Technical Approach

1. 新建 `pyproject.toml`，使用 `[tool.ruff]`、`[tool.ruff.lint]`、`[tool.ruff.format]` 配置 Ruff。
2. 选择温和规则集，只启用基础问题检查，避免直接引入大量风格类/升级型警告。
3. 将行长度设为较宽松值，例如 `120`。
4. 新建 `requirements-dev.txt` 并加入 `ruff`。
5. 运行 `ruff check .` 收集问题数。
6. 不运行 `ruff format .`，也不执行 `ruff check --fix`。

## Decision (ADR-lite)

**Context**: 项目是已有旧代码仓库，需要先接入低摩擦的质量工具，而不是一次性清理全部历史风格问题。

**Decision**: 采用 Ruff 单工具方案，配置为温和模式，只先建立基础 lint/format 能力与可执行入口，不在本任务内修复历史问题。

**Consequences**: 接入成本低、落地快，后续可以逐步收紧规则或分批清理现有告警。

## Out of Scope

- 不批量修复现有 Python 文件中的 lint 问题。
- 不对整个仓库执行格式化。
- 不迁移到 Black、Flake8、isort 等多工具组合。
- 不在本任务中引入 pre-commit、CI workflow 或编辑器集成。

## Technical Notes

- 目标新增文件：`pyproject.toml`
- 目标新增文件：`requirements-dev.txt`
- 现有依赖文件：`requirements.txt`
- 执行命令：`ruff check .`
