# Records, documentation, and engineering memory

Return to the [workflow router](../SKILL.md). Use [engineering](engineering.md) for admission, ownership, implementation, and impact closure; [evidence](evidence.md) for claim strength and provenance; [harness](harness.md) for session, loading, tool, and permission behavior.

The procedures below are **[INFERENCE]** workflow recommendations derived from the pinned sources at the end. They are instructions to an agent, not executable enforcement, permission to publish, or evidence that a check has run. Adapt them to the target project's established contract. Completeness means retaining the records needed for this change, not producing every kind of record on every task.

## 1. Discover ownership before creating records

1. Read applicable project guidance and the existing issue/PR/task context. Locate the developer map, canonical subsystem contracts, package documentation/manifests, decision conventions, changelog/release policy, generated-document inputs, logging/audit sinks, and evidence storage. Follow existing links before introducing a location.
2. Identify the owner of each affected contract and the integration owner responsible for closure. A document owner is normally the subsystem/package owner, not a newly invented documentation role. Assign a concrete person, team, or current task role when the project has no ownership declaration.
3. Keep current architecture separate from an execution plan. Determine a document's purpose from its content and status, not its filename: a file called `*-plan.md` can describe current architecture. A developer map routes readers to authoritative documents; it should not repeat their architecture narrative. [UPSTREAM: navigation and current architecture][developer-map] [session-architecture]
4. Use the existing issue, PR, task description, or session record for a small change. Create a missing persistent artifact only when its information has a future reader and no adequate canonical home. Choose its location under the project's existing convention. Do not create default `docs/`, ADR directories, journal files, or evidence trees merely because this workflow is loaded.
5. Treat the installed workflow package as reusable resources, not a target project's task ledger. Read a [change-record](../templates/change-record.md), [handoff](../templates/handoff.md), or [incident-record](../templates/incident-record.md) form and fill only the needed sections in the chosen destination. Do not copy the whole template set into the target or write task data back into the package.

**Ownership rule:** one authoritative location per fact or instruction. Other surfaces link to it. A source map is not the authority for every subsystem; a transcript is not the authority for current behavior; generated output is not the authoring source.

## 2. Choose the right record

Each row describes a distinct job, not a required new file. Reuse existing mechanisms. Keep the smallest fields that allow the intended reader to act without inventing missing context.

| Record and reader | Canonical home and owner | Minimum useful content | Update trigger and lifetime |
|---|---|---|---|
| Current architecture / source map: maintainers navigating present behavior | Existing subsystem document, package map, or source-local contract; subsystem owner | Responsibility and boundaries, public/internal status, invariants, authoritative implementation/generator links, navigation to adjacent owners | Update with moved ownership, changed contract, entry point, storage, protocol, or dependency boundary. Maintain while the capability exists; remove obsolete descriptions and incoming links on retirement. |
| Task plan: implementer executing this change | Existing task/issue/PR or harness plan; integration owner | Outcome and acceptance, concrete behavior steps, canonical helpers, dependencies, exact changed contracts, affected callers/deletions, verification inputs and expected observables | Write before nontrivial mutation; revise when evidence changes a load-bearing decision. Close or supersede at completion; promote only lasting rationale, not the whole plan, into maintained docs. |
| Durable rationale: future owner avoiding rediscovery | Near the relevant contract, a focused code comment, existing decision record, or linked issue/PR; contract owner | Decision and status, problem/constraints, reason, meaningful rejected alternative/tradeoff, evidence provenance, condition for reconsideration | Record when an otherwise surprising choice, compatibility promise, rejected approach, or expensive constraint must survive the task. Supersede explicitly when it changes. Use an ADR only if the project already requires one or the decision warrants a separate record. |
| Operational log: operators diagnosing a running product | Existing centralized logger/telemetry sink; runtime/service owner | Timestamp and severity, component/event, safe correlation ID, relevant bounded state, error category and outcome | Emit at useful runtime boundaries and failures. Use existing rotation, access, and retention policy; do not turn every operation into a permanent verbose trace. |
| Session journal: agent resumption and human task history | Existing harness session/task history; session owner | Goal, decisions, concise state changes, result/evidence links, unresolved work and handoff pointer | Append meaningful milestones; summarize before handoff or context loss. Keep transient under the session retention policy; not a stream of private reasoning or a duplicate code review. |
| Tool audit: authorized reviewer reconstructing an action | Existing host/tool audit store; host/operator owner | Task/actor/session correlation, timestamp, tool/action, sanitized arguments or safe reference, actual result/error, authorization/bypass reference where relevant | Capture actual tool invocations through the existing mechanism. Retain under security/operational policy; do not manually forge audit events from a task summary. |
| Reproduction / verification evidence: reviewer checking a claim | Existing test artifacts, CI job, issue attachment, or scoped evidence store; executor produces it, integration owner interprets it | Revision/artifact and environment, exact input/command or interaction, expected vs actual observation, time, exit status if applicable, sanitized output/artifact, limitations | Capture when a reproduction, check, or product-path observation is actually exercised. Replace stale applicability claims after relevant changes; retain stable evidence links needed for review or incidents. |
| User-facing changelog: consumers adopting a release | Existing package/product changelog or release-note mechanism; package/release owner | Brief user-visible change, affected surface, breaking/migration requirement and issue/PR attribution where applicable | Update unreleased notes when user-visible behavior changes. Follow project rules for released history; do not use it for task diaries or root-cause essays. |
| Incident record: operators and maintainers preventing recurrence | Existing incident/issue system; incident owner with affected contract owners | Impact and time window, observed timeline, evidence, cause status, containment/recovery status, corrective actions with owners and closure proof | Open for an incident warranting coordinated diagnosis or durable learning. Update through recovery and action closure; retain/redact under incident/security policy. |

[UPSTREAM] The pinned plan policy scales from a few bullets to ordered cross-cutting steps and requires callers, deletions, concrete observables, and a self-contained specification. This does not require a separate plan document for every edit. [plan-contract]

[UPSTREAM] Upstream changelogs are per package, brief and user-facing under `[Unreleased]`; released sections are immutable there. Discover the target's actual convention instead of copying this layout universally. [changelog]

## 3. Keep facts, hypotheses, and evidence distinct

Use the [evidence policy](evidence.md) consistently:

- **[SOURCE]** identifies what inspected implementation, manifest, or executable mechanism does at an exact revision. A test's existence is not a passing result.
- **[UPSTREAM]** identifies a documented rule or claim; it does not establish enforcement or effectiveness.
- **[OBSERVED]** identifies an actual execution or observation. Preserve input, revision/version, environment, result, artifact, and limits. Record a user-reported result as attributed to the user, not as your own run; do not rerun it merely to confirm it.
- **[INFERENCE]** identifies interpretation, recommendation, or an unverified assumption. State what would change the decision and which observation would resolve uncertainty.

Do not silently convert a hypothesis into a root cause, a planned command into a passing check, a successful tool request into a user-visible outcome, or a skipped check into coverage. Record `not run`, `blocked`, or `not applicable` with the actual reason. When a claim changes, update its current status and retain the relevant superseded evidence if the project's history requires it.

Use exact fixed-revision source links for external claims; include version and source/artifact identities for local evidence. Name the person/tool/job that supplied an observation. Where an artifact is ephemeral, preserve the smallest sanitized excerpt needed to understand the result in the canonical task record. A checksum can identify retained bytes but does not independently prove the claim.

[SOURCE] RoboOMP's `repro_record` validates supplied fields, writes command/output/exit status, and audits the call; it does **not** execute the recorded command. Its tool-call store persists supplied arguments, result/error, and timestamp. These are useful record shapes, not independent verification or a promise of sanitization. [repro-record] [tool-audit-schema] [tool-audit-write]

## 4. Update records as part of the same logical change

### Before and during implementation

- Establish the literal requested outcome, observable acceptance, known facts, assumptions, authority, and canonical owner before selecting a familiar design. Then decide the smallest complete change and its impact closure using [engineering](engineering.md).
- For cross-cutting work, make the plan executable without the planning conversation: concrete new behavior, existing helpers, exact contracts, every affected caller/deletion, and evidence requirements. Put settled implementation decisions in the plan, not in an open-question list. Keep small tasks correspondingly short. [UPSTREAM: plan contract][plan-contract]
- Record only decisions that matter to implementation, review, operations, or resumption. Link evidence instead of pasting raw terminal transcripts into multiple places. Update the canonical contract as behavior changes; do not wait for a second documentation-only migration.
- If behavior is unchanged, state why architecture/release notes are intentionally unchanged in the task record when this would otherwise be ambiguous. Do not add meaningless documentation churn.

### Full impact closure

The integration owner accounts for **every affected category**, with a location/evidence link or a specific reason it is unaffected. This is a review lens, not a demand to create one artifact per row:

1. Canonical implementation and all internal callers, imports/exports, configuration/schema/protocol consumers, and obsolete paths.
2. Tests and fixtures that defend the changed observable contract; generated inputs/outputs and their consumers.
3. Current architecture, developer navigation, public API/CLI/setup examples, operator runbooks, and lasting rationale.
4. User-facing changelog and compatibility/migration guidance when the change affects adopters.
5. Build/package manifests, assets, generated documentation indexes, installation/activation instructions, and the delivered artifact path.
6. Logs/audits needed to diagnose or review the changed behavior without leaking data or corrupting protocols.
7. Actual verification results, unexercised boundaries, remaining risk, and the owner of any authorized remaining action.

A broad but coherent migration is preferable to a narrow patch with stale internal callers or competing instructions. Deliberate compatibility for real external consumers needs an explicit owner and contract; accidental aliases and stale docs are not compatibility policy.

### Generated documentation and distribution

- Identify the authoring source, generator, inputs, committed/shipped outputs, owning package, and documented regeneration command. Change the source, not an output that will be overwritten. Regenerate only when authorized for the assignment, and distinguish performed regeneration from a required but unrun command. [UPSTREAM: generated-source ownership][generated-ownership]
- Keep source and required generated outputs in the same logical change. If generation is unavailable, report the exact prerequisite and unresolved artifact; do not hand-edit an output and claim regeneration.
- When a capability is runnable, make it discoverable from the existing product entry point while retaining package-local setup/flag ownership. Mark internal-only components explicitly and route them to their architecture owner. [UPSTREAM: package discovery][package-discovery]
- Treat shipped docs as part of the product. Record source/package revision, included resources, supported install/activation layout, prerequisites, and limits. A checkout-relative link or successful source-tree read is not proof that a package contains the same documentation. Upstream's docs loader explicitly separates embedded/shipped/checkout corpora, and its manifest/prepack pipeline ships generated documentation. [SOURCE: docs delivery][docs-loader] [package-files] [package-prepack]
- For this workflow, preserve skill-relative links and the explicit `omp --plugin-dir <package>` activation contract described in [harness](harness.md). Do not claim arbitrary nested-directory autodiscovery, require an unshipped checkout, or copy project-specific evidence into the reusable package.

### Stale-document retirement

When moving, replacing, or deleting a contract, find and update its incoming references, navigation, examples, generated indexes, and package inclusion rules in the same change. Remove obsolete instructions and contradictory duplicate narratives. Preserve historical decision records only when useful, clearly marked superseded and linked to the current owner; keep them out of the current-behavior route. Do not preserve dead guidance as an unlabelled compatibility copy. Follow retention/security authority before deleting operational or audit records.

## 5. Logging and output are product contracts

Before adding diagnostics, discover the existing logger, level conventions, redaction, sink, rotation, and failure handling. Reuse that mechanism rather than introducing a second logger or raw output channel.

- Keep protocol stdout clean. Shared TUI, RPC, SDK, worker, and background code must not print debugging messages to stdout or stderr unless the surrounding contract explicitly provides that sink. `console.error` is not automatically safe merely because it uses stderr.
- Intentional standalone CLI output is a separate user-visible contract: preserve documented stream, format, exit status, and machine-readable output. Classification depends on the runtime path, not the filename.
- Log actionable events and bounded context: safe identifiers, operation, failure category, and outcome. Avoid duplicate catch-and-log chains, unbounded payload dumps, high-cardinality secrets, and noisy success traces. A diagnostic record must not falsely announce success before the operation completes.
- Correlate operational events with a task/session/job where the existing system supports it. Keep raw requests, tool traces, and reproduction evidence in their intended stores rather than stuffing them into normal logs.

[UPSTREAM] Upstream requires the centralized logger in code that may run with TUI/RPC/SDK/workers/background runtimes and documents rotated file logs plus a semantic standalone-CLI exception. Its exact logger import and filesystem path are upstream-specific, not defaults to impose on another project. [logging]

## 6. Privacy, access, and retention

The record producer is responsible for sanitizing the record; the existing store owner controls access and retention. An agent must not invent a global retention schedule, expand telemetry, grant permissions, or purge records without authority.

1. Record only what is necessary for the reader and decision. Never put credentials, tokens, cookies, private keys, secret environment values, authorization headers, or unnecessary personal/customer data into docs, commands, logs, audit arguments, screenshots, artifacts, or handoffs. Use safe secret references, not their values. Avoid passing secrets in tool arguments that may be audited.
2. Sanitize at capture time and before sharing. Prefer synthetic/minimized inputs, allowlisted metadata, and bounded redacted excerpts; consider URLs, query strings, local paths, screenshots, filenames, and process arguments sensitive as well as message bodies. Redaction must not conceal a material failure or fabricate output.
3. Follow the project's retention/access rules for each store. Durable decisions outlive a session; raw logs and journals usually should not. Record a custodian and expiry/review trigger for new sensitive or large artifacts when policy permits their collection. If policy is absent, retain the minimum safe record in the existing restricted destination and resolve ownership before collecting raw sensitive data.
4. Keep restricted artifacts out of public repositories/releases; link an access-controlled reference when permitted. Before publication, the authorized publisher reviews both the summary and attachments. A template or upstream command is not publication authority.
5. If a secret is exposed, stop further disclosure, notify the responsible security/credential owner, and follow the incident process. Record a safe identifier and impact, not the secret again. Rotation, revocation, history rewriting, and deletion require their own authorization; do not silently erase audit history.

## 7. Session, compaction, and transfer handoff

Write a compact [handoff](../templates/handoff.md) when responsibility transfers, a long task may lose context, or current state cannot be reconstructed cheaply from canonical records. Use the harness/session facility where adequate; a separate repository file is optional. Link the current change record instead of duplicating it.

Preserve the exact goal and acceptance, user constraints/authority, owner and touched worktree state, completed changes, exercised results and failures, not-run checks, unresolved questions, active jobs/agents/artifacts, and the next concrete action. Distinguish planned work from already executed effects, so a successor does not replay a publish, destructive action, or expensive run. Never claim an action is authorized solely because an old summary says so; retain the direct authorization reference and re-evaluate current point-of-risk requirements.

The receiver reads applicable guidance and current canonical documents, reconciles actual files/jobs with the handoff, and rereads the relevant source before editing. Do not rerun user-reported failures merely to confirm them, restart completed checks without a reason, or overwrite unexpected user changes. Treat summaries as potentially stale navigation, not ground truth or new authority.

[UPSTREAM] The pinned compaction prompt calls for goals, constraints, completed/current/blocked work, decisions, next steps, critical context, pending questions, exact paths, and relevant results. [handoff-prompt] [UPSTREAM] Compaction/branch summaries are persisted session entries used when rebuilding model context. [compaction] [UPSTREAM] Session history supports targeted rewrites and migrations. [session-format] [session-migration] [INFERENCE] It is therefore not an immutable audit or decision ledger.

## 8. Incident to rule or mechanism

Use the [incident form](../templates/incident-record.md) when an operational failure, repeated engineering mistake, or security event warrants durable analysis. The incident owner coordinates; affected subsystem owners accept corrective changes.

1. **Establish impact and evidence.** Record user-visible failure, time window, affected versions/surfaces, detection method, and sanitized observations. Separate confirmed causes, contributing conditions, unresolved hypotheses, and unknown scope. Link reproduction and recovery evidence rather than guessing cause from the error string.
2. **Separate recovery from prevention.** Record authorized containment/recovery actions actually taken and their observed result; proposed actions remain proposed. Publishing, production changes, permission/credential changes, or destructive cleanup still require the applicable authority. Recovery success is not proof the underlying cause is fixed.
3. **Choose the smallest effective corrective home.** A mistaken current contract needs a canonical doc correction; missing navigation needs a source-map link; a violated invariant may need a regression test, centralized helper, runtime validation, CI gate, or host-side authorization guard. Do not grow a universal rule for a one-off typo or add a duplicate mechanism beside the owner.
4. **Name control strength.** A prompt, skill, checklist, or review reminder is **advisory**. An **executable control** must identify the actual test/check/guard, where it runs, what it rejects, bypasses/failure behavior, and an owner. Recording a reproduction or checklist item alone does not enforce that the underlying action happened. If a proposed control is not implemented/exercised, say so.
5. **Close the feedback loop.** Tie each corrective action to a failure mode, owner, status, evidence requirement, and canonical location. Verify prevention at the appropriate boundary when authorized, update docs/changelog as applicable, and remove superseded advice/mechanisms. Close only when impact/recovery and corrective-action dispositions are evidenced; unresolved actions remain explicitly owned, not hidden behind a completed incident label.

[UPSTREAM] Upstream's worker-packaging guidance preserves past failure modes and issue links next to the current invariant and names a live product smoke probe. It illustrates actionable rationale plus a mechanism, not proof that this workflow or any future run is effective. [worker-rationale]

## Pinned provenance

All links below refer to `can1357/oh-my-pi@eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac` (core package `18.11.3`). These are inspected source/documentation anchors, not local runtime results. Record the actually executed version separately. The recommendations above do not depend on retaining the upstream checkout.

[developer-map]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/packages/coding-agent/DEVELOPMENT.md#L3-L10
[session-architecture]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/docs/session-tree-plan.md#L1-L25
[plan-contract]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/packages/coding-agent/src/prompts/system/plan-mode-active.md#L80-L101
[changelog]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/AGENTS.md#L317-L345
[repro-record]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/python/robomp/src/host_tools.py#L1431-L1467
[tool-audit-schema]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/python/robomp/src/db.py#L90-L99
[tool-audit-write]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/python/robomp/src/db.py#L1052-L1073
[package-discovery]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/docs/user-facing-packages.md#L3-L10
[docs-loader]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/packages/coding-agent/src/internal-urls/docs-index.ts#L125-L160
[package-files]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/packages/coding-agent/package.json#L30-L46
[package-prepack]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/packages/coding-agent/package.json#L533-L535
[generated-ownership]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/AGENTS.md#L203-L214
[logging]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/AGENTS.md#L216-L228
[handoff-prompt]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/packages/agent/src/compaction/prompts/compaction-summary.md#L1-L38
[compaction]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/docs/compaction.md#L3-L8
[session-format]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/docs/session.md#L63-L69
[session-migration]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/docs/session.md#L435-L459
[worker-rationale]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/AGENTS.md#L53-L63
