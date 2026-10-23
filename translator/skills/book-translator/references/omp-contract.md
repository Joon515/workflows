# OMP activation and native task boundary

## Source and execution scope

[SOURCE] The current source pin is the verified upstream v18.12.3 tag commit `53a0377db6845e0dae606146130766ec92d407fd` ([version declaration](https://github.com/can1357/oh-my-pi/blob/53a0377db6845e0dae606146130766ec92d407fd/packages/coding-agent/package.json)). Remote tag resolution and the commit's package version establish that upstream tag mapping. Neither npm version metadata nor the installed package supplies gitHead; this is NOT an npm gitHead claim. Installed OMP used for this cutover is 18.12.3.

[SOURCE] Selective SHA256 comparisons found byte-identical installed source and pinned-commit files for packages/coding-agent/src/sdk.ts, task/index.ts, task/structured-subagent.ts, task/executor.ts, task/discovery.ts, config/settings.ts, session/agent-session.ts, and packages/ai/src/auth/affinity.ts only. This is not whole-package, executable-bundle or published-tarball attestation. The earlier 18.11.3 baseline at `eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac` is historical research, not the source authority for the current native path. [verification.md](verification.md) records execution evidence and limits. Resource discovery, task settlement, provider authentication and translation quality remain separate claims.

The fixed-commit native contracts used here are:

| Boundary | Grounded native behavior |
|---|---|
| Native entry | [Session preflight](https://github.com/can1357/oh-my-pi/blob/53a0377db6845e0dae606146130766ec92d407fd/packages/coding-agent/src/task/index.ts#L901-L907) precedes [structured task execution](https://github.com/can1357/oh-my-pi/blob/53a0377db6845e0dae606146130766ec92d407fd/packages/coding-agent/src/task/index.ts#L1728-L1734). |
| Execution-time discovery | [Preflight reloads settings and discovers agents from current effective roots](https://github.com/can1357/oh-my-pi/blob/53a0377db6845e0dae606146130766ec92d407fd/packages/coding-agent/src/task/structured-subagent.ts#L350-L362). Its [scan cache is in-flight only and cleared after settlement](https://github.com/can1357/oh-my-pi/blob/53a0377db6845e0dae606146130766ec92d407fd/packages/coding-agent/src/task/structured-subagent.ts#L312-L342), unlike the [create-time description discovery memo](https://github.com/can1357/oh-my-pi/blob/53a0377db6845e0dae606146130766ec92d407fd/packages/coding-agent/src/task/index.ts#L522-L535). [Native discovery roots/precedence](https://github.com/can1357/oh-my-pi/blob/53a0377db6845e0dae606146130766ec92d407fd/packages/coding-agent/src/task/discovery.ts#L76-L116) govern project and package definitions. |
| Parent registry/authentication | Structured native tasks forward the parent's [getApiKey and credential-source session ID](https://github.com/can1357/oh-my-pi/blob/53a0377db6845e0dae606146130766ec92d407fd/packages/coding-agent/src/task/structured-subagent.ts#L592-L596), and the [same authStorage, modelRegistry and settings](https://github.com/can1357/oh-my-pi/blob/53a0377db6845e0dae606146130766ec92d407fd/packages/coding-agent/src/task/structured-subagent.ts#L645-L647). The executor [checks registry/storage identity, reuses the parent and skips independent refresh](https://github.com/can1357/oh-my-pi/blob/53a0377db6845e0dae606146130766ec92d407fd/packages/coding-agent/src/task/executor.ts#L4359-L4374), then [passes that context into child creation](https://github.com/can1357/oh-my-pi/blob/53a0377db6845e0dae606146130766ec92d407fd/packages/coding-agent/src/task/executor.ts#L4575-L4587). The SDK enforces the [same-instance storage/registry invariant](https://github.com/can1357/oh-my-pi/blob/53a0377db6845e0dae606146130766ec92d407fd/packages/coding-agent/src/sdk.ts#L1781-L1803). |
| Resolver and affinity | An [explicit host resolver passes through](https://github.com/can1357/oh-my-pi/blob/53a0377db6845e0dae606146130766ec92d407fd/packages/coding-agent/src/sdk.ts#L2342-L2345); otherwise the [registry resolver uses the child session ID](https://github.com/can1357/oh-my-pi/blob/53a0377db6845e0dae606146130766ec92d407fd/packages/coding-agent/src/sdk.ts#L2241-L2243). The SDK [inherits parent credential affinities, with explicit-pin and revived-child caveats](https://github.com/can1357/oh-my-pi/blob/53a0377db6845e0dae606146130766ec92d407fd/packages/coding-agent/src/sdk.ts#L1919-L1933), using [native affinity identity/state inheritance](https://github.com/can1357/oh-my-pi/blob/53a0377db6845e0dae606146130766ec92d407fd/packages/ai/src/auth/affinity.ts#L368-L398). These propagation facts are not independent proof of bearer-secret equality or the identity of a remote model implementation. |

This package supplies [four conventional task-agent definitions](../../../agents/), the skill and book-domain commands. Native OMP owns task dispatch, model resolution, the existing registry/authentication, retries, fallback, settlement and session/task journals. The translator owns book data, checkpoints, coverage, source sealing, build, rounds, review and release. It does not implement another execution protocol.

[OBSERVED] Current-parent ordinary native source tasks u0018, u0019 and u0020 settled successfully on the existing opencode-go/deepseek-v4-flash-vision-exp selection with native low reasoning effort and unchanged authentication configuration. The separate SDK driver's recorded 401 belongs to its independently constructed parent/authentication context; it is not evidence that current or global Go authentication is invalid. These task outcomes demonstrate those executions, not whole-book translation quality or a guarantee of future requests; see verification.md.

## Recommended startup activation

Copy the complete translator/ package into the target project's .agents/translator/ or .omp/translator/. Inspect an existing destination before replacing anything. From that project start OMP using the published plugin-directory option:

```sh
omp --plugin-dir .agents/translator
# Or:
omp --plugin-dir .omp/translator
```

This discovers the skill and four native agents together. Invoke `/skill:book-translator` interactively with the actual task, or read the discovered skill. No extension flag, package-specific task tool, SDK loader, global configuration edit, global extension install or research checkout is required. `--skills` filters discovered names, not paths; there is no singular `--skill` flag. Copying an arbitrary nested directory without activating it does not establish skill registration.

## Complete project-native activation

Instead of --plugin-dir, materialize BOTH resource groups from the retained `.agents/translator` or `.omp/translator` distribution into the same project:

| Shipped resource | Native project destination |
|---|---|
| agents/book-source.md | .omp/agents/book-source.md |
| agents/book-terminology.md | .omp/agents/book-terminology.md |
| agents/book-translation.md | .omp/agents/book-translation.md |
| agents/book-review.md | .omp/agents/book-review.md |
| ENTIRE skills/book-translator directory | .omp/skills/book-translator |

The complete skill includes scripts, references, stages, contracts, templates, requirements and tests, not just SKILL.md. Preserve the shipped relative-reference convention: agents link to `../skills/book-translator/...`; skill references link to `../../../agents/`. Agent-only copying leaves those agent links broken; file symlinks alone merely conceal that defect for consumers that resolve realpaths first. Both materialized lexical bases must close.

Preflight ALL five destinations before ANY write (including parent creation). Any existing destination file, directory, valid symlink or dangling symlink rejects the whole operation. Existing `.omp`, `.omp/agents` and `.omp/skills` parents must be real directories, not symlinks or files. Preserve unrelated children in those directories. Never merge/overwrite an existing skill tree and never link the whole agents directory. This is an explicit standard-resource recipe, not an installer/configuration/extension; run it only in the intended project with no concurrent destination writers:

```sh
# Run from the target project. Choose the retained container and ONE mode.
python3 - .agents/translator copy <<'PY'
import os
from pathlib import Path
import shutil
import sys

retained = Path(sys.argv[1]).absolute()  # Or .omp/translator
mode = sys.argv[2]  # copy, or symlink
if mode not in ("copy", "symlink"):
    raise SystemExit("Choose copy or symlink")
names = ("book-source", "book-terminology", "book-translation", "book-review")
pairs = [(retained / "agents" / f"{name}.md", Path(".omp/agents") / f"{name}.md") for name in names]
pairs.append((retained / "skills/book-translator", Path(".omp/skills/book-translator")))
if any(not source.is_file() for source, _ in pairs[:4]) or not (pairs[4][0] / "SKILL.md").is_file():
    raise SystemExit("Missing retained translator resources")
conflicts = [str(target) for _, target in pairs if os.path.lexists(target)]
for parent in (Path(".omp"), Path(".omp/agents"), Path(".omp/skills")):
    if os.path.lexists(parent) and (parent.is_symlink() or not parent.is_dir()):
        conflicts.append(str(parent))
if conflicts:
    raise SystemExit("No resources written; occupied destinations: " + ", ".join(conflicts))
for source, target in pairs:
    target.parent.mkdir(parents=True, exist_ok=True)
    if mode == "symlink":
        target.symlink_to(os.path.relpath(source, target.parent), target_is_directory=source.is_dir())
    elif source.is_dir():
        shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
    else:
        shutil.copy2(source, target)
PY
omp
```

For the relative-symlink alternative change `copy` to `symlink`; use four FILE symlinks and one WHOLE skill-directory symlink, all relative to their destination parents. Keep the retained distribution present. Ordinary copies are independent of it after materialization. Start a NEW parent without --plugin-dir: complete copies and complete symlinks each expect one `/skill:book-translator` command and four native agents. Use `.omp/skills/book-translator` as <skill> for doctor, imports and worker paths. These are resource-loading arrangements for the same built-in native task mechanism, not different model executors.

The pinned execution-time discovery evidence above concerns native task-agent preflight; it does not establish skill-command reload in an already-running parent. A create-time task description may be cached. Do not infer a live-parent skill refresh, provider access or child execution from fresh-parent CLI metadata.

### Portable verifier boundary

Run [verify_install.py](../scripts/verify_install.py) from the RETAINED translator distribution, for example `python3 .agents/translator/skills/book-translator/scripts/verify_install.py` (or the .omp/translator equivalent). The helper recognizes the translator package root using its lexical layout, plugin.json identity, README, skill entry and four agents BEFORE any copy. Invocation through materialized `.omp/skills/book-translator/scripts/verify_install.py`, including a whole-skill symlink, is rejected; a consumer `.omp` and its configuration are never a package to copy. This helper verifies disposable layouts, not live-project installation.

It checks eight isolated NEW-parent cases: two retained containers times copied-only, --plugin-dir, complete project copy and complete project symlink. Copied-only expects 0 skills/0 agents; all six active forms expect 1 skill/4 agents. It compares every installed skill file/hash and all agent hashes, checks local Markdown references from the MATERIALIZED lexical agent and skill paths (normalizing .. before filesystem traversal), and imports modules/runs doctor from that same skill. Python bytecode caches are not shipped inventory. Metadata requests send no inference and forward no credentials; doctor reports capabilities rather than proving compilation. Discovery is separate from model authentication, task execution and translation quality.

## Explicit model choice and native configuration

Follow [operation.md](operation.md) for per-workflow intake. Obtain explicit current-user choices covering source, terminology, translation and review; a current exact choice already supplied satisfies intake without asking again. Record exact provider/model identities in the job with configure-model. That command records book intent; it neither routes tasks nor changes authentication/configuration.

Portable agent templates use the standard `model: "@task"` frontmatter. This is a conventional native default, NOT permission to inherit an unchosen task model. Before source-bearing work, bind every book agent to its selected model through either standard exact-model agent frontmatter in a project copy or OMP's native project `task.agentModelOverrides` configuration. For example, use the native override keys `book-source`, `book-terminology`, `book-translation` and `book-review` with literal, explicitly chosen native model selectors. Resolve conflicting overrides through OMP's normal configuration, not a translator-specific role alias. Keep provider/model identity separate from native reasoning-effort suffixes. Ordinary task items do not gain a translator-specific model argument. Never alter global settings or unrelated native defaults.

[SOURCE] Standard persistent native sessions [reload global/project/explicit settings layers from disk while preserving runtime overrides](https://github.com/can1357/oh-my-pi/blob/53a0377db6845e0dae606146130766ec92d407fd/packages/coding-agent/src/config/settings.ts#L1318-L1331) during the native preflight above. The same implementation immediately returns when #persist is false: a Settings.loadReadOnly object, such as the separate SDK driver used, does not exercise persistent-session disk reload merely because reloadFromDisk was called. Do not infer current-parent discovery/configuration behavior from that read-only probe or rewrite global settings to compensate.

The current native registry and authentication remain authoritative, including already configured OpenCode Go, OAuth, custom and keyless/local providers. Do not construct a private registry, forward credentials, run a separate model process, restrict authentication to API keys or claim a model is free/available from a catalogue entry. Model availability, source disclosure and paid requests require the applicable current-user authorization.

Native OMP owns retries and fallback policy unchanged. Do not silently accept a different model as the user's selection, disable native policies through this package, or relabel requested identity as actual identity. If native settlement reports an unexpected identity, fallback, error or abort, preserve the actual result and diagnose it before book checkpointing. No checkpoint is engine-authentication or endpoint attestation.

## Ordinary tasks and book checkpoints

### Native task field semantics

The coordinator must supply the required nonempty top-level context and per-item native agent, task and solutionSpace fields. ALL worker instructions belong in per-item task text: absolute job/skill/input/packet/result/asset paths, commands and recipes, complete owned scope, read-only context, feedback, output/write boundaries and completion requirements. Top-level context may summarize the batch for the parent; do not leave any worker requirement solely there. task is the worker-visible instruction text. There is no opaque run marker, return-only assignment token, hidden preparation step or custom wrapper.

solutionSpace is only a short description of work open-endedness for native auto-effort/auto-thinking classification, not an instruction or implementation channel. Do not place a required path, inspection recipe, feedback or write restriction only in solutionSpace, and never assume the child sees it as a message. Native API argument completeness remains the caller's responsibility. Workers proceed from their clear rendered task assignment; they do not need raw parent tool JSON, host credentials or hidden model introspection.

[SOURCE] The pinned native executor describes solutionSpace as an [open-endedness hint separate from effort](https://github.com/can1357/oh-my-pi/blob/53a0377db6845e0dae606146130766ec92d407fd/packages/coding-agent/src/task/executor.ts#L450-L453), repeats that [classifier contract](https://github.com/can1357/oh-my-pi/blob/53a0377db6845e0dae606146130766ec92d407fd/packages/coding-agent/src/task/executor.ts#L2427-L2433), and [dispatches task as the prompt while passing solutionSpace as an option](https://github.com/can1357/oh-my-pi/blob/53a0377db6845e0dae606146130766ec92d407fd/packages/coding-agent/src/task/executor.ts#L2526-L2530). AgentSession builds [actual user text from expandedText](https://github.com/can1357/oh-my-pi/blob/53a0377db6845e0dae606146130766ec92d407fd/packages/coding-agent/src/session/agent-session.ts#L7772-L7775), [appends the message](https://github.com/can1357/oh-my-pi/blob/53a0377db6845e0dae606146130766ec92d407fd/packages/coding-agent/src/session/agent-session.ts#L8348-L8349), and [prepares agent-start messages from message/expandedText](https://github.com/can1357/oh-my-pi/blob/53a0377db6845e0dae606146130766ec92d407fd/packages/coding-agent/src/session/agent-session.ts#L8369-L8379). The separate options.solutionSpace value is used by [applyAutoThinkingLevel only for an auto-thinking user turn](https://github.com/can1357/oh-my-pi/blob/53a0377db6845e0dae606146130766ec92d407fd/packages/coding-agent/src/session/agent-session.ts#L8382-L8395). These source facts do not establish that solutionSpace is another child instruction message.

Use native task/wait/result facilities for actual settlement; do not infer success from a worker's prose.

Only after successful native settlement does the coordinator persist the actual flat SingleResult metadata and invoke the domain checkpoint commands in [operation.md](operation.md). The canonical metadata and result schemas live in [format.md](format.md). Identity checks describe native operator metadata and book progress, not independently proved engine authorization, provider requests or image perception. Native journals remain native; the translator does not require copied assistant messages, provider lifecycle capture or a second journal.

Long-book source, translation and review use bounded units. Each worker owns only its result/assets; the controller alone assembles canonical source/book/review artifacts after complete coverage. Checkpoints do not seal source, compile a partial book, advance a unit's round, submit review or accept output. The coordinator separately seals, builds/finalizes, submits the exact complete report and accepts only a fresh passing book. Every owned source/PDF page and cross-unit seam still requires actual review, not merely matching hashes.

## Historical work and limits

Preserve prior jobs, plans, packets, results and provenance bytes. Explicit import-checkpoints may carry receipt-bound completed legacy results forward as book data with hash-referenced historical origins; it does not manufacture a current native task or rewrite old evidence. Pending or failed work remains pending. See the exact import command and source/round invalidation rules in operation.md and format.md.

The package is not a malicious-agent/filesystem/network sandbox or independent endpoint attestation. Native settlement metadata and book checks cannot prove remote implementation identity, image perception, linguistic quality or absence of duplicate meaning. Keep unrelated native defaults and global settings unchanged; report only exercised execution and review evidence.
