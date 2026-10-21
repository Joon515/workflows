# LaTeX book translation workflow

A self-contained oh-my-pi Agent Plugin for authorized PDF, EPUB, MOBI and DjVu books, including scanned and mixed text/image pages. It produces reviewed LaTeX PDFs, not merely OCR or a successful compile. An explicitly authorized excerpt or damaged copy must retain its true scope and missing-material limits; never call it a complete book. DRM bypass is outside scope.

## Activation

Copy the entire translator/ package into the target project's .agents/translator/ or .omp/translator/. Inspect existing destinations before replacing anything. Recommended published startup loads the skill and four conventional native task agents together:

```sh
omp --plugin-dir .agents/translator
# Or:
omp --plugin-dir .omp/translator
```

Invoke `/skill:book-translator` interactively with the actual task, or read the discovered skill. No extension flag, private task tool, SDK, global settings edit or research checkout is required. `--skills` filters discovered names, not paths; there is no singular `--skill` flag. Copying an arbitrary nested package without activation does not establish skill registration.

For an **already-running parent**, explicitly copy or file-symlink the four shipped agents into project .omp/agents/book-source.md, book-terminology.md, book-translation.md and book-review.md, inspecting collisions first. Installed OMP 18.12.3 refreshes project-native task agents on task preflight. Read the copied [SKILL.md](skills/book-translator/SKILL.md) manually: project-agent discovery alone does not register the skill or its slash command. Existing task-description text may be cached. These are two resource-loading arrangements for the same built-in native task system, not two execution backends. See [omp-contract.md](skills/book-translator/references/omp-contract.md) for scope and evidence limits.

## Explicit models; native ownership

Every workflow requires explicit current-user model choices for source, terminology, translation and review. An exact current choice already supplied fulfills intake; ask only for missing, unavailable or ambiguous choices. One model may serve all four. Explicit reuse resolves exact identities; old presets and unchosen parent/task defaults are not authorization. Existing native OpenAI and non-OpenAI configurations are eligible when actually available and authorized.

The shipped templates use conventional `model: "@task"` frontmatter. **Before source-bearing work**, configure the four agents to the user's choices through standard exact-model OMP frontmatter in project copies or native project task.agentModelOverrides. configure-model records book intent only; it does not route tasks or configure authentication. Keep reasoning effort in native configuration, separate from job provider/model IDs. Do not introduce package-specific model-role aliases or modify global settings.

Native OMP owns the current registry/authentication, model resolution, retries, fallback, task settlement and session/task journals. Existing OpenCode Go, OAuth, custom and keyless/local providers remain native; the package creates no private registry, credential forwarder, provider capture or separate model launcher. Registration, authentication, actual request success and translation quality are separate facts. Catalogue presence does not promise service availability or free requests. User authorization must cover source disclosure and any paid use.

Supply ordinary native task context and per-item agent/task/solutionSpace with complete scope, paths, feedback and write boundaries. After actual native settlement, check the ACTUAL flat SingleResult identity/status and record book progress through checkpoint-unit or checkpoint-role. A model mismatch/fallback/error/abort is not silently accepted or relabeled as the requested model. Native policy remains unchanged. Checkpoint identity is descriptive native operator metadata/book progress, **not independently proved engine authentication**, endpoint identity, image perception or translation quality.

## Default layout

| Setting | Contract |
|---|---|
| Paper | A5, two-sided physical-side mirrored layout |
| Outer long edge | 8 mm |
| Binding side | Complete minimum margin 20 mm, no added binding compensation |
| Top/bottom | 15 mm each |
| Translated folios | Start at 1 on explicit main_body_start; title/prefaces/frontmatter have no printed folio; outer running-header folios, never footer folios |
| Running headers | Physical left/even: inner chapter; physical right/odd: inner section; new chapter clears stale section |
| Original folios | Verified printed source labels at content transitions, outer long edge 3 mm from paper edge; not reader absolute page indices |
| Notes | Bottom of the annotated page, rule-separated; at least one line when present, at most half body height per page, with long continuations at subsequent page bottoms |
| Agent translator preface | Required, authored by the chosen translation model, at most two compiled pages |
| Human preface | Optional, separate and only supplied/authorized; never fabricate a human signature |
| Paragraphs/lists | Two-em first-line indentation; original ordered/unordered markers and levels; hanging continuation alignment |
| Original blank pages | Retain sealed evidence but omit translated blank blocks/pages/markers and explanatory filler; never remove sparse real content or insert parity blanks |
| Artwork | Verified source-body-font-relative source_em sizing, no fill-to-width enlargement; only explicit reviewed bounded uniform downscale |
| Glossary | Four Chinese-labeled columns only: number, original term, translation, first-use page reference; authorities/decisions remain audit data |

Translated body folios and physical PDF pages are distinct: without parity blanks body page 1 may be a physical left page. Binding side, margins and headers always follow physical sides. Original-source labels retain Roman numerals, prefixes, repeated labels and null for truly unnumbered pages; do not fabricate pagination. An overwide label is measured/fitted only inside its outer folio strip without changing text, baseline or the 3 mm anchor.

## Translation, restoration and fit invariants

- Preserve formulas and prose variable names. Use protected LaTeX only after symbol-by-symbol verification; otherwise retain actual formula images. Preserve code including comments and whitespace. There is no general native table renderer or automatic table reflow promise.
- Preserve original personal-name components; translate only non-name parts of eponyms. Record actual terminology authorities, editions/locators and decisions; where no standard is verifiable, record specialist usage or uncertainty rather than inventing a citation.
- First genuine term use is bold italic with a numbered superscript. Explicit title_terms spans count before prefaces/body; approved term tokens cover body, captions and notes. First-use references distinguish unnumbered frontmatter physical PDF locations from body-relative folios. Do not omit early uses to manufacture a body-page first occurrence. Glossary audit authority/decision fields are not printed columns.
- Retain images/groups, inline raster mathematics, reading order, panel offsets/gaps, source assets and baselines. Verify source_em against normal surrounding source running-text/body font, not tiny diagram/caption text, raster DPI or a bounding-box height. Preferred size is source dimensions / source body em * output body em, not available-column width. Missing defensible calibration blocks affected work.
- Move an intact object to the next page if only the current remainder is too small. If it cannot fit a whole eligible page/side column, a candidate uniform scale is min(1, available width/preferred width, available height/preferred height), reserving unscaled captions, side text and notes. Record an explicit scale, reviewed readability floor and actual compiled-size evidence for smallest labels/subscripts/lines. One scale covers the whole canvas and every panel/offset. No crop, split, upscaling, silent source_em change, paper/margin change or implicit landscape fallback is allowed. Still oversized/unreadable artwork is a blocker requiring authorized constraint change. Fit is output-only mutable metadata bound to content/current-PDF review; source-only documents omit it.
- Every body paragraph, caption, table and note requires source coverage. Explanatory footnote prose must be translated, including raster-origin notes: transcribe verified semantic prose and retain the full original note raster as non-rendered source_evidence. Protect mixed-note mathematics/code/names. An untranslated English prose bitmap is not an acceptable footnote translation.
- Default damaged ordinary prose to defensible evidence-backed reconstruction. Preserve confirmed/conjectural status, source-page identity, replacement and supporting rationale/evidence in sealed internal metadata; context is not recovered ink. The printed single editorial note contains only a concise target-language completion notice, verbatim original fragment and supplied-source damaged crop. Do not print the locator, repeated replacement, status, rationale or other commentary. Author visible note.target explicitly; rendering does not automatically disclose restoration metadata. A clean witness cannot replace the damaged crop. Never guess materially ambiguous technical values.

The canonical source is **Book version 2**: verified body boundary, image calibration, structured lists, real blank-page classification and semantic prose notes. Old sealed books cannot be upgraded by filling defaults, rewriting receipts or resetting rounds. Preserve historical bytes and obtain newly reviewed source/seal/downstream book checkpoints where required. This package does not automatically migrate active jobs or authorize additional model calls. Mechanical token/schema checks do not prove every name, OCR error or undeclared variable was found; actual source/PDF review remains mandatory.

## Dependencies

Python 3.10+, PyMuPDF, Pillow and jsonschema are required; executed Python versions are pinned in [requirements.txt](skills/book-translator/requirements.txt). Use an authorized isolated project environment, for example `python3 -m pip install -r "$skill/requirements.txt"`, not global installation. Composition requires XeLaTeX, ctex/template packages, appropriate fonts and the LaTeX build/column/baselineattach output socket API. The recorded composition environment is TeX Live 2026; missing capability fails explicitly rather than skipping bottom-note size correction. latexmk is optional; repeated XeLaTeX is used otherwise. OCR needs working Tesseract language data; DjVu needs a real ddjvu decoder. Doctor reports capabilities, not permissions to install/upload.

PyMuPDF/MuPDF uses AGPL or commercial licensing; independently assess compatibility with intended distribution/service use. Other dependencies retain their licenses. The package ships no upstream binaries, OCR language data or third-party books.

## Operations and artifacts

Resolve skill to the copied skill directory and keep jobs outside the package. Record current exact user choices, then bind corresponding native agent models before work:

```sh
skill=.agents/translator/skills/book-translator
python3 "$skill/scripts/translator.py" doctor
python3 "$skill/scripts/translator.py" init /path/book.pdf /path/book-job --source-language en --target-language zh-CN
python3 "$skill/scripts/translator.py" configure-model /path/book-job source --provider "$SOURCE_PROVIDER" --model "$SOURCE_MODEL"
python3 "$skill/scripts/translator.py" configure-model /path/book-job terminology --provider "$TERMINOLOGY_PROVIDER" --model "$TERMINOLOGY_MODEL"
python3 "$skill/scripts/translator.py" configure-model /path/book-job translation --provider "$TRANSLATION_PROVIDER" --model "$TRANSLATION_MODEL"
python3 "$skill/scripts/translator.py" configure-model /path/book-job review --provider "$REVIEW_PROVIDER" --model "$REVIEW_MODEL"
# Configure standard native OMP agent frontmatter/overrides to those selections.
python3 "$skill/scripts/translator.py" extract /path/book-job --ocr auto --language eng
```

Source, translation and review with more than eight source pages require bounded durable units, with 1-8 owned source pages each; choose smaller units for dense content. Terminology remains whole-role against complete sealed source. Eligible small whole-role work uses checkpoint-role. The controller is the single aggregate merge owner: unit workers write only assigned result/assets, never canonical source/book/report or sibling results. Every imported draft page starts pending; fresh OCR skeletons are not ready source. Inspect every assigned source page, not samples.

```sh
python3 "$skill/scripts/translator.py" plan-units /path/book-job source --pages-per-unit 4
# Optional untrusted source reading aid: --draft /path/existing-source-draft.json
python3 "$skill/scripts/translator.py" unit-status /path/book-job source
# Native book-source tasks use actual pending IDs/packets and ordinary context/task/solutionSpace.
# Wait for native settlement; persist each ACTUAL flat SingleResult, then:
python3 "$skill/scripts/translator.py" checkpoint-unit /path/book-job source UNIT_ID --task-result /path/actual-single-result.json
python3 "$skill/scripts/translator.py" assemble-units /path/book-job source
python3 "$skill/scripts/translator.py" validate /path/book-job --source
python3 "$skill/scripts/translator.py" seal-source /path/book-job
```

Plan command: plan-units JOB ROLE --pages-per-unit N [--draft PATH] [--revise]. Unit/status/assembly commands are shared by source/translation/review; use every returned unit ID. A unit checkpoint changes no whole-book state/round, seal, build, review submission or approval. Assembly requires every planned scope checkpointed and complete coverage; source sealing is separate. Run/checkpoint native book-terminology next, then plan/task/checkpoint/assemble translation. Complete authoring is saved before fallible compilation; only successful canonical finalization advances one round, never a unit task.

Review automatically bounds each task to eight owned physical PDF pages plus at most two immediate read-only PDF context pages. Overflow IDs repeat bounded source/block/note scope, so source inspection may overlap but must cover the entire source set. Physical PDF ownership/inspection remains exact-once over every output page. Inspect seams against complete read-only neighboring blocks/notes and declared owners. Hashes/semantic-ID declarations do not independently prove perception, proofreading or semantic non-duplication. Unsupported cross-unit restructuring stays pending for explicit replanning, never silent omission or invented span contracts.

After complete native review checkpointing/assembly, submit that **same exact report**, then accept only a fresh complete pass:

```sh
python3 "$skill/scripts/translator.py" review /path/book-job /path/report.json
python3 "$skill/scripts/translator.py" accept /path/book-job
python3 "$skill/scripts/translator.py" status /path/book-job
```

All eight review checks must pass with no findings; the current build must pass all eleven gates. Neither model completion, checkpointing nor report assembly submits/accepts automatically. On changes_requested, return the entire aggregate finding set to translation. Default **three complete translation/review pairs**; the third failure exhausts the job and releases no output.pdf. Only explicit user choice may raise the cap.

book.json is the complete assembled translation; terms.json/handoff.md retain terminology and context. units/ holds durable plans/packets/results/checkpoints and inspection evidence. provenance/ holds domain role/authoring/finalization records and immutable historical data; native OMP keeps execution journals. reviews/ binds exact report/content/PDF identities; build/ holds TeX/PDF and mandatory build evidence. Only final acceptance publishes output.pdf. Recovery uses durable/native records, not conversation memory or a task badge.

Explicit import-checkpoints JOB ROLE --plan PATH imports only receipt-bound completed legacy results as book data into sibling book-plan.json plus hash-linked historical-origin checkpoints; it preserves old job/plan/packet/result/receipt/evidence bytes and calls no model. Failed or unreceipted results remain pending. Never invent a current native result for historical work.

Source correction uses a bounded --revise plan or eligible whole-role checkpoint-role --revise, followed by deliberate seal-source JOB --reseal. Correction checkpoints/assembly do not replace the old seal/state/round; changed resealing invalidates downstream approval, unchanged resealing cannot reset the cap. Pretranslation terminology revision is allowed only at terminology_ready, round 0, with current bindings and linked feedback. Do not reset history or silently hand-edit checkpointed outputs. If a valid unchanged complete-authoring proof exists after build failure, finalize-translation JOB performs fresh canonical build/finalization without new inference; it does not admit partial/changed work or skip review.

Exact schemas, commands and stage instructions are in [format.md](skills/book-translator/references/format.md), [operation.md](skills/book-translator/references/operation.md), [source](skills/book-translator/stages/source.md), [terminology](skills/book-translator/stages/terminology.md), [translation](skills/book-translator/stages/translation.md) and [review](skills/book-translator/stages/review.md). Agent-facing package instructions and operational records are English; book prose/prefaces/glossary values use the requested target language.

## Verification and limits

```sh
python3 translator/skills/book-translator/scripts/verify_install.py
# Full domain regression, when explicitly assigned to the verification owner:
python3 -m unittest discover -s translator/skills/book-translator/tests -v
```

Adjust paths after copying. verify_install checks isolated .agents/translator and .omp/translator copy layouts: published --plugin-dir skill/four-agent discovery, conventional native frontmatter, and explicit project .omp/agents discovery without falsely claiming skill registration. It requests actual CLI metadata only, sends no model prompt and forwards no credentials. Fresh copied-layout discovery is not proof of live-parent discovery, provider authentication, task execution or translation quality. Executed checks/history/limits belong in [verification.md](skills/book-translator/references/verification.md); old results are not proof of this cutover.

The workflow is not a malicious-agent/filesystem/network sandbox or independent endpoint attestation. Source parsers/TeX require appropriate OS isolation; prose is escaped, assets/math constrained and shell escape disabled. Do not claim complete real-book translation without actual selected-model native work, complete source/current-PDF review and book-domain gates. Complex scans, uncertain formulas, side-text artwork and narrow folio strips may require source-structure correction, not cropping, swallowed notes, fabricated pagination, unsupported fit or silent model substitution.
