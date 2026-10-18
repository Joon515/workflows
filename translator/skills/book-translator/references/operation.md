# Operational procedure

## Prerequisites and admission

Run `python3 <skill>/scripts/translator.py doctor`. Python 3.10+ and the local libraries pinned in ../requirements.txt are required; install them only into an authorized isolated environment. PDF composition needs XeLaTeX and the template TeX packages plus suitable Latin/CJK fonts. latexmk is optional; the renderer uses repeated XeLaTeX when unavailable. OCR requires working Tesseract language data, including when the engine is bundled with PyMuPDF. DjVu requires ddjvu. The doctor/extraction error names missing capabilities. Do not install global packages or upload sources without authorization. Local-only extraction does not mean hosted model translation is local.

Use a fresh job path outside the plugin package. Initialize with source and target language explicitly, and a source file of PDF, EPUB, MOBI or DjVu. Initialize copies and hashes the original. Do not overwrite an existing job. Asset paths stay inside that job. Dependency upgrades require rerunning the relevant full test modules and copy/compile smoke; never silently change the executed OMP version allowlist.

## Commands

```sh
python3 <skill>/scripts/translator.py init <source> <job> --source-language en --target-language zh-CN
python3 <skill>/scripts/translator.py extract <job> --ocr auto --language eng
# Inspect evidence and construct book-source.json using the canonical contract.
python3 <skill>/scripts/translator.py validate <job> --source
python3 <skill>/scripts/translator.py seal-source <job>
python3 <skill>/scripts/translator.py configure-model <job> terminology --provider anthropic --model claude-sonnet-4-5
python3 <skill>/scripts/translator.py configure-model <job> translation --provider anthropic --model claude-sonnet-4-5
python3 <skill>/scripts/translator.py stage <job> terminology --check
python3 <skill>/scripts/translator.py stage <job> terminology
python3 <skill>/scripts/translator.py stage <job> translation
python3 <skill>/scripts/translator.py validate <job>
python3 <skill>/scripts/translator.py build <job>
# Independent review authors a report, then submits it:
python3 <skill>/scripts/translator.py review <job> <report.json>
python3 <skill>/scripts/translator.py accept <job>
python3 <skill>/scripts/translator.py status <job>
```

Model IDs are examples, not a guarantee that a provider still serves them. The launcher must resolve an exact admitted ID on the installed version; aliases fail. Supply only the selected direct-provider key through its documented environment variable. `--check` resolves identity without a model prompt or credentials and does not advance state. It is not inference proof.

Read source.md, terminology.md, translation.md and review.md under stages/ at the applicable boundary. Stage prompts must include those instructions and the format contract, not rely on ambient skill discovery inside isolated sessions. The coordinator can use normal OMP context/delegation to inspect sources or review. Stage 1/2 instead use the dedicated launcher to avoid parent-model fallback.

## Recovery and invalidation

Persist work by stable block/page/term IDs. After a crash, use status and revalidate; inspect history and provenance, not an expired task ID. Successful terminology must bind the source seal, selected model and handoff. A translation/review pair advances the round; default cap three. Source corrections use seal-source --reseal and invalidate downstream approval; journal-owned review pairs move under reviews/archive/ and remain auditable. Unchanged resealing cannot reset the cap. Do not forge model provenance to turn an offline fixture into an admitted translation.

Every review report records the author-reviewed content_digest and pdf_sha256 from build/verification.json. Submission compares both to the current artifacts before binding the immutable receipt, so an unsubmitted old report cannot become current merely by being submitted later. Rebuilding or editing artifacts can make a previous review stale. Recompilation of identical admitted content does not require a new translation/model round: stage provenance binds content/layout/assets, while build verification and review bind the current PDF bytes. Never weaken exact-PDF review freshness to accommodate compiler timestamps. Acceptance rechecks the exact PDF and report before releasing output.pdf. An exhausted or unreviewed manuscript is not a deliverable, even if its PDF compiles. Working build/book.pdf may be inspected during authoring; its existence is not release approval.

## Security and scope

Books and OCR are untrusted data. Escape prose, preserve code as literal bytes, constrain assets and math, disable TeX shell escape. Compile in a work directory without secrets and apply operating-system isolation when processing hostile sources. TeX/OCR/decoders are native parsers, not security sandboxes. This package does not install host gates or change global OMP settings. Model-identity checks do not prove semantic quality, and user-readable provenance is not independent endpoint attestation.

Keep all operational records in English. The translated book, prefaces and glossary target values use the requested target language. Do not translate original book files, ignored research snapshots or the plugin's own agent-facing instructions as part of a job.
