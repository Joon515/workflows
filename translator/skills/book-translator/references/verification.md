# Verification ledger

## Baseline and claim boundaries

[OBSERVED] Executed OMP: 18.10.3. [SOURCE] Inspected upstream pin/version: eb74cf84d8e16ac9b8c4fa5d7c43037023d016ac / 18.11.3; fixed-commit references are in omp-contract.md. These are not interchangeable. Python reported 3.13.11 and PyMuPDF reported 1.28.2. The delivered launcher intentionally supports the exercised OMP version only.

[OBSERVED] `python3 translator/skills/book-translator/scripts/verify_install.py` copied the entire package into isolated .agents/translator and .omp/translator layouts. Actual OMP RPC get_available_commands returned exactly one skill:book-translator command with explicit --plugin-dir and none without it, in both layouts. RPC state had zero messages and no streaming. No provider credentials were forwarded and no model prompt was sent. This establishes registration, not model instruction following or translation effectiveness.

[OBSERVED] The actual translator.py CLI --help enumerated doctor, init, extract, seal-source, validate, render, build, configure-model, stage, review, accept and status. doctor found native PDF/EPUB/MOBI extraction via PyMuPDF. The base host had no ddjvu, djvutxt, Tesseract CLI or discoverable traineddata. OCR and DjVu are conditional dependencies, not silently successful fallback paths. Isolated runtime validation dependencies, where exercised, are listed below separately from the clean-host capability.

## Input and isolated dependency evidence

[OBSERVED] The extraction module exercised actual PDF, EPUB and generated uncompressed MOBI input; scanned PDF, mixed native-text/image PDF and forced OCR; generated DjVu through c44/ddjvu; DjVu hidden spans through djvused/djvutxt; and scanned DjVu OCR. The full extraction module ran 17 tests with 16 passing and one conditional missing-decoder test skipped because a decoder was present. A separate 90-degree mixed-page probe aligned native/image/OCR coordinates, but OCR prose quality was poor; automatic orientation correction and OCR accuracy are not claimed. Margin candidates included xii, A-7 and decimal labels without promoting them to verified pagination.

[OBSERVED] Isolated validation used TESSDATA_PREFIX=/tmp/book-input-runtime/tessdata, PATH=/tmp/book-input-runtime/djvu/usr/bin:$PATH and LD_LIBRARY_PATH=/tmp/book-input-runtime/djvu/usr/lib/x86_64-linux-gnu. No global install or shipped dependency followed. OCR used the embedded PyMuPDF/Tesseract engine with [eng.traineddata](https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/87416418657359cb625c412a48b6e1d6d41c29bd/eng.traineddata), SHA256 7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2. DjVu tools reported DjVuLibre 3.5.28; cjb2 was discovered but not exercised.

Temporary official Debian archives, recorded by URL and SHA256 (archive identity, not an independent trust attestation):

- https://deb.debian.org/debian/pool/main/d/djvulibre/djvulibre-bin_3.5.28-2.2_amd64.deb : a1f23b5d8e382c8567c78e47f4090586054d6bdb5d2dd3363350081b4c49ea1f
- https://deb.debian.org/debian/pool/main/d/djvulibre/libdjvulibre21_3.5.28-2.2_amd64.deb : 576f95b4129c6e06d27c83389a9d0025d65cfff79c82f01936eb44d160b7049d
- https://deb.debian.org/debian/pool/main/libj/libjpeg-turbo/libjpeg62-turbo_2.1.5-4_amd64.deb : 5504299ad0e3c0a9ca9f962a68a650a040db52f9f416a109e74df48d55601d3f

[OBSERVED] Installed metadata identified PyMuPDF1.28.2 as AGPL3/commercial, Pillow12.3.0 as MIT-CMU and jsonschema4.26.0 as MIT; all require Python3.10+. XeTeX was 0.999998 from TeX Live2026 and latexmk4.88. Unpacked DjVu Debian copyright identifies GPL-2.0-or-later; the supporting JPEG archive has multiple licenses. These checks do not resolve a consumer distribution license choice. No upstream binary, language model or third-party book is distributed in this package.

## Initial compiled-PDF observations (superseded inner-margin layout)

[OBSERVED] The representative synthetic fixture compiled with XeLaTeX into 11 A5 pages. The report measured mirrored 26 mm inner / 8 mm outer margins and 15 mm top/bottom; original labels xii and A-7 remained distinct from output pagination, with the unnumbered boundary retaining null. The long note continued across output pages 3 through 7; its last marker FOOTNOTE-END survived. Body-first and note-first terminology both resolved to output page 3 in the appendix. Image/group rectangles retained the shared-canvas offsets and aspect ratios, including side text and a tall indivisible image. This is mechanical fixture evidence, not a translated book.

[OBSERVED] Actual PDF pages 3, 7, 9, 10 and 11 were rasterized with PyMuPDF and observed in Chromium. The visible surface showed bold-italic numbered first terms, outside source labels, a bottom note rule and continued footer content, offset paired images, text beside a complete image canvas, a tall image on a separate page, and the terminology appendix with first-output-page references. The managed browser tab was closed after observation. Visual review sampled these pages; it did not establish semantic quality or every future source-layout case.

[OBSERVED] A separate Chinese-term/preface scenario compiled and was observed on output pages 1, 3 and 11 in Chromium. Chinese first-use terms were visibly bold and slanted with superscripts; their note recurrence was ordinary. The appendix resolved the preface-first term to output page 1 and the body-first term to page 3. The renderer test additionally checks the CJK bold font and PDF slant matrix instead of assuming that an upright CJK italic substitute meets the requirement.

## Initial integrated suite, copy layouts and controller

[OBSERVED] Full command, with the isolated dependency environment above plus BOOK_TRANSLATOR_REAL_OMP_CHECK=1 and PYTHONDONTWRITEBYTECODE=1:

```sh
python3 -m unittest discover -s translator/skills/book-translator/tests
```

Initial result before the inner-margin correction: 127 tests in 26.150 seconds, 126 passed and one conditional missing-decoder test skipped because ddjvu existed. The real installed OMP keyless RPC preflight executed and passed. The full extraction module was also run on the clean host: 17 tests, 16 passed, only the real-decoder scenario skipped; the missing-decoder and missing-OCR failure branches executed. After removing the deprecated PyMuPDF import fallback, the complete 17-test extraction module passed again with isolated real OCR/DjVu dependencies (one opposite-condition skip). No inference was sent. The then-current complete package also passed the two copied-layout smoke scenarios described below. Current-layout evidence is recorded separately below; these initial results are not a claim that the former inner margin remains the contract.

[OBSERVED] A temporary integration driver copied the complete plugin into both .agents/translator and .omp/translator in unrelated temporary projects. Both copies ran actual CLI init, native PDF extraction with Roman-label candidate evidence, source validation/sealing, exact-model configuration and real RPC --check. Both rejected OpenAI configuration and unapproved acceptance. Both validated and built the representative synthetic manuscript into an 11-page A5 PDF with current content/PDF identities; neither released output.pdf without admitted-stage provenance and passing review. The copied .omp PDF was also observed in Chromium. This is end-to-end mechanical authoring/guard evidence, not successful hosted translation or approved release. The temporary driver is not a distributed dependency.

[OBSERVED] Full workflow tests covered stale authored review identities, reports from another job at the same round, changed PDF bytes, replay, failed checks, the third unsuccessful review entering exhausted, missing stage provenance, and old reviewed source to explicit changed-source reseal to a new review round. They also cover identical-content recompilation with different PDF bytes, missing-PDF rebuild recovery without another model round, and rejection of old exact-PDF review reports. Those controller success-path fixtures use synthetic transport/build evidence and do not establish actual non-OpenAI inference or linguistic review. Source resealing archives submitted audit pairs; unchanged resealing cannot reset the cap.

[OBSERVED] A separate real-XeLaTeX controller smoke, explicitly using synthetic model transport, reproduced PDF byte drift on unchanged content, then verified the corrected authority boundary: stage content provenance survived recompilation, an old authored PDF review was rejected, a new current report could be accepted, released bytes matched its reviewed PDF hash, and round remained 1. No cache, hidden model retry or relaxed exact-PDF review was introduced. The temporary job and smoke scaffolding were removed.

[OBSERVED] All authored package assets other than README.md were checked for CJK prose, relative Markdown links were resolved and JSON files parsed. No broken package links or non-English agent-facing prose were found. All operational assets reside inside the skill; obsolete root scripts/tests/templates layouts were removed. The only change outside translator/ is the root README catalog entry and description.

## Current inner-margin correction

[OBSERVED] The binding-side contract now uses the entire inner_min_mm directly, default 20 mm, without additional compensation. Schema, controller initialization/signature/CLI, renderer, TeX templates, width validation and fixtures were migrated together; no compatibility setting or offset path remains. The only retained former-margin measurement above is explicitly historical evidence, not a second active contract.

[OBSERVED] After this correction, the complete suite ran with the isolated OCR/DjVu dependency environment and BOOK_TRANSLATOR_REAL_OMP_CHECK=1: 128 tests in 28.111 seconds, 127 passed and one conditional missing-decoder case skipped because the actual decoder was available. The real OMP keyless preflight executed; no model prompt was sent. Full affected modules also passed individually: core 66 tests, workflow 35 tests with only its opt-in RPC case skipped in that individual run, and renderer 10 tests with real XeLaTeX.

[OBSERVED] A fresh actual CLI init produced a six-field layout with inner_min_mm 20, outer_mm 8, top_mm/bottom_mm 15 and source_mark_edge_mm 3. Feeding that initialized layout into the representative synthetic manuscript and compiling through the renderer produced 10 A5 pages. Compiled geometry measured the odd-page left margin at 19.999997 mm and the even-page left margin at 7.999995 mm, with a 120 by 180 mm text area and 15 mm top/bottom margins. Independent PDF footer-rule measurements confirmed mirrored inner/outer positions at 20/8 mm; a custom entire inner margin of 32 mm also compiled as 32 mm rather than receiving another offset.

[OBSERVED] The corrected default PDF pages 3, 4, 8 and 10 were observed in Chromium, then the tab was closed. The visible surface retained outside printed-page labels, CJK bold/slanted numbered terms, literal formula/code, splitting bottom notes, offset image groups and side text, and appendix page references. The long note still spans output pages 3 through 7; first-use references for both representative terms remain page 3. Reflow from the wider text area changes sample pagination and is expected. Other workflow behavior is covered by the full suite; no extraction, model-routing, review-admission or release policy was changed.

## Verification interpretation

Schema/semantic tests cover selected data boundaries and state transitions; they cannot establish all protected-span discovery, OCR fidelity, translation accuracy or truthfulness of model-supplied research/review. Mechanical PDF checks are not a substitute for visual and semantic review. Synthetic fixtures are development data, not evidence of a real book translated by an admitted model. Runtime identity resolution without a prompt is not inference evidence.

No real hosted-model translation or professional linguistic review has been claimed. No private source was uploaded, no global OMP settings were edited, and no extension or egress gateway was installed. External inference requires authorized source handling and explicit available non-OpenAI credentials. The launcher is not a hostile-agent or network sandbox.
