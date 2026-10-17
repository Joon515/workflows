# workflows

本仓库为 AI-assisted software development 提供可迁移的 **operational workflow packages**，不是仅供阅读的 upstream studies。目标 harness 是 **oh-my-pi（omp）**：每个 workflow 必须考虑 dynamic system prompt、discovery、tools、context lifecycle、delegation、permissions 与实际执行机制。

## Workflow index

| Workflow | 适用范围 | 入口 |
|---|---|---|
| `omp-workflow` | agent-heavy、rapidly evolving software，尤其是 multi-package CLI / agent harness 及其 native、provider、UI、RPC、release 边界 | [README](omp-workflow/README.md) |

整个 workflow directory 可以复制到目标项目的 `.agents/` 或 `.omp/`。若 harness 不自动扫描任意子目录，就提供并验证显式 activation；不将“文件已经存在”描述为“政策已经生效”。首个 package 使用标准 Agent Plugin，通过 `omp --plugin-dir <package>` 加载，无需全局 settings、额外 extension code 或 system-prompt override。

## Global contract

1. **只有 `README.md` 面向人。** 可以用中文，technical terminology 保持 English；其余 authored files 全部面向 agents、使用 English，包括 references、analysis、templates、scripts、comments 与 rules。原书和 ignored upstream snapshots 是参考数据，不改写。
2. **交付的是可操作流程。** 覆盖适用的 intake/admission、architecture/ownership、implementation、documentation、logs、tests、runtime verification、review、release、incident 与 handoff。完整不等于每次都执行所有阶段或新建所有文档。
3. **已有优秀范式 > 待验证的新范式 > 当前开发者的低效习惯。** **scenario-specific optimization > general-purpose optimization > unexamined direct adoption**。说明证据与代价，不照抄权威，也不把偏好冒充效率。
4. **First thinking 包含两层。** First-principles thinking：从 outcome、facts、constraints、invariants、failure cost 与 authority 推导方案；think-before-acting：先决定是否该改、canonical owner 在哪里、impact closure 是什么，再动手。
5. **书籍是辅助，不是 workflow 的主导来源。** `ref/` 用于精确描述已观察到的范式，或修补其具体问题；不从书籍直接推出 AI-development effectiveness。
6. **外部参考与依赖有明确顺序。** Excellent long-lived OSS → excellent long-lived closed-source projects 的 technical blogs/papers/whitepapers → 已复现并主动质疑相关结论的 research papers → 任意搜索结果中的 OSS/blogs。排名不能替代适用性、license、maintenance、security、compatibility 和替换成本检查。

## Evidence discipline

- `[SOURCE]`：固定 commit 的实现事实。
- `[UPSTREAM]`：上游规范或作者声明。
- `[OBSERVED]`：本次实际执行结果，附版本与边界。
- `[INFERENCE]`：本仓库的迁移选择或推导。

Shared AI conversations 是待核验假设，不是独立证据。规模、release cadence、agent prompts 或 automation code 均不能单独证明 majority agent authorship、开发质量或因果上的效率优势。

## Repository layout

- `omp-workflow/`：独立分发的 workflow package；具体 activation、覆盖范围和 verification 见其 README。
- `ref/`：经典 software engineering 参考书。
- `ref_repo/`：optional upstream checkouts，已由 `.gitignore` 排除；交付 package 不依赖它们。
- [AGENTS.md](AGENTS.md)：本仓库的 English management guidance，不随 workflow 复制到目标项目。

格式依据：[Agent Plugins specification](https://agent-plugins.org/specification)、[Agent Skills specification](https://agentskills.io/specification)、[AGENTS.md convention](https://agents.md/)。
