# Change record: <short title>

Use in the existing task/issue/PR location; do not create a file by default. Replace placeholders with facts, keep only applicable optional sections, and never mark planned work as completed. No secrets or raw private payloads. Procedure: [records](../references/records.md); execution: [engineering](../references/engineering.md); provenance: [evidence](../references/evidence.md); entry: [workflow](../SKILL.md).

## Identity and outcome

- Canonical task/request: <reference; exact authorized scope>
- Integration owner / affected contract owners: <owner(s)>
- Status / updated at: <current status; timestamp and timezone>
- Revision / worktree / delivered artifact: <relevant identities; note uncommitted state>
- User-visible outcome and observable acceptance: <input or situation -> expected behavior>
- Scope boundary / authority needed: <only material constraints; external actions are not authorized by this form>

## Facts and decisions

- [SOURCE] <current contract or mechanism; exact revision/path/anchor>
- [UPSTREAM] <applicable documented policy; reference, if relevant>
- [OBSERVED] <attributed observation; evidence reference, if available>
- [INFERENCE] <load-bearing assumption or recommendation; what would resolve or change it>
- Canonical owner and existing implementation to reuse: <path/symbol/contract>
- Decision / reason: <chosen approach and relevant constraint>
- Optional durable rationale: <canonical destination; meaningful rejected option/tradeoff; reconsideration condition>

## Execution plan (optional for nontrivial work)

| Behavior step / dependency | Concrete change and exact contract | Existing helper / callers / deletions | Acceptance evidence required |
|---|---|---|---|
| <step> | <edit and resulting behavior> | <authoritative paths/symbols> | <input -> expected observable> |

## Evidence and limits

| Claim / provenance class | Revision, environment, input and exact command or interaction | Expected / actual observation and exit status if applicable | Evidence reference, producer and time | Limits / not-run reason |
|---|---|---|---|---|
| <claim; SOURCE / UPSTREAM / OBSERVED / INFERENCE> | <identity, working directory, prerequisites; safe values only> | <actual status; distinguish not run from passed/failed> | <stable job/artifact/path; executor or reporter; timestamp> | <uncovered boundary, blocked prerequisite, or applicability limit> |

## Impact closure

Account for affected categories with updated locations and evidence; otherwise give a specific unaffected/not-applicable reason. This table does not require new artifacts for each category.

| Area | Changed location and closure evidence, or why unaffected | Owner / unresolved disposition |
|---|---|---|
| Canonical implementation, callers, imports/exports, config/schema/protocol consumers, obsolete paths | <disposition> | <owner/status> |
| Tests, fixtures, generated inputs/outputs and consumers | <disposition; source/generator if relevant> | <owner/status> |
| Current architecture, navigation, API/CLI/setup docs, runbooks, durable rationale | <disposition> | <owner/status> |
| User-facing changelog and external compatibility/migration | <disposition> | <owner/status> |
| Build/package resources, documentation index, install/activation and delivered path | <disposition> | <owner/status> |
| Logs, clean protocol output, tool audit, redaction and retention | <disposition> | <owner/status> |

## Handoff or final disposition

- Outcome against acceptance: <observed result; no-change/rejection is valid when justified>
- Remaining uncertainty / unexercised boundaries: <explicit limits>
- Remaining authorized work / exact blocker / owner: <concrete state; omit if none>
- Optional handoff: <reference, next action, relevant running job/agent>
- Optional restricted-artifact custody: <safe reference; access owner; retention/review trigger; no secret values>
