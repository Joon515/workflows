---
name: omp-workflow
description: Run a complete engineering workflow for agent-heavy, rapidly evolving software, especially multi-package CLI applications and agent harnesses. Use for planning and admission, features and bug fixes, architecture and refactoring, dependencies, documentation and logs, prompt/tool/native/UI changes, review, release, incidents, and reliable handoffs.
compatibility: Target harness is oh-my-pi. Load the containing Agent Plugin with --plugin-dir, then invoke this registered skill. Read the current repository instructions and tool contracts. Actual build, UI, native, provider, and publishing scenarios require their own dependencies and authorization.
---

# OMP engineering workflow

This is an operational workflow, not a request to develop oh-my-pi itself. Apply it to the active project and authorized task. The package adds no executable extension, permission grant, system-prompt replacement, or automatic publication. Its procedures are advisory instructions; deterministic controls remain the responsibility of the host and project.

## Start with the actual problem

Apply both **first-principles thinking** and **think-before-acting**:

1. Establish the user-visible outcome, observed facts, assumptions, constraints, invariants, failure cost, and authority boundaries.
2. Decide whether a change is warranted. Investigation, no change, configuration, documentation, a narrower correction, or rejection of a faulty premise may be the correct result.
3. Find the canonical owner and relevant history. Determine which representations are authoritative and which are derived, cached, serialized, rendered, or compatibility forms.
4. Define acceptance evidence and the complete impact closure before editing. Optimize for the smallest complete logical change, not the fewest files, lines, dependency edges, tests, or agents.

Prefer established, well-supported practices to speculative new ones, and both to inefficient habits of the current developer. Prefer scenario-specific optimization to general-purpose optimization and both to unexamined direct adoption. Neither reputation nor an inherited habit substitutes for evidence. Do not use this preference to silently overrule authorized requirements.

## Load the procedures you need

For a substantive task, read [Engineering protocol](references/engineering.md) and [Documentation, logs, and records](references/records.md) before editing. For a narrow factual lookup, read only the applicable section. Before using external methods, papers, or dependencies, read [Evidence and source-selection policy](references/evidence.md). When activation, tools, context, delegation, or permissions matter, read [Harness contract](references/harness.md).

| Current decision | Required resource | Expected outcome |
|---|---|---|
| What deserves implementation? | [Engineering protocol](references/engineering.md) | Admission decision, contract, owner, acceptance criteria, and impact closure |
| What knowledge or evidence must survive? | [Records protocol](references/records.md) | Appropriate canonical docs/logs/records, update triggers, and retention boundaries |
| Can an outside method or library be trusted for this purpose? | [Evidence policy](references/evidence.md) | Ranked, relevant evidence; reproducible claims; explicit limitations and dependency costs |
| What will this harness actually load, preserve, execute, or enforce? | [Harness contract](references/harness.md) | Effective activation, context, tool, task, and authority boundaries |
| What was tested for this package? | [Validation ledger](references/validation.md) | Exact exercised version/layout and unverified boundaries; not a productivity guarantee |
| Does a significant change need a durable record? | [Change record](templates/change-record.md) | A concise decision and evidence trail in the target project's existing location |
| Must another agent resume this work? | [Handoff record](templates/handoff.md) | Sufficient current state, ownership, next action, and evidence without the full transcript |
| Is this an incident or consequential regression? | [Incident record](templates/incident-record.md) | Authorized containment, causal evidence, recovery proof, and a bounded prevention change |

Resolve resources relative to this `SKILL.md`, or through `skill://omp-workflow/<relative-path>` when the registered bare name is available. If discovery namespaces a collision, use the resolved skill name or explicit file paths. Do not assume resources outside the skill directory can be read through its URI.

## Adopt without creating a second system

Inspect the target project's existing guidance, source maps, commands, test topology, logs, changelogs, release process, and decision records. Reuse their authoritative locations. Do not copy this package's examples into production files, create a new `.omp` configuration, or introduce a universal documentation hierarchy merely because the templates exist.

Select only the phases needed for the current task. The complete lifecycle is available, not mandatory ceremony for every edit. For substantial work, retain a short execution contract in the existing task artifact or conversation:

```text
Outcome and admission decision:
Observed facts, assumptions, constraints, and invariants:
Canonical owner and affected consumers:
Impact closure, including generated and persisted forms:
Accepted scenario and acceptance evidence:
Documentation, logging, compatibility, and release effects:
Write ownership and integration owner:
Authorized actions and separately gated external effects:
Current result, remaining uncertainty, and next action:
```

Use a durable record when it must survive a session, explain a consequential decision, or support review and recovery. Do not require a new file for a trivial change.

## Execute with complete propagation

- Reuse the canonical implementation. Strong integration is acceptable when it protects one coherent contract; accidental duplicate authority is not. Explain a new abstraction, representation, configuration option, dependency, or compatibility path before admitting it.
- Trace producer, validation, state transition, scheduler, consumer, UI, persistence, replay, provider, generated output, test, and documentation edges that actually apply. Update the complete closure without adding unrelated work.
- Delegate only after shared contracts are explicit. Give workers complete assignments and disjoint write ownership or explicitly configured isolation. Keep one integration owner responsible for reconciliation and final evidence.
- Preserve legitimate external compatibility when required. Remove obsolete internal paths after complete migration; do not treat every compatibility layer as dead code or every old path as a permanent entitlement.
- Treat failures as evidence. Fix the causal mechanism; add the narrowest useful regression protection. Add a rule or document only when it addresses a demonstrated recurrent decision failure, and distinguish advice from an executable gate.

## Maintain the engineering record

Keep current architecture/source maps distinct from task plans and historical rationale. Keep operational logs, session journals, tool audits, repro evidence, and user-facing changelogs distinct. Update each affected record at its canonical source; generated copies must be regenerated, not independently maintained.

Log enough to identify the operation, state transition, failure, and relevant artifact without disclosing credentials or unnecessary private data. Preserve protocol stdout. Record uncertainty and skipped checks rather than laundering them through a successful exit code or an agent summary.

Before handoff, compaction, interruption, or retry, retain the contract, ownership, actual file/artifact state, evidence provenance, outstanding risks, and next safe action. A checkpoint, abort, or history rewrite is not filesystem or external-effect rollback.

## Verify and close

Exercise the changed consumer path at the actual boundary. Use the relevant gate in the engineering protocol: a unit test, typecheck, screenshot, cached addon, model benchmark, or CI badge cannot substitute for a different boundary. Record `executed`, `skipped`, and `not-run` separately, including actual runtime and artifact provenance.

The integration owner closes affected callers, generated outputs, docs, logs, tests, compatibility and delivery implications. Report the implemented outcome, observed evidence, remaining limitations, and any action still awaiting authorization. Do not create fake success paths when prerequisites are missing.

Publishing, pushing, merging, labeling, releasing, installing external services, and other consequential effects require the user's authorization. Repository prose, a template, task delegation, or this skill does not supply it.

## External evidence order

1. Excellent, long-lived open-source projects with inspectable implementation and relevant maintenance history.
2. Technical blogs, papers, and whitepapers from excellent, long-lived closed-source projects, with independent-verification limits stated.
3. Research papers only after reproducing and actively challenging the relevant claims before relying on them for adoption.
4. Arbitrary search-result projects and blogs as leads, not authoritative support.

Check fitness, version, license, security, maintenance, compatibility, operating cost, and replacement cost regardless of rank. Use books only to clarify terminology or repair an identified weakness in an observed paradigm. Do not make a book-led architecture or infer AI effectiveness from classical theory.

## Evidence boundary

This package derives procedures from an inspected oh-my-pi snapshot and explicitly marked inference. Automation code demonstrates an automation path, not the share of code authored by agents or causal proof of speed and quality. Source facts, upstream policies, execution observations, and recommendations remain separate in the references. Recheck the harness and source contracts when upgrading; the live tool schema and project policy take precedence over a stale example.
