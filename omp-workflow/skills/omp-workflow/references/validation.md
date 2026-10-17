# Package validation ledger

Use this ledger to distinguish a usable distribution artifact from untested claims about agent behavior. Return to [the workflow](../SKILL.md); use [harness](harness.md) for implementation contracts and [evidence](evidence.md) for inference policy.

## Identity and scope

- Review and execution date: **2026-10-17**.
- Research source: `can1357/oh-my-pi@eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac`, core **18.11.3**.
- Executed CLI and installed-package helper source: **omp 18.10.3**.
- Execution runtime: **Bun 1.4.3**, Linux x64.
- Distribution contract: copy the entire Agent Plugin into a target project's `.agents/omp-workflow` or `.omp/omp-workflow`, explicitly register it at launch with `--plugin-dir`, then invoke the registered skill through the supported interactive path.
- All observations below are local. No prompt, steer, or follow-up inference command was submitted; credentials were not forwarded into the isolated fixtures. This is not a general network-traffic audit.

The pinned 18.11.3 source and installed 18.10.3 implementation are separate evidence objects. Do not relabel installed helper execution as execution of the pinned tree. Earlier checks of the obsolete nested `omp-engineering` skill layout are not verification of this package.

## 1. Actual launch-time registration

**[OBSERVED]** Ran the shipped [installation smoke](../scripts/verify-install.ts) using the real installed `omp` executable. It copies the entire package into temporary projects, supplies isolated HOME/agent directories, omits credentials, and sends only `get_available_commands` and `get_state` over the actual RPC interface. It cleans its fixtures in a `finally` block.

| Copy destination | Explicit activation | Observed skill command | Observed session state |
|---|---|---|---|
| `.agents/omp-workflow` | None; negative control | No `skill:omp-workflow` | `messageCount=0`, `isStreaming=false` |
| `.agents/omp-workflow` | `--plugin-dir <copied package>` | Exactly one `skill:omp-workflow`, `source=skill` | `messageCount=0`, `isStreaming=false` |
| `.omp/omp-workflow` | None; negative control | No `skill:omp-workflow` | `messageCount=0`, `isStreaming=false` |
| `.omp/omp-workflow` | `--plugin-dir <copied package>` | Exactly one `skill:omp-workflow`, `source=skill` | `messageCount=0`, `isStreaming=false` |

The launch used `--mode rpc --model openai/gpt-5.2 --no-session --no-lsp --no-extensions --no-title`. An explicit existing catalog model was needed because an isolated configuration had no default model. Selecting it for inspection did not submit an inference prompt. `--no-extensions` did not prevent standard skill-plugin registration.

Run after installation or upgrade, with the path adjusted to the chosen container:

```sh
bun .agents/omp-workflow/skills/omp-workflow/scripts/verify-install.ts
```

If the installed catalog no longer contains the default inspection model, set `OMP_WORKFLOW_SMOKE_MODEL` to a model already present in that installation. A missing model is a startup prerequisite failure, not evidence that the plugin is invalid. Do not add credentials or submit a prompt merely to inspect registration.

The runner bounds each process to 45 seconds and rejects missing/error RPC responses, unexpected registration, collisions, nonzero message counts, and streaming state. Its initial development run exposed an incorrect use of Bun's stdin sink; changing the writer to `write(input)` followed by `end()` made the real four-case smoke pass. No sleep or retry was added to conceal the failure.

## 2. Real skill preprocessing and resource helpers

**[OBSERVED]** A separate isolated fixture used the real **installed 18.10.3 package's TypeScript modules**, not mocks and not a model call:

1. `injectPluginDirRoots` registered the copied standard package.
2. `loadSkills` selected `omp-workflow` with provider `agent-plugins`, the copied skill path, package `containRoot`, and no discovery warnings.
3. `parseSkillInvocation` and `buildSkillPromptMessage` expanded the actual skill body, omitted frontmatter, included the absolute skill directory and user task arguments, and did not leave the raw invocation in place of the instructions.
4. `SkillProtocolHandler.resolve` resolved `skill://omp-workflow/SKILL.md` to the copied file's actual content and path.
5. Encoded `..` traversal outside the skill base was rejected. This proves the exercised URI rule, not process, filesystem, or network sandboxing.

These helpers are the implementation used by the interactive skill/resource paths. The inspected RPC API has no dedicated expansion/resource-inspection operation; sending a real skill `prompt` would proceed into the provider pipeline. Therefore helper integration is deliberately reported separately from full-session invocation. An initial helper assertion was too specific about the wording of an already-correct traversal rejection; correcting the assertion did not change the implementation.

The exact module locations used for the helper run were the installed package's `src/discovery/helpers.ts`, `src/extensibility/skills.ts`, `src/internal-urls/parse.ts`, and `src/internal-urls/skill-protocol.ts`. This environment-specific verification is not a package runtime dependency. Normal use requires the installed harness, not access to an upstream checkout or those source files.

### Completed-package resource coverage

**[OBSERVED]** Repeated the installed-source helper integration for both final copy destinations. Each resolved all ten skill-contained files: the router, five references, three templates, and the installation script. Every returned resource matched the copied file content and source path; discovery warnings were empty and encoded parent traversal was rejected in both fixtures.

The complete 88-line skill body survived expansion, with the absolute copied skill directory and user arguments preserved. The prompt renderer changes Markdown table padding, so the full-body comparison normalized only horizontal whitespace around table separators; it did not ignore instruction text, row order, defaults, or exceptions. URI resource comparisons remained byte-for-byte. This is real preprocessing/resource integration, not a provider or instruction-following experiment.

## 3. Distribution integrity

**[OBSERVED]** Checked the completed authored distribution: 15 files, including 12 Markdown files and 13 non-README English agent-facing files. All 80 local links resolved; skill-local dependencies remained within the skill base. All 182 fixed-commit source links addressed existing files and valid line ranges across 80 upstream files. Reference definitions and code fences passed structural checks. The obsolete root study documents and nested skill directory were absent.

JSON/YAML parsing and field/name/length checks passed for the Agent Plugins 1.0.0 manifest and Agent Skills metadata. The skill had 95 file lines including frontmatter; no tokenizer measurement is claimed. Actual standard-provider registration additionally exercised the installed loader. English-language review was supported by a scan rejecting CJK content in non-README authored files.

These checks establish package structure, language compliance, containment of local dependencies, and addressable citations, not universal schema-client compatibility, semantic truth of every citation, external URL availability, or workflow effectiveness. The source claims were separately reviewed against the inspected reports and pinned implementation.

## 4. Utility commands are not plugin-registration proof

**[OBSERVED]** In isolated installed-18.10.3 fixtures, leading `--plugin-dir P` before `skill list` did not register the package, and before `read skill://...` did not make the skill resolvable. A trailing flag was rejected by the utility parser. Direct `omp read <file path>` could read the file, but that did not create a skill command.

Use the actual launch smoke, not a utility result from a different code path, to claim registration. The negative controls above also establish that copying into an arbitrary child directory alone does not activate the package.

## 5. Verification limits

Not claimed or executed for this package:

- A real model-driven engineering task, instruction-following rate, behavioral A/B comparison, or productivity experiment.
- TUI keystroke automation of `/skill:omp-workflow`; interactive expansion is supported by source inspection and the real preprocessing helper, not an observed interactive task.
- Full upstream 18.11.3 build/test execution, Rust/native rebuilding, real provider integration, or target-platform release validation.
- A security audit of approvals, extensions, MCP, subprocesses, or all possible URI/path attacks.
- Automatic activation in unrelated harnesses, every omp version, or every user profile/provider configuration.
- Publishing, pushing, labeling, merging, releasing, or changing global configuration.

A valid manifest, registered command, accessible resource, completed checklist, or positive smoke is not evidence that a model followed the procedure or that the procedure improves speed and quality. Preserve these limits when reporting adoption.

## 6. Maintenance obligations

When updating the package, rerun the shipped copied-layout smoke, validate the manifest and skill format, check all local resources and pinned-source anchors, and review every non-README authored file for English agent-facing content. Exercise expansion/resource helpers again when their contracts or layout change, where an appropriate installed-source environment is available. Report a missing prerequisite as unverified coverage rather than installing a fake substitute.

Update this ledger with the actual version, commands, observed results, changed boundaries, and remaining limits. Remove obsolete distributions and aliases only after the replacement path works. Do not carry forward earlier link totals, resource checks, or runtime results as though they were rerun for changed bytes.
