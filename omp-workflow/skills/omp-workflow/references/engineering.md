# Engineering protocol

Use this reference to turn an authorized engineering request into a complete, reviewable product change, or an evidence-backed decision not to change code. Start at [the skill router](../SKILL.md). Use [records](records.md) for artifact ownership and durable memory, [evidence](evidence.md) for source selection and claim strength, and [harness](harness.md) for loading, context, tools, delegation, and runtime limits. Do not reproduce their inventories here.

## Status and authority

- **[INFERENCE]** The procedures below are this package's recommendations, adapted from the cited implementation and policies. Follow the target project's actual contracts and the current task's authority; do not mechanically impose upstream's language, package manager, forum, commands, or thresholds.
- **[SOURCE]** Source citations are pinned to `can1357/oh-my-pi@eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac` (core package version `18.11.3`). A local executable of another version is a separate runtime, not evidence that the pinned source was exercised.
- **[UPSTREAM]** Contributor rules, commands, and RoboOMP prompts describe intended conduct. They are not all executable gates, and they do not authorize this agent to commit, publish, install, call models, or mutate external systems.
- **[OBSERVED]** Reserve this label for actual execution with revision, inputs, environment, result, and evidence location. This reference reports no passing build, test, model evaluation, or deployment. See [validation](validation.md) for package execution evidence and its limits.

Select the applicable workflow and relevant boundaries. Completeness does **not** mean creating every record, spawning workers, or executing every scenario on every task.

## 1. First principles, then think before acting

These are two distinct obligations: derive the problem from facts and constraints, **and** decide the change before editing. A familiar pattern, impressive source repository, scanner finding, or available tool is not a reason to introduce a mechanism.

### Establish the task anchor

Before choosing an implementation, establish:

1. **Outcome and authority:** the literal request, observable user outcome, explicit exclusions, who can accept a behavior change, and permitted operations. Separate permission to inspect, edit, execute checks, spend model/provider resources, commit, and publish. The skill itself grants none of these permissions.
2. **Present state:** relevant revision, local changes that belong to others, product/version/platform/configuration, existing owner decisions, and current user observations. Treat reported observations as task facts, not something to rerun merely to establish the user's credibility. Label assumptions separately.
3. **Contract and costs:** the expected behavior, actual behavior or desired transition, preserved invariants, failure consequences, security/data boundaries, compatibility obligations, and constraints that rule out otherwise attractive designs.
4. **Acceptance before mechanism:** concrete input/state → observable result, including relevant negative, cancellation, restart, or error behavior. Define what would justify no change. Do not use code volume, citation count, test count, or severity language as a proxy for user impact.
5. **Existing implementation and rationale:** navigate project guidance → developer map → authoritative subsystem contract → implementation and consumers. Inspect history or prior decisions where intent is material. Use the source policy in [evidence](evidence.md), not a new search-first methodology.

**[UPSTREAM rationale]** The developer map deliberately points to canonical subsystem documents instead of repeating a drifting architecture walkthrough. Plans are proportional, grouped by behavior, and specify concrete edits, existing helpers, changed contracts, every caller/deletion, and observable verification; they must survive loss of the planning conversation. [Developer map][developer-map] · [Plan contract][plan-contract]

### Decide the bounded transition

Write the smallest useful statement of:

> Current state → intended state; preserved contracts; canonical owner; required authority; smallest complete logical delta; acceptance evidence.

For a small fix this can be a few bullets in the existing task record. Cross-boundary work needs a self-contained execution specification with exact signatures/fields, ordering, affected callers, deletions, and handling of material uncertainties. Reuse the project's records; do not create a parallel planning bureaucracy. Unknown consequential consumers or an unresolved authority boundary require investigation or a decision **before** mutation, not a footnote after implementation.

## 2. Admit work and additions deliberately

An issue is a report or proposal, not proof of a defect and not implementation authorization. Read its comments, existing fixes/PRs, relevant release history, and maintainer decisions before creating competing work. Do not open automation-triggering issues merely as a personal task tracker. That last caution is specific to projects with issue automation. **[UPSTREAM]** Upstream permits small bug/docs/narrow improvements directly, but requires discussion before major features, dependencies, subsystems, large UI changes, and broad cross-package behavior changes. Translate that rule into the target project's actual owner/approval process. [Admission and duplicate-work policy][contribution-admission]

| Proposed work | Admission question | Required disposition before implementation |
|---|---|---|
| Bug/issue | Which real contract is broken, with what user impact? Is the premise true, the behavior intentional, and the defect owned here rather than by a provider/runtime/another project? | Accept a bounded root-cause repair; otherwise explain intended behavior, existing remedy, upstream ownership, duplicate/fixed status, or missing evidence. Do not silently turn a feature request into a bug. |
| Feature/default change | Who needs the new outcome? What existing behavior changes, and who accepts the product/security/compatibility tradeoff? | Obtain required owner decisions; define end-to-end acceptance and unchanged contracts. A discussion or invitation to contribute is not necessarily approval to implement. |
| Dependency | What concrete capability cannot reasonably be supplied by the existing platform or established owner? | Compare reuse, extension, and addition; record version, license, maintenance/security, supported platforms, transitive/runtime/install cost, compatibility, and replacement/exit cost. Use [evidence](evidence.md) for the external-source ranking. |
| Configuration/flag | Is this genuinely a user-owned policy choice, rather than an unresolved implementation decision? | Specify owner, default, precedence, validation, persistence, security implications, docs, and migration/removal conditions. Prefer an existing setting when it already satisfies the outcome; do not add an escape hatch simply to avoid choosing coherent behavior. |
| Representation/schema/cache | Which consumer requires another form? Which fact remains authoritative? | Specify derivation, normalization, ordering, invalidation, validation, persistence/replay, and deletion rules. Avoid a second independently editable truth. |
| Refactor/helper/subsystem | What named maintenance or correctness improvement is needed? Where is the existing domain owner? | Extend the hardened owner or define a justified ownership seam. Do not introduce interfaces, buses, wrappers, flags, or dependencies merely because code moved. |

Evaluate these legitimate outcomes explicitly:

- **Implement:** the problem, owner, authority, and acceptance are established.
- **Configuration or usage remedy:** an existing supported mechanism already satisfies the request; give its exact scope and limitations. A documentation correction may still be warranted.
- **Docs-only:** runtime behavior is correct but its discoverability or documented contract is wrong; update the canonical document and relevant entry point, not an unrelated narrative.
- **Investigate:** consequential facts remain unknown; name the smallest discriminating inspection or authorized experiment. Do not guess a repair.
- **No change/reject/redirect:** the proposal is superseded, net-negative, outside accepted scope, intentional, or owned elsewhere; explain evidence and what would change the decision. No-change is a complete deliverable when justified, not an excuse to leave accepted work incomplete.

**[UPSTREAM rationale]** RoboOMP's five-part bug-merit prompt checks broken contract, impact, intentional tradeoffs, defect ownership, and true premises. Its enhancement path waits for maintainer acceptance. These are useful questions, **not** universal adoption of that bot's project-specific rejection thresholds. [Bug merit][robo-merit] · [Enhancement policy][robo-enhancement]

## 3. Choose canonical ownership; justify coupling

Canonical ownership means **one authoritative semantic decision with owned derivations**, not one file, one data shape, or minimum dependency edges.

1. Locate the current domain owner and hardened helper before adding code. Extend it when the missing capability belongs there. Preserve accumulated limits, sanitization, timeout, concurrency, and error semantics rather than recreating a superficially similar helper.
2. Explain any new boundary using responsibilities, state lifecycle, public contract, or independently varying policy. A large coherent module is not defective merely because it is large; a shared abstraction is not useful merely because two literals resemble one another.
3. Accept justified fanout: shared policy may intentionally drive catalog, authentication, transport, UI, and provider consumers. Name these dependencies and make their update path explicit. Split independently owned concepts, not merely file sizes.
4. For generated data, edit the owner source and regenerate through its authoritative generator. Never repair a bundled derivative independently. Check generator inputs, ordering, credential/network needs, generated exports, and drift rules before running it.
5. Choose the **smallest complete logical delta**, not the smallest file count. A rename, schema transition, or ownership correction may require many callers/docs/tests to move together; a tiny patch that leaves two inconsistent truths is larger maintenance debt.

**[UPSTREAM rationale]** Central helpers carry hardening and must be extended rather than forked. Provider onboarding owns catalog and auth policy separately, then derives provider unions, environment maps, login dispatch, and consumer maps; reusing an existing wire API is different from adding a transport. Generated source policy is not repaired by hand-editing bundled JSON. [Central helpers][central-helpers] · [Provider ownership and derivation][provider-ownership] · [Generated ownership][generated-ownership]

### Clean internal cutover is not indiscriminate compatibility removal

- Migrate **every internal caller**, generated reference, and import of a replaced implementation; remove obsolete internal originals, aliases, re-exports, and parallel `v2` paths. Do not leave a shim merely to avoid finishing the migration.
- Treat explicit public exports, CLI/RPC/wire shapes, persisted formats, plugins/extensions, and documented integration points as external contracts. Absence of repository references does not prove absence of consumers.
- Preserve a legitimate external adapter when that is the accepted compatibility contract. Name its supported consumers, owner, behavior, and retirement decision; keep new internal code on the canonical path rather than routing it through the legacy adapter.
- For an approved public break, deliver migration guidance/versioning and required format/provider transitions together. Do not call an unapproved break “cleanup.”

**[UPSTREAM]** Cleanup requires full callsite migration and behavior preservation, protects public exports, and forbids re-export shims after extraction. The porting guide simultaneously requires removal of obsolete internal implementations **and preservation of intentional legacy extension adapters**. Both rules matter. [Cleanup scope and execution][cleanup] · [External compatibility boundary][legacy-compat]

## 4. Close the impact cone across state transitions

Map the transition through its actual consumers, not only through files that text search happens to return. For each relevant row mark **changed**, **intentionally unchanged with reason**, or **unknown requiring investigation** in the existing plan/change record. Omit irrelevant rows with a brief boundary explanation; do not manufacture artifacts just to fill a matrix.

| Boundary | Questions to close |
|---|---|
| Identity, authority, admission | Do names/IDs, canonical aliases, ownership, permission/approval, dispatchability, or blocked-call behavior change? Can work be admitted from stale or partial state? |
| Schema and callers | Are input/output/error contracts, public exports, defaults, config precedence, bindings, SDK/RPC callers, and examples migrated? Use language-server references before changing exported symbols; inspect public maps because external users are invisible to local references. |
| Ordering and lifecycle | Who owns state before/after validation, normalization, execution, cancellation, timeout, retry, streaming completion, teardown, and restart? Which transitions must be atomic or exactly ordered? |
| Derived/generated forms | Which registries, unions, compiled policy, schemas, caches, bindings, rendered assets, or lock/build files derive from the change? What invalidates stale work or speculative plans? |
| Events, diagnostics, rendering | Do consumers see authorized effective values? Are start/update/end, live/final/rebuilt views, errors, and structured logs consistent? Is secret redaction maintained and protocol stdout kept clean? |
| Persistence and replay | Is saved data old/new compatible as intended? Are emission order, session replacement, migrations, restart, recovery, and provider replay addressed? A correct live run alone does not close durable state. |
| Providers and deployment | Are wire dialects, model/provider routing/auth, supported runtimes, native targets, packaging, and installed entry points affected? Is the tested artifact the one being claimed? |
| Docs, tests, release | Are authoritative contracts and discoverability current, tests attached to observable consumer behavior, and user-facing release notes/migrations appropriate? What evidence is still not run or outside scope? |

**[UPSTREAM rationale]** UI preview policy explicitly connects partial decoding, event propagation, transcript reconstruction, and merged call/result rendering. Logging policy distinguishes diagnostic logging from intentional standalone CLI output so shared TUI/RPC/SDK code does not corrupt its transport. This is why a final renderer or source-level test alone cannot close all consumers. [Streaming and rendering closure][ui-policy] · [Logging boundary][logging]

### Concrete example: a revised tool call is a semantic decision, not a second execution-only copy

**[SOURCE]** In the pinned agent runtime, `beforeToolCall` may return replacement `args`. The checked-in `echo` test starts with `{ value: "original" }`, returns `{ args: { value: "revised" } }`, and asserts `"revised"` at execution, the start event, and the assistant message's call block. This is checked-in test intent, **not an observed passing run**. [Replacement test][args-test]

Trace the actual ownership/derivation boundaries:

1. **Resolve identity and validate.** `prepareToolCallDispatch` repairs call IDs, resolves canonical tool names (preserving custom wire names), validates original arguments, then invokes the hook. A returned replacement is validated again; the raw replacement is written to `toolCall.arguments`, while the validated form is stored in prepared dispatch state. [Preparation implementation][args-prepare]
2. **Finalize before downstream snapshots.** On the finalized streamed path, dispatchability is established before the hook; preparation precedes speculative reconciliation, final context insertion, and final event snapshots. This is stronger and narrower than saying every earlier streaming observation already contains the replacement. Recovered paths can prepare at dispatch instead. [Finalization order][args-finalize] · [Recovered dispatch][args-recovered]
3. **Derive downstream behavior.** Prepared arguments determine argument-sensitive scheduling; start events use the effective record. Execution may apply an explicit `transformToolCallArguments` pass. Persisted messages follow the finalized message path, and subsequent provider context may normalize or encode them for a dialect. Raw/wire, validated, execution, stored, and provider forms therefore need not be byte-identical. [Scheduling][args-schedule] · [Events][args-events] · [Execution transform][args-transform] · [Persistence][args-persist] · [Provider preparation][args-provider]
4. **Invalidate stale plans.** Speculation compares finalized calls with immutable admission snapshots and discards candidates/stream sessions when the final call no longer matches. Keeping the same ID does not make an old plan valid after arguments change. [Speculation reconciliation][args-speculation]

**Critical caveat:** returned replacements are revalidated; **in-place mutations of the validated `args` reference are deliberately passed through without revalidation**. The type contract permits those mutations, and a checked-in test mutates a string field to `123` and asserts execution receives it. Never summarize this as “all modified arguments are revalidated,” nor assume every mutation follows the replacement's message-writeback discipline. [Mutation contract][args-contract] · [In-place test][args-mutation]

**[INFERENCE]** Apply the lesson, not the implementation wholesale: author a semantic revision once at its proper admission boundary; own each derivation; state when snapshots become authoritative; invalidate consumers created from the old decision. Do not prohibit useful representations or claim this example measures coupling, maintainability, speed, quality, or agent authorship share.

## 5. Assign work under one integration owner

Keep a single integration owner accountable for the accepted scope, shared contracts, coherent tree, final evidence, and handoff. Workers are optional; use them for genuinely independent slices after shared prerequisites are settled, not to distribute an unresolved top-level plan.

Every worker assignment must state:

- exact outcome and acceptance, baseline, relevant decisions, and owned paths/symbols;
- shared signatures/data ownership and dependencies on other slices;
- allowed operations, including whether any focused checks or model/provider calls are explicitly assigned;
- prohibited overlap/external effects, coordination point for shared-file changes, and expected return evidence;
- what the worker must report instead of guessing when reality contradicts the contract.

Assign by behavior or independently runnable issue/PR where possible, not arbitrary file partitions. The integration owner owns shared cutovers, generated output coordination, and cross-boundary acceptance. Workers must not run builds/tests/linters/formatters/smoke checks merely because a workflow lists them; execute only checks explicitly included in their assignment. Do not create parallel full-suite storms or verify against half-landed sibling edits. After all slices land, the integration owner performs the authorized integrated checks once and records exact coverage; if verification was not authorized, hand off the precise commands/prerequisites and the unverified status instead.

**[UPSTREAM rationale]** Issue and PR commands isolate one worker per issue/PR, avoid competing fixes, and restrict worker checks to affected areas. Review fixes address merge blockers, not unrelated rewrites. Artifact reuse is an optimization, not permission to conceal a native source change behind an old binary. [Issue isolation][fix-workflow] · [Review scope][review-workflow]

## 6. Separate merit prompts from executable host gates

RoboOMP is a useful concrete example, not a publication mechanism shipped by this package. Do not assume these tools or protections exist in a target installation. Follow [harness](harness.md) for actual exposure and permission limits.

| Layer | Pinned behavior and limitation | Operational consequence |
|---|---|---|
| Merit/ownership policy **[UPSTREAM]** | Prompts demand the five-part bug justification, root-cause scope, maintainer-stop behavior, and maintainer ownership of prompt/tool shapes. | Ask and document the semantic questions; do not mistake instructional text for a path-based denylist or proof of a good change. [Merit][robo-merit] · [Protected ownership][robo-protected] |
| Classification **[SOURCE]** | `classify_issue` validates allowed classification, nonempty rationale, bug priority, and slug shape. It does not establish the truth of the five merit conditions. | A valid tool call is not an automatic semantic gate. [Classification implementation][robo-classify] |
| Publication authorization **[SOURCE]** | Push and PR creation check authorization. Bug/docs classification, current/persisted authorization, or an existing PR can permit publication. Eligible implementation authorizers are repository `OWNER` or explicit allowlist, not every collaborator. | Read the actual authority/provenance; do not equate a classification with user consent in another environment. [Authorization][robo-auth] · [Author eligibility][robo-author] |
| Authorization semantics **[SOURCE]** | The router records authorization from eligible-author status plus a bot mention; it does not independently parse whether the text really grants “go ahead.” | Semantic permission still needs judgment. An eligibility bit is not a substitute for the user's intended action/scope. [Directive routing][robo-directive] |
| Host publication checks **[SOURCE]** | Push runs formatter and check; PR creation additionally runs the repository test script after formatter changes, then guarded push. Review mode, prepared branch, author identity, and cleanliness have separate guards. | These are executable barriers within that host, narrower than proof of product correctness. [Push][robo-push] · [PR sequence][robo-pr] · [Push guards][robo-guards] |
| Missing scripts **[SOURCE]** | Missing `fix`, `check`, or `test` scripts make the respective gate return without running. | Record **not run/missing**, never “passed by gate.” Inspect command coverage rather than relying on a familiar name. [Formatter absence][robo-fix] · [Check absence][robo-check] · [Test absence][robo-test] |
| Bypass **[SOURCE]/[UPSTREAM]** | `skip_checks=true` bypasses formatter/check/test and is audited. The prompt limits it to verified pre-existing baseline breakage and requires disclosure; those functions do not independently compare baseline failures. | A bypass is an explicit exception requiring authority and evidence, not a green result. Never invoke it to evade a diff-caused or unexplained failure. [Bypass policy][robo-bypass] · [Check/test implementation][robo-check] [robo-test] |
| Reproduction record **[SOURCE]** | `repro_record` writes agent-supplied command/output/exit status; it does not execute the command. The inspected PR publishing sequence does not require a recorded reproduction before publishing. | Supplied logs are recorded assertions unless connected to actual execution evidence. Required PR headings are structure, not semantic proof. [Recorder][robo-repro] · [PR sequence][robo-pr] |

**[INFERENCE]** Keep four things distinct in review: required authority, executable invariants, evidence-backed exceptions, and semantic instructions still dependent on agent/human judgment. None of these host gates automatically proves root-cause correctness, meaningful impact, protected-file compliance, end-to-end behavior, or honest reproduction. Do not claim this Markdown package adds a missing executable semantic gate.

## 7. Operation-specific workflows and acceptance outputs

All workflows below are **[INFERENCE]**. “Acceptance output” means the information the owner must be able to provide, not a mandatory new file. Store proportionally using [records](records.md). Checks, local UI interaction, model calls, installs, and external effects remain bounded by the actual task authorization; report unexecuted evidence honestly.

### Bug / issue

**Inputs:** reported expected/actual behavior, version/platform/settings, real user impact, current owner decisions, and available reproduction evidence.

**Procedure:** read issue/comments/history and existing fixes → admit the defect and its owning contract → state a falsifiable root-cause hypothesis → inspect the failing path and its impact closure → make the root-cause repair in the canonical owner → update the regression that detects the consumer failure and any changed docs. If authorized and useful for diagnosis or correction evidence, exercise the minimal scenario; do not rerun a user's reported failure merely to confirm it. If no reproduction is possible, distinguish that uncertainty from disproving the report; do not invent a repair or silently substitute a different bug. Upstream's issue command explicitly rejects competing fixes and stops unreproduced work rather than guessing. [Issue workflow][fix-workflow]

**Acceptance output:** broken contract and cause; bounded repair and migrated consumers; exact scenario/input/result when exercised; regression coverage or explicit unexecuted status; unchanged invariants; remaining environment/version uncertainty. For no-change, give the exact existing remedy/fix/intentional tradeoff and evidence.

### Feature / behavior or default change

**Inputs:** accepted user outcome, owner approval where required, current behavior, compatibility/security constraints, and concrete acceptance.

**Procedure:** decide reuse/config/docs-only versus new mechanism → agree contract and default/precedence/error behavior before code → follow one complete product path from entry point through state/persistence/output → implement the canonical owner and all affected consumers/generated forms → update discoverability and user-facing history. Avoid a partial callable API with no real entry point or a UI whose backend is only simulated. Keep additions within the authorized outcome. Upstream contribution acceptance requires personal use of the changed product path, not merely a check result. [Contribution responsibility][contribution-responsibility]

**Acceptance output:** approved contract, actual end-to-end path, preserved behavior, exact observed interaction when authorized, docs/config/migration consequences, and any not-run boundary. A compile-only result must not be presented as feature acceptance.

### Public API change / behavior-preserving refactor

**Inputs:** whether behavior changes are authorized, public/internal classification, named quality improvement, exported/reference map, and compatibility consumers.

**Procedure:** use language-server references before changing exports/signatures → inspect explicit exports/barrels/CLI/RPC and external consumers → select one coherent cluster → for behavior-preserving extraction move implementation without simultaneously rewriting it → migrate every caller/import → delete obsolete internal paths → retain intentional external adapters or perform the explicitly approved public migration. Do not infer dead public API from zero local references or create a compatibility re-export to postpone internal cutover. Upstream's cleanup-specific file/LOC preferences are candidate heuristics, not a general requirement to minimize touched files. [Cleanup][cleanup] · [Compatibility][legacy-compat]

**Acceptance output:** named quality/contract change, complete caller/deletion map, public-surface decision, preserved observable behavior or approved break/migration, and scoped evidence. Do not add tests that merely echo moved code; retain/relocate the behavioral contract tests.

### Native / Rust / ABI / packaged runtime

**Inputs:** JS ↔ binding ↔ Rust contract, target OS/architecture/libc/ISA, toolchain, build backend/profile/features, binding/export effects, and actual loaded artifact provenance.

**Procedure:** identify whether this is source logic, ABI/bindings, loader, packaging, or installed-runtime work → keep source and generated declaration/runtime exports coherent → when execution is authorized, select source-matched build/load/behavior evidence for the affected boundary → separately close installed artifact behavior when delivery changes. Shared or released binaries may speed unrelated TS work, but cannot prove a changed native implementation. Do not overwrite platform variants with colliding output names. Upstream's host Cargo path regenerates bindings, while Bazel artifact builds need not; committed `index.js`/`index.d.ts` remain part of the API change. [Native build/binding contract][native-contract]

**Acceptance output:** source revision and artifact identity; target/profile/features; regenerated declaration/export status; exact build/load/product-path results that were run; installed topology coverage and explicit untested targets. A TS check, successful load of an old addon, or unrelated platform's green CI is not native acceptance. **[SOURCE]** Pinned PR CI skips Rust validation and may use cached/released addons; its green status is not source-matched native proof. [CI native limits][native-ci]

### UI / streaming / transcript / renderer

**Inputs:** user-visible scenario, terminal/browser/environment constraints, input stream, and live/final/replay states.

**Procedure:** identify state owner, event propagation, decoding, renderer, and rebuilt-history path → use canonical width/path/tab/preview/sanitization helpers for success, errors, diffs, and streaming → carry preview-only fields across every path that needs them → regenerate derived views if the project requires it → when authorized, interact with the actual UI and inspect rendered evidence for relevant sizes and transitions. Do not fix only the final screenshot while live streaming or transcript rebuild still drops state. Preserve protocol stdout and avoid unredacted diagnostic payloads. [UI policy][ui-policy] · [Derived renderer build][renderer-generation]

**Acceptance output:** exact scenario and viewport/terminal conditions; observed interaction/rendering evidence when exercised; live/final/rebuilt consistency; error/cancellation/empty states relevant to the change; generated-view status; explicit unexercised surfaces. Snapshot/source assertions alone do not establish usability or actual rendering.

### Prompt / tool / harness-facing behavior

**Inputs:** intended behavioral obligations, retrieval description versus body, effective rendered prompt, live wire schema/name, settings/availability gates, dynamic context, provider/model, and protected owner decisions.

**Procedure:** obtain required owner authorization for prompt/tool-shape changes → inspect the effective prompt and actual tool schema rather than a handwritten approximation → separate static instruction assets from rendered inputs → enumerate retained defaults, routing, output shapes, exceptions, authority boundaries, and incident-derived constraints → make one intended semantic change → close loading, tool construction, schema/execution, message/persistence/replay, and provider implications. Read [harness](harness.md) for runtime limits instead of freezing its defaults here.

**[UPSTREAM]** Prompts live in static Markdown and use templating for dynamic content. Tool-prompt reconstruction from name/schema/outline identifies **pruning candidates**, not automatic deletions; a `--show` inspection avoids API calls, while live probes require explicit model/resource authority. Semantic compression inventories claims and declares losses rather than optimizing token count alone. [Prompt assets][prompt-assets] · [Probe method][prompt-probe] · [Compression method][prompt-compression]

**Acceptance output:** effective before/after inputs and intended semantic delta; retained/lost obligations; actual loading/schema/tool behavior evidence; model/provider evaluation settings, failures, artifacts, and uncertainty **only if authorized and executed**. Reconstruction success, fewer tokens, or passing deterministic checks alone does not prove behavioral parity or improved agent quality.

### Dependency / configuration / new representation

**Inputs:** capability gap, existing alternatives/owners, supported environments, authority, and maintenance/operational constraints.

**Procedure:** complete the admission row in section 2 → inspect actual versioned implementation/contracts and existing dependencies → choose reuse, owner extension, or justified addition → define source ownership and derived forms → update manifests/locks/install/build/runtime consumers together → handle config precedence/persistence or schema migration as applicable → update canonical docs and user-visible behavior. Do not turn a dependency update into a feature bundle or couple unrelated third-party refreshes to release versioning. Upstream's release tooling deliberately separates dependency refresh from the release bump. [Dependency-release separation][release-deps]

**Acceptance output:** decision and rejected alternative; exact version/license/runtime/platform cost or exact config/representation contract; complete consumer/migration/install impact; authorized execution results and unresolved risks. If reuse or no addition wins, state how it satisfies the original outcome.

### Review / triage

**Inputs:** exact issue/PR/head/base/author, accepted scope, comments, existing owner decisions, and requested review versus edit versus publication authority.

**Procedure:** review admission and already-landed equivalents before checkout → inspect the complete diff against the actual contract/impact cone → separate correctness/security/regression/compatibility blockers from taste → produce evidence-backed findings with concrete consumer impact → only if assigned, repair merge blockers in an isolated slice without unrelated refactoring. Treat semantic rebase conflicts as design decisions, not mechanical merge cleanup. Do not alter author history, submit reviews/comments, or publish without the required authority. [Review workflow][review-workflow]

**Acceptance output:** reviewed revision/scope; actionable finding with location, failure scenario, impact, and remedy; accepted/rejected/superseded disposition; assigned fix evidence; skipped checks and residual uncertainty. “No findings” states the inspected scope and limits, not universal correctness.

### Release / installed delivery

**Inputs:** approved target/version/channel, exact source revision, user-facing changelog/migration status, platform/artifact matrix, credentials and publication authority, and recovery owner.

**Procedure:** inspect the executable release implementation and CI dependencies, not command prose alone → preflight baseline/branch/cleanliness and affected version/generated/lock ownership → collect source-matched integrated and installed-artifact evidence appropriate to the change → review attribution and package discoverability → publish only with exact authorized target/scope/values → observe publication/CI/artifact results and record any unresolved boundary. Do not rerun or repair a consequential release step blindly; inspect current branch/tag/artifact state first.

**[SOURCE]** Pinned release code skips private packages, coordinates generated configuration/locks, and atomically pushes branch/tag; older command prose is not the authority for these details. CI separately aggregates validation and smoke-tests release binaries before publishing. These are configured mechanisms, not a report of a successful release here. [Release preflight and updates][release-preflight] · [Release publication/recovery][release-publication] · [Validation aggregation][release-validation] · [Release smoke][release-smoke]

**Acceptance output:** released source/tag/version and channel, exact artifact identities/targets, installed entry-point evidence, actual CI/publication status, user-facing notes/migrations, approval provenance, and recovery/handoff boundary. A local source import or successful typecheck does not prove the shipped CLI/plugin/binary works.

### Incident reentry / maintenance continuation

**Inputs:** current symptoms and impact, last known good/changed revision, affected users/data, actual running/artifact state, prior decisions/evidence, and containment/recovery authority.

**Procedure:** re-anchor current reality before resuming an old plan → preserve relevant redacted diagnostics and distinguish user reports, observations, and hypotheses → compare the live state with recorded assumptions, including stale sessions, migrations, provider state, cached artifacts, and partially completed external operations → prioritize authorized containment and data safety → identify the owning state transition and repair its cause → deliver a complete caller/representation cutover or an explicit approved rollback, not a competing emergency implementation. Never delete unrelated user changes or silently revise earlier evidence to look certain.

**Acceptance output:** incident scope/current state, confirmed cause versus hypotheses, authorized containment/recovery actions and actual results, remaining user/data risk, canonical decision/diagnostic locations, and an executable reentry anchor for the next owner. Promote lasting rationale and assessment-changing evidence to the authoritative owner document using [records](records.md); keep raw sessions and transient logs distinct from current design and release history.

## 8. Integrate and hand off without overstating completion

The integration owner closes the accepted logical change: callers, state transitions, generated forms, compatibility decisions, diagnostics, docs, and contract tests are updated or intentionally unchanged with reasons. Remove obsolete internal paths and task-created scaffolding; preserve meaningful regression evidence in the project's normal form. Do not remove unrelated material.

Choose contract-level tests, not constructor echoes, arbitrary defaults/wording, source-text appearance, or duplicate rows with no distinct consumer path. Keep tests safe in the full suite: isolate global state, environment, timers, and runtime mutation. **[UPSTREAM]** Those are explicit test principles, while contributors remain responsible for reviewing every changed file and personally exercising accepted behavior. [Test contract][test-contract] · [Contribution responsibility][contribution-responsibility]

Return a concise acceptance record: decision/outcome; canonical owner and logical delta; affected contracts and compatibility; actual commands/scenarios/results and evidence locations; not-run/missing/bypassed checks; remaining risk/blocker and next authority boundary. Never turn a planned check, stored log, source citation, checked-in assertion, resource load, or worker summary into a claimed passing run. Update authoritative current behavior and discoverability in place; keep durable rationale, task evidence, runtime diagnostics, and user-facing changelog entries in their proper roles under [records](records.md).

[developer-map]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/packages/coding-agent/DEVELOPMENT.md#L3-L10
[plan-contract]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/packages/coding-agent/src/prompts/system/plan-mode-active.md#L80-L102
[contribution-admission]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/CONTRIBUTING.md#L12-L36
[contribution-responsibility]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/CONTRIBUTING.md#L38-L80
[central-helpers]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/AGENTS.md#L65-L71
[provider-ownership]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/docs/adding-a-provider.md#L3-L62
[generated-ownership]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/AGENTS.md#L184-L214
[cleanup]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/.omp/commands/cleanup.md#L5-L86
[legacy-compat]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/docs/porting-from-pi-mono.md#L145-L151
[logging]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/AGENTS.md#L216-L228
[ui-policy]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/AGENTS.md#L230-L257
[args-test]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/packages/agent/test/agent-loop.test.ts#L5960-L6006
[args-prepare]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/packages/agent/src/agent-loop.ts#L3007-L3115
[args-finalize]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/packages/agent/src/agent-loop.ts#L2257-L2300
[args-recovered]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/packages/agent/src/agent-loop.ts#L3258-L3271
[args-schedule]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/packages/agent/src/agent-loop.ts#L3775-L3798
[args-events]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/packages/agent/src/agent-loop.ts#L3476-L3501
[args-transform]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/packages/agent/src/agent-loop.ts#L3524-L3535
[args-persist]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/packages/coding-agent/src/session/agent-session.ts#L3823-L3855
[args-provider]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/packages/agent/src/agent-loop.ts#L1929-L1968
[args-speculation]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/packages/agent/src/speculative-execution.ts#L454-L520
[args-contract]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/packages/agent/src/types.ts#L887-L951
[args-mutation]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/packages/agent/test/agent-loop.test.ts#L5919-L5958
[fix-workflow]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/.omp/commands/fix-issues.md#L24-L105
[review-workflow]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/.omp/commands/review-prs.md#L23-L84
[robo-merit]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/python/robomp/src/prompts/system_append.md#L33-L52
[robo-enhancement]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/python/robomp/src/prompts/system_append.md#L83-L90
[robo-protected]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/python/robomp/src/prompts/system_append.md#L121-L127
[robo-classify]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/python/robomp/src/host_tools.py#L2429-L2465
[robo-auth]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/python/robomp/src/host_tools.py#L1840-L1878
[robo-author]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/python/robomp/src/github_events.py#L182-L193
[robo-directive]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/python/robomp/src/github_events.py#L290-L320
[robo-push]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/python/robomp/src/host_tools.py#L1230-L1249
[robo-pr]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/python/robomp/src/host_tools.py#L1275-L1329
[robo-guards]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/python/robomp/src/host_tools.py#L856-L927
[robo-fix]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/python/robomp/src/host_tools.py#L408-L440
[robo-check]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/python/robomp/src/host_tools.py#L525-L545
[robo-test]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/python/robomp/src/host_tools.py#L575-L618
[robo-bypass]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/python/robomp/src/prompts/system_append.md#L64-L78
[robo-repro]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/python/robomp/src/host_tools.py#L1431-L1467
[native-contract]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/docs/natives-build-release-debugging.md#L101-L137
[native-ci]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/.github/workflows/ci.yml#L221-L344
[renderer-generation]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/packages/coding-agent/DEVELOPMENT.md#L25-L30
[prompt-assets]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/AGENTS.md#L51-L52
[prompt-probe]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/.omp/skills/tool-prompt-optimization/SKILL.md#L6-L43
[prompt-compression]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/.omp/skills/semantic-compression/SKILL.md#L12-L21
[release-deps]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/scripts/release.ts#L247-L258
[release-preflight]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/scripts/release.ts#L284-L438
[release-publication]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/scripts/release.ts#L441-L485
[release-validation]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/.github/workflows/ci.yml#L733-L759
[release-smoke]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/.github/workflows/ci.yml#L883-L977
[test-contract]: https://github.com/can1357/oh-my-pi/blob/eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac/AGENTS.md#L283-L315
