# Incident record: <identifier and short title>

Use the existing incident/issue system. Omit optional sections that do not apply; do not fabricate times, cause, severity, recovery, or completion. Store sanitized evidence only. A recorded proposal is not an executed action or approval. Procedure: [records](../references/records.md); prevention changes: [engineering](../references/engineering.md); claim strength: [evidence](../references/evidence.md); entry: [workflow](../SKILL.md).

## Ownership and impact

- Incident owner / affected contract owners: <identities or roles>
- Status / severity under existing policy / updated at: <current state; timestamp and timezone>
- Canonical incident, change and communication references: <links; publication requires separate authority>
- User-visible failure and broken contract: <expected vs actual behavior>
- Affected versions, artifacts, environments and users: <confirmed scope; unknowns explicitly marked>
- Start / detection / recovery time: <known timestamps with timezone; mark unknown or estimated and basis>
- Detection source and safe correlation identifiers: <alert, user report, log/job/session ID>

## Observed timeline

| Time and timezone | Observed event or action | Producer / evidence reference | Interpretation or uncertainty |
|---|---|---|---|
| <timestamp or bounded estimate> | <fact; distinguish proposed actions> | <source, reporter, sanitized artifact> | <hypothesis or limit, if any> |

## Evidence and cause status

- [SOURCE] Relevant implementation / contract / guard: <fixed revision and path/anchor>
- [UPSTREAM] Applicable policy or documented claim: <reference, if relevant>
- [OBSERVED] Reproduction or production evidence: <revision, environment, exact safe input/interaction, actual output and exit status if applicable; artifact and producer>
- [INFERENCE] Hypotheses and discriminating observation: <plausible cause; what would confirm or refute it>
- Confirmed cause and contributing conditions: <supported causal chain; say unknown if unestablished>
- Evidence limits and unresolved scope: <not-run checks, missing data, contradictory observations>

## Containment and recovery

| Action | Proposed / authorized / executed status | Authority reference and executor | Actual result / recovery evidence | Residual risk or reversal condition |
|---|---|---|---|---|
| <specific containment or recovery> | <actual state> | <scope and approval provenance> | <observed result or not yet exercised> | <remaining exposure> |

- Recovery acceptance and independent observation: <what affected users/operators must observe; actual evidence if available>
- Optional sensitive-data handling: <safe identifier and scope only; restricted custodian/reference; no exposed value>

## Corrective feedback

| Failure mode | Corrective change and canonical location | Strength: advisory or executable control | Owner / status / target trigger | Required closure evidence and limits |
|---|---|---|---|---|
| <specific recurrence risk> | <doc/rationale/helper/test/runtime guard/CI/host gate or justified no-change> | <advisory wording, or actual enforcement point plus bypass/failure behavior> | <accountable owner; actual disposition> | <observable prevention check; not run if unexercised> |

- Durable rationale / reconsideration condition: <where future owners learn why; when to revisit>
- Affected callers, tests, generated sources/outputs, architecture, navigation, runbooks, package docs and changelog: <updated references or specific unaffected reasons>
- Superseded rule/mechanism removed or explicitly superseded: <location and disposition, if relevant>

## Closure and retention

- Impact/recovery disposition: <evidence-backed status; do not equate mitigation with root-cause fix>
- Corrective actions closed or explicitly remaining with owners: <references and evidence>
- Remaining uncertainty / pending authorization: <exact boundary>
- Restricted artifacts / access owner / retention or review trigger: <safe references under existing policy>
- Review/closure owner and timestamp: <actual reviewer and time, only after review>
