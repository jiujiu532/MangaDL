# 用 Ruff 安全修复可自动修复的问题

## Goal

基于当前已经接入的 Ruff 配置，使用 Ruff 的安全自动修复能力清理当前仓库中“可自动修复且不改变逻辑”的 lint 问题，并在修复后重新运行一次 `ruff check .`，统计问题数下降了多少。本任务明确不使用 `--unsafe-fixes`，也不做人工风格大扫除。

## What I already know

- 仓库根目录已存在 `pyproject.toml`，并配置了温和的 Ruff 规则集。
- 仓库根目录已存在 `requirements-dev.txt`，其中包含 `ruff`。
- 当前 Ruff 配置只启用了基础规则：`E4`、`E7`、`E9`、`F`。
- 当前执行 `python -m ruff check .` 的结果为 **472** 个问题。
- Ruff 输出显示：其中 **23** 个问题可通过 `--fix` 自动修复。
- 用户明确要求：
  - 只做安全修复
  - 不使用 `--unsafe-fixes`
  - 不做会改变逻辑的改动
  - 修后重新统计问题数变化

## Assumptions

- `ruff check --fix .` 在当前启用规则集下只会执行安全修复。
- 本任务目标是自动可修复项，不要求手工清零剩余问题。
- 修复范围可能会涉及多个 Python 文件，但仅限 Ruff 能安全改写的内容。

## Open Questions

- 无阻塞问题。需求清晰，可直接实现。

## Requirements

- 使用 Ruff 对当前仓库执行自动修复。
- 只能使用安全修复，不使用 `--unsafe-fixes`。
- 不做人工逻辑改动。
- 修复后重新运行一次 `ruff check .`。
- 汇报修复前后的问题数量，以及总共下降了多少。

## Acceptance Criteria

- [ ] 已执行 Ruff 安全自动修复。
- [ ] 执行命令中未使用 `--unsafe-fixes`。
- [ ] 修复后已重新运行 `ruff check .`。
- [ ] 已记录修复前问题数、修复后问题数、下降数量。
- [ ] 未进行与 Ruff 自动修复无关的人工大范围代码改动。

## Definition of Done

- Ruff 可安全修复的问题已实际应用。
- 最新问题统计结果可向用户汇报。
- 改动范围仅限本次安全修复产生的代码变更与必要任务元数据。

## Technical Approach

1. 保持当前 `pyproject.toml` 不变。
2. 执行 `python -m ruff check . --fix`，但不附加 `--unsafe-fixes`。
3. 再执行一次 `python -m ruff check .` 获取剩余问题数。
4. 汇总修复前 `472`、修复后数量与下降值。

## Decision (ADR-lite)

**Context**: 当前仓库已有 Ruff 配置与初始基线，下一步最安全的治理动作是先消费工具可确定安全修复的部分。

**Decision**: 只运行 Ruff 的安全自动修复，不启用 `--unsafe-fixes`，也不混入人工重构。

**Consequences**: 可以快速降低一部分低风险问题，同时把剩余需要人工判断的问题保留下来，避免一次性引入逻辑风险。

## Out of Scope

- 不使用 `--unsafe-fixes`
- 不手工修复 Ruff 剩余问题
- 不收紧 Ruff 规则配置
- 不执行 `ruff format .`
- 不进行与 lint 无关的业务重构

## Technical Notes

- Ruff 配置文件：`pyproject.toml`
- 开发依赖文件：`requirements-dev.txt`
- 当前基线问题数：`472`
- 当前可自动修复数量：`23`
- 目标命令：`python -m ruff check . --fix`
- 复核命令：`python -m ruff check .`
