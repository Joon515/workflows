# OMP engineering workflow

这是一个 **可整包复制的 Agent Plugin**，将 oh-my-pi 中可借鉴的工程范式转为 agent 可执行的流程。它不只是 upstream summary，也不替换 omp 默认 system prompt。

适用于 agent-heavy、rapidly evolving software，尤其是 multi-package CLI / agent harness，以及 native addon、provider、UI、RPC、persisted session 与 cross-platform delivery 等交叉边界。对简单任务只选择相关路径；不要为了完整而引入不需要的 coordination 或 documentation。

## 1. Copy and activate

从本仓库 root 执行。`target` 是已有目标项目；`container` 可选择 `.agents` 或 `.omp`。如果同名 package 已存在，先审阅升级差异，不覆盖目标项目的修改。

```sh
target=/absolute/path/to/your-project
container=.agents
if test -d "$target" && test ! -e "$target/$container/omp-workflow"; then
  mkdir -p "$target/$container"
  cp -R omp-workflow "$target/$container/omp-workflow"
else
  printf '%s\n' 'Target missing or package already exists; inspect before copying.' >&2
  exit 1
fi
cd "$target"
omp --plugin-dir "$container/omp-workflow"
```

进入 TUI 后提交实际任务：

```text
/skill:omp-workflow Investigate the reported defect. Decide whether a change is warranted, identify the canonical owner and complete impact closure, then implement and verify the accepted change.
```

**Activation boundary：** omp 不自动扫描 `.agents/omp-workflow/` 或 `.omp/omp-workflow/` 这样的任意子目录。`--plugin-dir` 是每次启动所需的显式 registration，不是一次性的安装命令。无需拆散文件、创建 symlink、修改全局 settings 或复制本仓库 root `AGENTS.md`。

不要使用不存在的 `--skill <path>`；`--skills` 是已发现 skill 的 name filter。不要把 positional CLI argument `/skill:...` 当成已经验证的 TUI skill expansion。也不要用 `omp --plugin-dir ... skill list/read` 检验 registration：当前 CLI utility dispatch 不沿 launch-time plugin 路径执行。细节及源码见 [Harness contract](skills/omp-workflow/references/harness.md)。

`.agents` 在这里是可选存放位置，不代表任意其他 harness 都已经通过兼容性验证。有效 provider settings、skill-name collisions 和本地 policies 仍可能影响实际 session。

## 2. Package structure

```text
omp-workflow/
  README.md
  plugin.json
  skills/omp-workflow/
    SKILL.md
    references/
      engineering.md
      records.md
      harness.md
      evidence.md
      validation.md
    templates/
      change-record.md
      handoff.md
      incident-record.md
    scripts/
      verify-install.ts
```

只有本 README 面向人；其余内容均为 English agent-facing assets。所有 procedure、template 和 script 均在 skill directory 内，支持相对路径和注册后的 `skill://omp-workflow/...`。不依赖本研究仓库、`ref/` 或 `ref_repo/`。

| Asset | 职责 |
|---|---|
| [SKILL.md](skills/omp-workflow/SKILL.md) | 入口、first thinking、procedure routing、跨阶段约束 |
| [Engineering protocol](skills/omp-workflow/references/engineering.md) | admission、canonical ownership、impact closure、implementation 和 scenario-specific acceptance |
| [Records protocol](skills/omp-workflow/references/records.md) | documentation、logs、decision/repro/audit/changelog 的区分、维护与保留 |
| [Harness contract](skills/omp-workflow/references/harness.md) | dynamic prompt、discovery、tools、delegation、context、permissions 与 reload 边界 |
| [Evidence policy](skills/omp-workflow/references/evidence.md) | 外部参考/依赖优先级、paper reproduction gate、分享内容核验与书籍辅助定位 |
| [Validation ledger](skills/omp-workflow/references/validation.md) | 实际验证、版本、重现方式与未覆盖项 |
| [Templates](skills/omp-workflow/templates/) | 需要 durable records 时使用；不强制目标项目新建一套平行目录 |
| [Installation smoke](skills/omp-workflow/scripts/verify-install.ts) | 临时复制到两种目标位置，通过真实 omp RPC 验证 registration 与 negative controls |

## 3. Operational coverage

核心选择是 **bounded logical change + complete impact closure**，而不是“改动文件越少越好”，也不是“耦合越少越好”。Canonical ownership、明确 derived representations、相同契约下的完整传播，可以比表面上的模块独立更重要。

| 阶段或场景 | Workflow 要求的结果 |
|---|---|
| Intake / first thinking | outcome、facts/assumptions、constraints、invariants、failure cost、authority；先判断问题与前提 |
| Admission | feature、dependency、configuration、representation 或 abstraction 是否值得新增；保留 no-change、docs/config-only、rejection 等结果 |
| Design / change map | canonical owner、历史原因、state transitions、affected consumers 与完整 impact closure |
| Implementation / delegation | 一个完整 logical change；明确 ownership、shared contracts 与单一 integration owner |
| Documentation / logs | 复用 authoritative locations；current architecture、task plan、rationale、operational log、session journal、audit、repro、changelog 各司其职 |
| Bug / feature / refactor | 真实 consumer path、错误与边界；完整 caller/generated/doc migration；保留有依据的 external compatibility |
| Native / UI / prompt / tool | 分别验证本次 addon、实际交互与 replay、effective model inputs 和正确统计口径 |
| Review / release | findings 与 external mutations 分离；明确 CI coverage、artifact identity、target execution 与 publication authority |
| Incident / maintenance | 先授权 containment，保留因果证据，再做窄修复与 prevention；不把每次失败扩成全局禁令 |
| Handoff / re-entry | 当前 contract、文件/artifact 状态、evidence、risks、owner 与 next safe action，可脱离完整 transcript 恢复 |

这些是可选的完整流程面，不要求每个小任务都创建 plan、ADR、incident record 或运行全套 checks。Agent 先发现目标项目既有习惯，再填补真正缺失的机制。

## 4. Documentation and rule mechanisms

该 package 区分三层：

- **稳定知识与 rationale**：保存在目标项目既有 authoritative docs/records；及时移除过时 walkthrough，不复制多份事实。
- **conditional workflow**：本 skill 按任务读取对应 procedure；templates 只在需要 durable artifact 时使用。
- **deterministic gate**：必须由实际 host/tool/CI implementation 执行。本 package 没有 extension code，文字规则不能冒充 permissions、publication gate 或 sandbox。

RoboOMP 的 admission prompts、host-side checks 和 publication paths 提供了可借鉴实例，但它们并不等价：missing scripts、`skip_checks`、agent-supplied repro records 等都存在证据边界。迁移时不把上游宣言当作已执行保证。

## 5. First thinking and external references

First thinking 同时指 **first-principles thinking** 与 **think-before-acting**。不是“先写很长计划”，而是先确定真实 outcome、invariants、canonical owner、改动必要性及可观察验收，再选择已有范式。

外部参考与依赖顺序固定为：excellent long-lived OSS → excellent long-lived closed-source projects 的 technical publications → 在采用相关结论前已复现并主动质疑的 research papers → 普通搜索 OSS/blogs。任何等级仍需核对适用性、license、maintenance、security、compatibility、运行及替换成本。

经典书籍只用于描述精度和修补具体问题，不作为 workflow 的默认架构来源。[分享内容](https://chatgpt.com/share/6ad3118a-8e40-83ea-8172-7d3c4884bffc) 已读取并作为待核验假设：automation implementation 可以证明存在 agent execution paths，但不能单凭规模与 release cadence 推出 majority authorship、开发质量或因果上的速度优势。

## 6. Verify the copied package

需要 installed `omp` 与 `Bun`。可以在任意 cwd 运行被复制 package 内的脚本，例如：

```sh
bun .agents/omp-workflow/skills/omp-workflow/scripts/verify-install.ts
```

脚本创建并清理临时 projects/HOME/agent directories，分别测试 `.agents` 与 `.omp`：copy-only 时不应出现 command；加 `--plugin-dir` 后应出现 `skill:omp-workflow`、`source=skill`。只发送 RPC inspection commands，不提交 prompt，不转发 credentials。默认 catalog model 为 `openai/gpt-5.2`；若安装版本不含它，可通过 `OMP_WORKFLOW_SMOKE_MODEL` 指定其已有 catalog model。这只是启动所需的 model selection，不是 model inference。

可迁移性不等于 effectiveness。实际执行的版本、body/resource helper checks、引用和 English checks，以及未验证部分，以 [Validation ledger](skills/omp-workflow/references/validation.md) 为准。

## 7. Provenance and upgrade

- Source snapshot：[can1357/oh-my-pi@eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac](https://github.com/can1357/oh-my-pi/tree/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac)，core `18.11.3`。
- 本机实际 launch/runtime 验证对象：`omp 18.10.3`、`Bun 1.4.3`；不混写为 pinned snapshot 的全套通过。
- Package format：[Agent Plugins 1.0.0](https://agent-plugins.org/specification)；skill format：[Agent Skills](https://agentskills.io/specification)。
- Evidence labels：`[SOURCE]`、`[UPSTREAM]`、`[OBSERVED]`、`[INFERENCE]` 分别表示实现、上游规范、实测和推导。

升级时重新检查 plugin/discovery、skill expansion、动态 prompt、delegation/approval、context lifecycle，以及所引用的 engineering gates。同步引用与 validation ledger；完整替换过时 package，不保留另一套同名入口或 obsolete nested skill layout。
