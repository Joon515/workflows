"""Book unit-checkpoint regressions; metadata fixtures never prove native inference."""
from __future__ import annotations

from collections import Counter
import copy
import io
import json
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
import pymupdf

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import core
import translator as workflow
import units
import test_workflow as domain_fixtures
import test_render as render_fixtures


PROVIDER = "opencode-go"
MODEL = "deepseek-v4-flash-vision-exp"


def unit_output(packet, binding):
    output = {
        "version": 1, "kind": packet["role"] + "-unit-result",
        "unit_id": packet["unit_id"], "packet_sha256": binding["packet_sha256"],
        "inspection": [
            {"page_id": page["page_id"], "image_sha256": page["image_sha256"],
             "findings": [], "protected_checked": True,
             "regions": [{"index": index, "classification": "nonprose"}
                         for index in range(page["raster_region_count"])]}
            for page in packet["pages"] if page["page_id"] in packet["owned_pages"]
        ],
    }
    if packet["role"] == "source":
        output.update(
            source_pages=[
                {"id": page["page_id"], "locator": page["locator"], "printed_label": None,
                 "label_verified": False, "evidence": "Synthetic source-page inspection declaration."}
                for page in packet["pages"] if page["page_id"] in packet["owned_pages"]
            ],
            blocks=copy.deepcopy(packet["blocks"]), notes=copy.deepcopy(packet["notes"]),
            protected=copy.deepcopy(packet["protected"]),
        )
        if packet["metadata_owner"]:
            output["metadata"] = {key: value for key, value in packet["metadata"].items() if value is not None}
            if packet["metadata"]["main_body_start"] is None:
                output["body_start"] = output["blocks"][0]["id"]
    elif packet["role"] == "translation":
        for category in ("blocks", "notes"):
            output[category] = [
                {"id": item["id"], "target": [
                    dict(token) if "text" not in token else {"text": "Translated " + token["text"]}
                    for token in item["source"]
                ]} for item in packet[category]
            ]
        if packet["metadata_owner"]:
            output["metadata"] = {
                "title": "Synthetic translated fixture",
                "agent_preface": [{"text": "Synthetic controller fixture, not a model translation."}],
                "human_preface": None,
            }
    else:
        output.update(
            pdf_inspection=[{"page": page, "evidence": "Synthetic physical-page inspection declaration."}
                            for page in packet["pdf_pages"]],
            checks={name: True for name in workflow.REVIEW_CHECKS}, findings=[], verdict="pass",
            evidence=["Synthetic unit review; no visual or model-quality claim."],
        )
    return output


def synthetic_build(job, page_count=2):
    """Publish a tiny real PDF with synthetic verification, not renderer evidence."""
    book = core.validate_book(job, translated=True)
    directory = job / "build"
    directory.mkdir(exist_ok=True)
    pdf = directory / "book.pdf"
    with pymupdf.open() as document:
        for number in range(1, page_count + 1):
            page = document.new_page(width=419.528, height=595.276)
            page.insert_text((45, 55), f"Synthetic contract PDF page {number}.")
        document.save(pdf)
    blocks = [block for block in book["blocks"] if block["kind"] != "blank"]
    core.save_json(directory / "verification.json", {
        "version": 1, "content_digest": core.content_digest(job),
        "pdf_sha256": workflow.digest_file(pdf), "passed": True,
        "checks": {name: True for name in workflow.BUILD_CHECKS},
        "pages": [{"physical_pdf_page": page} for page in range(1, page_count + 1)],
        "block_boundaries": [
            {"id": block["id"], "start": {"page": 1 if index == 0 else page_count},
             "end": {"page": page_count}}
            for index, block in enumerate(blocks)
        ],
        "notes": [], "agent_preface_pages": [1],
    })
    return pdf


class UnitContractTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="book-unit-contract-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.case_number = 0

    def new_job(self, page_count=2, raster_page=None):
        self.case_number += 1
        directory = self.root / f"case-{self.case_number}"
        directory.mkdir()
        source = directory / "source.pdf"
        with pymupdf.open() as document:
            for number in range(1, page_count + 1):
                page = document.new_page()
                page.insert_text((60, 60), f"Required original source paragraph on physical page {number}.")
                if number == raster_page:
                    image = io.BytesIO()
                    Image.new("RGB", (16, 16), "blue").save(image, format="PNG")
                    page.insert_image(pymupdf.Rect(60, 100, 140, 160), stream=image.getvalue())
            document.save(source)
        job = directory / "job"
        workflow.init_job(source, job, "Synthetic unit fixture", "en", "en")
        for role in workflow.ROLES:
            workflow.configure_model(job, role, PROVIDER, MODEL)
        workflow.extract_job(job, ocr="never", dpi=72)
        return job

    def plan(self, job, role="source", draft=None, pages_per_unit=1):
        reference = workflow.plan_units(job, role, pages_per_unit, draft=draft)
        return core.load_json(job / reference["plan"])

    def prepare(self, job, role, unit_id):
        binding = units.unit_binding(job, role, unit_id)
        packet = core.load_json(job / binding["packet"])
        return {"role": role, "unit_id": unit_id}, binding, packet, unit_output(packet, binding)

    def finish(self, job, prepared, output):
        role, unit_id = prepared["role"], prepared["unit_id"]
        binding = units.unit_binding(job, role, unit_id)
        core.save_json(job / binding["result"], output)
        result = domain_fixtures.save_task_result(self.root / "coordinator-results", role, PROVIDER, MODEL)
        return workflow.checkpoint_unit(job, role, unit_id, result)

    def admit_source(self, job):
        plan = self.plan(job)
        for spec in plan["units"]:
            prepared, _, _, output = self.prepare(job, "source", spec["unit_id"])
            self.finish(job, prepared, output)
        workflow.assemble_units(job, "source")
        workflow.seal_job(job)

    def admit_terminology(self, job, terms=None):
        core.save_json(job / "terms.json", terms if terms is not None else {"version": 1, "terms": []})
        handoff = "Synthetic fixture: governed terminology entries inspected." if terms is not None else "Synthetic fixture: no governed terminology entries."
        (job / "handoff.md").write_text(handoff + "\n", encoding="utf-8")
        task = domain_fixtures.save_task_result(self.root / "coordinator-results", "terminology", PROVIDER, MODEL)
        workflow.checkpoint_role(job, "terminology", task)

    def admit_translation(self, job, plan, pdf_pages=2):
        for spec in plan["units"]:
            prepared, _, _, output = self.prepare(job, "translation", spec["unit_id"])
            self.finish(job, prepared, output)
        with patch("render.build", side_effect=lambda current: synthetic_build(current, pdf_pages)):
            return workflow.assemble_units(job, "translation")

    def translated_job(self, pdf_pages=2):
        job = self.new_job()
        self.admit_source(job)
        self.admit_terminology(job)
        self.admit_translation(job, self.plan(job, "translation"), pdf_pages)
        return job

    def graphic_translation_job(self, relation):
        """Admit the canonical graphic fixture through real extraction-owned units."""
        fixture = render_fixtures.make_graphic_boundary_job(
            self.root / f"graphic-fixture-{self.case_number + 1}", relation)
        job = self.new_job(page_count=3)
        draft = core.load_json(fixture / "book-source.json")
        pages = core.extraction_inventory(job)["pages"]
        page_ids = {original["id"]: page["id"]
                    for original, page in zip(draft["source_pages"], pages, strict=True)}
        for block in draft["blocks"]:
            block["source_pages"] = [page_ids[page] for page in block["source_pages"]]
        for item in draft["blocks"] + draft["notes"]:
            for token in item["source"]:
                if "page" in token:
                    token["page"] = page_ids[token["page"]]
        draft["source_pages"] = []
        core.save_json(fixture / "draft.json", draft)
        source_plan = self.plan(job, draft=fixture / "draft.json")
        for spec in source_plan["units"]:
            prepared, _, _, output = self.prepare(job, "source", spec["unit_id"])
            self.finish(job, prepared, output)
        workflow.assemble_units(job, "source")
        workflow.seal_job(job)
        self.admit_terminology(job)
        return job, self.plan(job, "translation")

    def pending_translation_job(self, page_count=18, spans=None, terms=None, draft_update=None, source_update=None):
        job = self.new_job(page_count=page_count)
        pages = [page["id"] for page in core.extraction_inventory(job)["pages"]]
        spans = dict(spans if spans is not None else ((3, 4), (6, 7), (9, 10), (12, 13), (15, 16)))
        Image.new("RGB", (8, 8), "red").save(job / "note-evidence.png")
        draft = {"title": "Pending translation fixture", "main_body_start": "paragraph1", "source_pages": [],
                 "blocks": [], "notes": [],
                 "protected": [{"id": "SharedName", "kind": "name", "value": "Literal Name"}]}
        for number in range(1, page_count + 1):
            if any(first < number <= last for first, last in spans.items()):
                continue
            last = spans.get(number, number)
            covered = pages[number - 1:last]
            source = []
            for page in covered:
                source.extend(({"page": page}, {"text": f"Original paragraph on {page}. "}))
            source.append({"protected": "SharedName"})
            identifier = f"cross{number}" if last != number else f"paragraph{number}"
            if last != number:
                source.append({"note": f"note{number}"})
                draft["notes"].append({
                    "id": f"note{number}", "content_type": "prose",
                    "source": [{"text": f"Complete original crossing note {number}. "}, {"protected": "SharedName"}],
                    "target": [], "source_evidence": [{"asset": "note-evidence.png", "source_page": covered[-1],
                        "description": "Synthetic original note crop associated with this crossing callout."}],
                })
            draft["blocks"].append({"id": identifier, "kind": "paragraph", "source_pages": covered,
                                    "source": source, "target": []})
        if draft_update is not None:
            draft_update(draft, pages)
        core.save_json(job / "draft.json", draft)
        source_plan = self.plan(job, draft=job / "draft.json", pages_per_unit=6)
        for spec in source_plan["units"]:
            prepared, _, _, output = self.prepare(job, "source", spec["unit_id"])
            if source_update is not None:
                source_update(spec, output)
            self.finish(job, prepared, output)
        workflow.assemble_units(job, "source")
        workflow.seal_job(job)
        self.admit_terminology(job, terms=terms)
        return job, self.plan(job, "translation", pages_per_unit=6)

    def source_rebase_job(self):
        terms = domain_fixtures.terms()
        terms["terms"][0].update(id="OriginalTerm", source="Original Literal Name", target="Verified Literal Name",
                                 protected_ids=["SharedName"])

        def faulty_source(draft, pages):
            draft["blocks"][0]["source"] = [{"page": pages[0]}, {"text": "Original "}, {"protected": "SharedName"}]
            blocks = []
            for block in draft["blocks"]:
                blocks.append(block)
                if block["id"] == "paragraph20":
                    blocks.append({"id": "phantom20", "kind": "paragraph", "source_pages": [pages[19]],
                                   "source": [{"text": "Phantom OCR prose absent from the intended source structure."}], "target": []})
                if block["id"] == "paragraph21":
                    duplicate = copy.deepcopy(block)
                    duplicate.update(id="duplicate21", source=[token for token in duplicate["source"] if "page" not in token])
                    blocks.append(duplicate)
                if block["id"] == "paragraph22":
                    block["source"].append({"protected": "Formula"})
            draft["blocks"] = blocks
            draft["protected"].append({"id": "Formula", "kind": "math", "value": "x + x"})

        def original_source_result(spec, output):
            if spec["unit_id"] == "u0003":
                block = next(item for item in output["blocks"] if item["id"] == "paragraph14")
                block["id"] = "u0003_canonical14"
                next(token for token in block["source"] if "text" in token)["text"] = "Canonical prose verified during original native source work. "

        job, original = self.pending_translation_job(page_count=42, spans=tuple((page, page + 1) for page in range(6, 42, 6)),
                                                     terms=terms, draft_update=faulty_source, source_update=original_source_result)
        for index in (0, 2, 4):
            spec = original["units"][index]
            prepared, _, packet, output = self.prepare(job, "translation", spec["unit_id"])
            if index == 0:
                output["blocks"][0]["target"] = [{"page": packet["owned_pages"][0]}, {"term": "OriginalTerm"}]
            elif index == 2:
                next(token for token in output["blocks"][0]["target"] if "text" in token)["text"] = "Incorrect seam interpretation retained until explicit operator reopening. "
            self.finish(job, prepared, output)
        reference = workflow.plan_units(job, "translation", 3, replan_pending=True)
        pending = core.load_json(job / reference["plan"])
        drafts = {}
        for spec in [item for item in pending["units"] if not (job / item["checkpoint"]).exists()][:4]:
            _, binding, _, output = self.prepare(job, "translation", spec["unit_id"])
            output["blocks"] = output["blocks"][:1]
            output["blocks"][0]["target"] = [{"text": "UNADMITTED HISTORICAL TRANSLATION DRAFT"}]
            core.save_json(job / binding["result"], output)
            drafts[spec["result"]] = (job / spec["result"]).read_bytes()
        return job, original, pending, drafts

    def recovery_tree(self, job):
        """Include empty directories so rejection also proves no partial plan writes."""
        return {path.relative_to(job).as_posix():
                hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
                for path in job.rglob("*")}

    def recovery_build(self, job, overflow=False, overlap=False):
        """Real PDF bytes and explicit synthetic ranges; never glyph/render evidence."""
        book = core.validate_book(job, translated=True)
        pages = {page["id"]: index + 2 for index, page in enumerate(book["source_pages"])}
        pdf = synthetic_build(job, len(pages) + (16 if overflow else 2))
        verification = core.load_json(job / "build/verification.json")
        verification["block_boundaries"] = [
            {"id": block["id"], "start": {"page": min(pages[page] for page in block["source_pages"])},
             "end": {"page": max(pages[page] for page in block["source_pages"])}}
            for block in book["blocks"] if block["kind"] != "blank"]
        callers = {token["note"]: block for block in book["blocks"]
                   for token in block["source"] if "note" in token}
        verification["notes"] = [
            {"id": note["id"], "start": {"page": pages[callers[note["id"]]["source_pages"][-1]]},
             "end": {"page": pages[callers[note["id"]]["source_pages"][-1]]},
             "callout": {"page": pages[callers[note["id"]]["source_pages"][0]]}}
            for note in book["notes"]]
        if overlap:
            next(row for row in verification["block_boundaries"] if row["id"] == "paragraph32").update(
                start={"page": 26}, end={"page": 28})
            next(row for row in verification["notes"] if row["id"] == "note18").update(
                start={"page": 27}, end={"page": 28})
        core.save_json(job / "build/verification.json", verification)
        core.save_json(job / "build/render-manifest.json", {"fixture": "synthetic ranges", "round": workflow.load_job(job)["round"]})
        (job / "build/book.tex").write_text("% Synthetic retained build input, not compiled TeX.\n", encoding="utf-8")
        return pdf

    def recovery_review(self, job, failures=None):
        plan = self.plan(job, "review", pages_per_unit=3)
        if callable(failures):
            failures = failures(plan)

        if failures is None:
            # ACK-like source-unchanged content; no inference from this location string.
            failures = {next(spec["unit_id"] for spec in plan["units"]
                             if "paragraph26" in spec["owned_block_ids"]): "coverage"}
        expected_findings = []
        for spec in plan["units"]:
            prepared, _, _, output = self.prepare(job, "review", spec["unit_id"])
            check = failures.get(spec["unit_id"])
            if check is not None:
                output["verdict"] = "changes_requested"
                if check != "findings_only":
                    output["checks"][check] = False
                if check != "source_pages":
                    finding = {"id": spec["unit_id"] + "_UnchangedACK", "severity": "major",
                               "location": "Intentionally unparseable freeform location",
                               "detail": "Synthetic source-unchanged omission requiring fresh target authoring."}
                    output["findings"] = [finding]
                    expected_findings.append(finding)
            self.finish(job, prepared, output)
        workflow.assemble_units(job, "review")
        round_number = workflow.load_job(job)["round"]
        report = job / f"reviews/round-{round_number}.json"
        self.assertEqual(core.load_json(report)["findings"], expected_findings)
        result = workflow.submit_review(job, report)
        self.assertEqual(result["state"], "exhausted" if round_number == workflow.load_job(job)["max_rounds"] else "changes_requested")
        return plan, [spec["unit_id"] for spec in plan["units"] if spec["unit_id"] in failures]

    def recovery_job(self, shared=False, overflow=False, failure_mode="local"):
        def independent_source(draft, pages):
            for item in draft["blocks"] + draft["notes"]:
                item["source"] = [token for token in item["source"] if "protected" not in token]
            draft["protected"] = []
            if shared:
                draft["protected"] = [{"id": "SharedName", "kind": "name", "value": "Literal Name"}]
                for identifier in ("paragraph26", "paragraph32"):
                    next(block for block in draft["blocks"] if block["id"] == identifier)["source"].append({"protected": "SharedName"})
        job, first = self.pending_translation_job(page_count=36, spans=((6, 7), (18, 19)), draft_update=independent_source)
        for spec in first["units"]:
            prepared, _, _, output = self.prepare(job, "translation", spec["unit_id"])
            self.finish(job, prepared, output)
        # Two real preassembly transitions leave nested origin chains under consumed R0 work.
        for identifier in ("u0002", "u0001"):
            reference = workflow.plan_units(job, "translation", 6, reopen_units=[identifier])
        target = core.load_json(job / reference["plan"])
        for identifier in ("u0001", "u0002"):
            prepared, _, _, output = self.prepare(job, "translation", identifier)
            self.finish(job, prepared, output)
        with patch("render.build", side_effect=lambda current: self.recovery_build(current, overflow, failure_mode == "physical_overlap")):
            workflow.assemble_units(job, "translation")
        self.assertEqual((workflow.load_job(job)["state"], workflow.load_job(job)["round"]), ("translated", 1))
        def select_failures(plan):
            ack = next(spec["unit_id"] for spec in plan["units"] if "paragraph26" in spec["owned_block_ids"])
            if failure_mode == "metadata":
                return {plan["metadata_owner"]: "coverage"}
            if failure_mode == "global_check":
                return {ack: "terminology"}
            if failure_mode == "findings_only":
                return {ack: "findings_only"}
            if failure_mode == "pdf_overflow":
                return {next(spec["unit_id"] for spec in plan["units"] if "_pdf002" in spec["unit_id"]): "typography"}
            if failure_mode == "multiple_check_only":
                crossing = next(spec["unit_id"] for spec in plan["units"] if "cross18" in spec["owned_block_ids"])
                return {ack: "coverage", crossing: "source_pages"}
            return {ack: "coverage"}

        review, failed = self.recovery_review(job, failures=select_failures)
        return job, target, review, failed

    def recovery_request(self, job, identifier="cross6"):
        expected = core.load_json(job / "book-source.json")
        block = next(item for item in expected["blocks"] if item["id"] == identifier)
        block.update(kind="list_item", label="6", list_type="ordered", list_level=1 if block.get("list_level") != 1 else 2)
        directory = job / "work"
        directory.mkdir(exist_ok=True)
        expected_path = directory / "expected-source.json"
        # Different object serialization is accepted only at native candidate comparison.
        expected_path.write_text(json.dumps(expected, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        event = next(event for event in reversed(workflow.load_job(job)["history"]) if event["event"] == "review_submitted")
        request = {"version": 1, "kind": "post-review-source-scope",
                   "submitted_review": {"path": event["receipt"], "sha256": event["receipt_sha256"]},
                   "expected_source": {"path": expected_path.relative_to(job).as_posix(), "sha256": workflow.digest_file(expected_path)},
                   "source_changes": {"block_ids": [identifier], "allowed_fields": ["kind", "source", "label", "list_type", "list_level"]}}
        request_path = directory / "scope.json"
        core.save_json(request_path, request)
        return request_path, request, expected

    def recovery_source(self, job, request_path, expected):
        reference = workflow.plan_units(job, "source", 6, revise=True, reopen_units=["u0001"], post_review_scope=request_path)
        revision = core.load_json(job / reference["plan"])
        prepared, _, _, output = self.prepare(job, "source", "u0001")
        # Independently authored synthetic native result, not proposal-to-result copying.
        block = next(block for block in output["blocks"] if block["id"] == "cross6")
        block.update(kind="list_item", label="6", list_type="ordered",
                     list_level=1 if block.get("list_level") != 1 else 2)
        self.finish(job, prepared, output)
        workflow.assemble_units(job, "source")
        self.assertEqual(core.load_json(job / "book-source.json"), expected)
        workflow.seal_job(job, reseal=True)
        return reference, revision

    def recovery_terms(self, job):
        # Fresh settled metadata is distinct; byte-identical terms are not a reused receipt.
        (job / "handoff.md").write_text(
            "Synthetic fresh whole-source terminology decision: governed terms, protected-name bindings, "
            "target language, register, treatment of untranslated names, title and preface policy remain compatible. "
            "Structural source list changes require new target authoring, not reused review approval.\n", encoding="utf-8")
        task = domain_fixtures.save_task_result(self.root / "coordinator-results", "terminology", PROVIDER, MODEL)
        workflow.checkpoint_role(job, "terminology", task)

    def recovery_terms_and_rebase(self, job, revision_reference):
        self.recovery_terms(job)
        reference = workflow.plan_units(job, "translation", 6, rebase_source=job / revision_reference["plan"],
                                        accept_policy_compatibility=workflow.digest_file(job / "handoff.md"))
        return core.load_json(job / reference["plan"])

    def test_post_review_source_recovery_preserves_consumed_origins_feedback_and_original_cap(self):
        job, old_target, review, failed = self.recovery_job()
        original = workflow.load_job(job)
        old_history = copy.deepcopy(original["history"])
        old_files = {path.relative_to(job).as_posix(): path.read_bytes() for path in job.rglob("*") if path.is_file()}
        old_target_pointer = core.load_json(job / "units/translation/active.json")
        old_source_pointer = core.load_json(job / "units/source/active.json")
        old_native = {spec["unit_id"]: core.load_json(job / spec["checkpoint"]) for spec in old_target["units"]}
        self.assertEqual(old_target["base_round"], 0)
        self.assertIn("carried_checkpoint", next(spec for spec in old_target["units"] if spec["unit_id"] == "u0003"))
        request_path, request, expected = self.recovery_request(job)
        revision_reference, revision = self.recovery_source(job, request_path, expected)
        base_reference = revision["source_revision"]["base"]
        base = core.load_json(job / base_reference["path"])
        post = base["post_review"]
        self.assertEqual((post["original_round"], post["original_max_rounds"]), (1, 3))
        self.assertEqual(post["failed_review_units"], failed)
        self.assertEqual(post["derivation_version"], 1)
        self.assertEqual(base["target_plan"], old_target_pointer)
        self.assertEqual(base["source_plan"], old_source_pointer)
        for field, old_path in (("target_document", "book.json"), ("scope_request", "work/scope.json"),
                                ("expected_source", request["expected_source"]["path"])):
            reference = post[field]
            self.assertEqual(workflow.digest_file(job / reference["path"]), reference["sha256"])
            if old_path in old_files:
                self.assertEqual((job / reference["path"]).read_bytes(), old_files[old_path])
        build_bytes = {content for path, content in old_files.items() if path.startswith("build/")}
        frozen_bytes = {(job / item["path"]).read_bytes() for item in post["build_files"].values()}
        self.assertEqual(frozen_bytes, build_bytes)
        self.assertEqual((workflow.load_job(job)["state"], workflow.load_job(job)["round"]), ("source_ready", 1))
        for spec in revision["units"][1:]:
            self.assertEqual(spec["source_carry"]["checkpoint"]["path"], spec["checkpoint"])
            self.assertEqual(core.load_json(job / spec["result"])["kind"], "source-unit-projection")
        rebased = self.recovery_terms_and_rebase(job, revision_reference)
        self.assertEqual((workflow.load_job(job)["state"], workflow.load_job(job)["round"]), ("changes_requested", 1))
        self.assertEqual(rebased["readiness"]["bindings"]["post_review_base"], base_reference)
        self.assertEqual([(spec["unit_id"], spec["owned_pages"]) for spec in rebased["units"]],
                         [(spec["unit_id"], spec["owned_pages"]) for spec in old_target["units"]])
        bridge = rebased["source_rebase"]
        footprints = bridge["footprints"]
        self.assertNotEqual(footprints["u0001"]["before"], footprints["u0001"]["after"])
        self.assertNotEqual(footprints["u0002"]["before"], footprints["u0002"]["after"])
        self.assertEqual(footprints["u0005"]["before"], footprints["u0005"]["after"])
        self.assertIn("u0005", post["forced_pending"])
        self.assertNotIn("u0005", bridge["carried"])
        old_readonly = core.load_json(job / next(spec for spec in old_target["units"] if spec["unit_id"] == "u0002")["packet"])
        fresh_readonly = core.load_json(job / next(spec for spec in rebased["units"] if spec["unit_id"] == "u0002")["packet"])
        self.assertEqual(fresh_readonly["blocks"], old_readonly["blocks"])
        self.assertEqual(fresh_readonly["notes"], old_readonly["notes"])
        self.assertNotEqual(fresh_readonly["context_blocks"], old_readonly["context_blocks"])
        self.assertEqual(footprints["u0005"]["decision"], "pending")
        self.assertEqual(set(bridge["carried"]), {"u0003", "u0006"})
        for identifier in bridge["carried"]:
            previous = next(spec for spec in old_target["units"] if spec["unit_id"] == identifier)
            current = next(spec for spec in rebased["units"] if spec["unit_id"] == identifier)
            for key in ("packet", "packet_sha256", "result", "checkpoint", "assets_dir"):
                self.assertEqual(current[key], previous[key], (identifier, key))
            self.assertEqual(core.load_json(job / current["checkpoint"]), old_native[identifier])
            self.assertEqual(footprints[identifier]["before"], footprints[identifier]["after"])
        for spec in rebased["units"]:
            if spec["unit_id"] in bridge["carried"]:
                continue
            prepared, _, _, output = self.prepare(job, "translation", spec["unit_id"])
            if spec["unit_id"] == "u0005":
                output["blocks"][0]["target"] = [{"page": spec["owned_pages"][0]}, {"text": "Fresh complete ACK correction."}]
            self.finish(job, prepared, output)
        with patch("render.build", side_effect=self.recovery_build):
            result = workflow.assemble_units(job, "translation")
        self.assertEqual((result["state"], result["round"], workflow.load_job(job)["max_rounds"]), ("translated", 2, 3))
        workflow.translation_ready(job, workflow.load_job(job))
        current = workflow.load_job(job)
        self.assertEqual(current["history"][:len(old_history)], old_history)
        authored = next(event for event in reversed(current["history"]) if event["event"] == "translation_content_authored")
        self.assertEqual(core.load_json(job / authored["receipt"])["base_round"], 1)
        mutable = {"job.json", "book-source.json", "source.sha256", "book.json", "handoff.md",
                   "units/source/active.json", "units/translation/active.json"}
        for name, content in old_files.items():
            if name not in mutable and not name.startswith("build/"):
                self.assertEqual((job / name).read_bytes(), content, name)
        with self.assertRaises(ValueError):
            workflow.submit_review(job, job / "reviews/round-1.json")
        with self.assertRaises(ValueError):
            workflow.accept_job(job)
        self.recovery_review(job)
        path, _, next_expected = self.recovery_request(job)
        reference, _ = self.recovery_source(job, path, next_expected)
        final = self.recovery_terms_and_rebase(job, reference)
        for identifier in units.status(job, "translation")["pending"]:
            prepared, _, _, output = self.prepare(job, "translation", identifier)
            self.finish(job, prepared, output)
        with patch("render.build", side_effect=self.recovery_build):
            last = workflow.assemble_units(job, "translation")
        self.assertEqual((last["state"], last["round"], workflow.load_job(job)["max_rounds"]), ("translated", 3, 3))
        self.assertEqual(final["base_round"], 2)
        self.recovery_review(job)
        self.assertEqual(workflow.load_job(job)["state"], "exhausted")
        path, _, _ = self.recovery_request(job)
        before = self.recovery_tree(job)
        with self.assertRaises(ValueError):
            workflow.plan_units(job, "source", 6, revise=True, reopen_units=["u0001"], post_review_scope=path)
        self.assertEqual(self.recovery_tree(job), before)


    def test_post_review_source_rebase_rechecks_frozen_authority_readiness_policy_and_feedback(self):
        job, target, review, _ = self.recovery_job()
        path, _, expected = self.recovery_request(job)
        revision_ref, revision = self.recovery_source(job, path, expected)
        base_ref = revision["source_revision"]["base"]
        base = core.load_json(job / base_ref["path"])
        self.recovery_terms(job)
        acceptance = workflow.digest_file(job / "handoff.md")

        def refuse(**overrides):
            options = {"rebase_source": job / revision_ref["plan"], "accept_policy_compatibility": acceptance, **overrides}
            before = self.recovery_tree(job)
            with self.assertRaises(ValueError):
                workflow.plan_units(job, "translation", 6, **options)
            self.assertEqual(self.recovery_tree(job), before)

        for options in ({"accept_policy_compatibility": None}, {"accept_policy_compatibility": "0" * 64},
                        {"rebase_source": job / base["source_plan"]["plan"]}, {"rebase_source": None},
                        {"replan_pending": True}, {"reopen_units": ["u0001"]}, {"draft": job / "book.json"}, {"revise": True}):
            with self.subTest(options=options):
                refuse(**options)
        names = {base_ref["path"], revision_ref["plan"], "book-source.json", "book.json", "source.sha256",
                 "terms.json", "handoff.md", "note-evidence.png", "extraction.json"}
        names.update(base[field]["path"] for field in ("job", "source", "terms", "handoff", "seal", "source_receipt", "terminology_receipt"))
        names.update(ref["path"] for field, ref in base["post_review"].items() if isinstance(ref, dict) and set(ref) == {"path", "sha256"})
        names.update(ref["path"] for ref in base["post_review"]["build_files"].values())
        names.update(spec[field] for spec in (target["units"][2], review["units"][-1], revision["units"][0])
                     for field in ("packet", "result", "checkpoint"))
        term_event = next(event for event in reversed(workflow.load_job(job)["history"]) if event["event"] == "stage_terminology")
        names.add(term_event["receipt"])
        for name in sorted(names):
            artifact = job / name
            content = artifact.read_bytes()
            try:
                artifact.write_bytes(content + b"\n ")
                with self.subTest(postfreeze_artifact=name):
                    refuse()
            finally:
                artifact.write_bytes(content)
        _, _, _, seal, bindings = workflow.role_readiness(job, "translation")
        readiness = {"source_digest": seal, "bindings": bindings}
        for field in ("source_digest", "source_seal_sha256", "terminology_receipt_sha256", "terms_sha256",
                      "handoff_sha256", "post_review_base", "extra"):
            invalid = copy.deepcopy(readiness)
            if field == "source_digest":
                invalid[field] = "0" * 64
            elif field == "post_review_base":
                invalid["bindings"][field] = {**base_ref, "sha256": "0" * 64}
            else:
                invalid["bindings"][field] = "0" * 64
            before = self.recovery_tree(job)
            with self.subTest(readiness=field), self.assertRaises(ValueError):
                units.create_plan(job, "translation", pages_per_unit=6, readiness=invalid,
                                  rebase_source=job / revision_ref["plan"], accept_policy_compatibility=acceptance)
            self.assertEqual(self.recovery_tree(job), before)
        reference = workflow.plan_units(job, "translation", 6, rebase_source=job / revision_ref["plan"],
                                        accept_policy_compatibility=acceptance)
        active = job / "units/translation/active.json"
        pointer_bytes = active.read_bytes()
        plan_path = job / reference["plan"]
        plan_bytes = plan_path.read_bytes()
        valid = core.load_json(plan_path)
        for case in ("omitted_feedback", "false_footprint", "forced_carry", "changed_owner", "changed_native_origin"):
            invalid = copy.deepcopy(valid)
            bridge = invalid["source_rebase"]
            if case == "omitted_feedback":
                bridge["footprints"]["u0005"]["review_exclusions"] = []
            elif case == "false_footprint":
                bridge["footprints"]["u0002"]["after"] = bridge["footprints"]["u0002"]["before"]
            elif case == "forced_carry":
                previous = next(spec for spec in target["units"] if spec["unit_id"] == "u0005")
                bridge["carried"]["u0005"] = {"path": previous["checkpoint"], "sha256": workflow.digest_file(job / previous["checkpoint"])}
            elif case == "changed_owner":
                invalid["metadata_owner"] = "u0005"
            else:
                next(spec for spec in invalid["units"] if spec["unit_id"] == "u0003")["carried_checkpoint"]["sha256"] = "0" * 64
            try:
                core.save_json(plan_path, invalid)
                core.save_json(active, {"plan": reference["plan"], "plan_sha256": workflow.digest_file(plan_path)})
                before = self.recovery_tree(job)
                with self.subTest(recomputed=case, endpoint="readiness"), self.assertRaises(ValueError):
                    units.unit_binding(job, "translation", "u0001")
                self.assertEqual(self.recovery_tree(job), before)
            finally:
                plan_path.write_bytes(plan_bytes)
                active.write_bytes(pointer_bytes)
        self.assertEqual(units.status(job, "translation")["admitted"], ["u0003", "u0006"])


    def test_post_review_source_scope_preflight_rejects_unauthorized_complete_proposals_without_writes(self):
        job, _, _, _ = self.recovery_job()
        path, good, expected = self.recovery_request(job)
        expected_path = job / good["expected_source"]["path"]
        original = core.load_json(job / "book-source.json")
        cases = ["missing_expected", "incomplete_expected", "unknown_request_field", "unknown_scope_field",
                 "wrong_kind", "wrong_version", "wrong_hash", "malformed_hash", "wrong_submitted", "missing_file",
                 "empty_ids", "duplicate_ids", "unknown_ids", "outside_owner", "empty_fields", "duplicate_fields",
                 "unsupported_field", "owner_field", "no_change", "extra_unchanged_id", "unlisted_change",
                 "selected_owner_extra_edit", "metadata", "notes", "definitions", "page_inventory", "page_reassignment",
                 "block_order", "block_insert", "block_delete", "block_id", "source_asset", "invalid_structure"]
        for case in cases:
            request, proposal = copy.deepcopy(good), copy.deepcopy(expected)
            selected = next(block for block in proposal["blocks"] if block["id"] == "cross6")
            if case == "missing_expected":
                request.pop("expected_source")
            elif case == "incomplete_expected":
                proposal = {"blocks": proposal["blocks"]}
            elif case == "unknown_request_field":
                request["allow_reset"] = True
            elif case == "unknown_scope_field":
                request["source_changes"]["owner"] = "u0001"
            elif case == "wrong_kind":
                request["kind"] = "source-revision"
            elif case == "wrong_version":
                request["version"] = True
            elif case in {"empty_ids", "duplicate_ids", "unknown_ids", "outside_owner", "extra_unchanged_id"}:
                request["source_changes"]["block_ids"] = {
                    "empty_ids": [], "duplicate_ids": ["cross6", "cross6"], "unknown_ids": ["unknown"],
                    "outside_owner": ["paragraph26"], "extra_unchanged_id": ["cross6", "paragraph1"]}[case]
            elif case in {"empty_fields", "duplicate_fields", "unsupported_field", "owner_field"}:
                request["source_changes"]["allowed_fields"] = {
                    "empty_fields": [], "duplicate_fields": ["kind", "kind"], "unsupported_field": ["target"],
                    "owner_field": ["kind", "source_pages"]}[case]
            elif case == "no_change":
                proposal = copy.deepcopy(original)
            elif case in {"unlisted_change", "selected_owner_extra_edit"}:
                identifier = "paragraph26" if case == "unlisted_change" else "paragraph2"
                next(block for block in proposal["blocks"] if block["id"] == identifier)["source"].append({"text": "Unauthorized extra prose."})
            elif case == "metadata":
                proposal["title"] = "Unauthorized global title"
            elif case == "notes":
                proposal["notes"][0]["source"].append({"text": "Unauthorized note edit."})
            elif case == "definitions":
                proposal["protected"].append({"id": "ExtraName", "kind": "name", "value": "New binding"})
            elif case == "page_inventory":
                proposal["source_pages"][0]["printed_label"] = "new"
            elif case == "page_reassignment":
                selected["source_pages"] = [proposal["source_pages"][0]["id"]]
            elif case == "block_order":
                proposal["blocks"][1:3] = reversed(proposal["blocks"][1:3])
            elif case == "block_insert":
                proposal["blocks"].insert(1, {**copy.deepcopy(proposal["blocks"][0]), "id": "InsertedBlock"})
            elif case == "block_delete":
                proposal["blocks"].pop()
            elif case == "block_id":
                selected["id"] = "ChangedIdentity"
            elif case == "source_asset":
                selected["source_evidence"] = [{"asset": "note-evidence.png", "source_page": selected["source_pages"][0],
                                                  "description": "Unauthorized asset-reference set change."}]
            elif case == "invalid_structure":
                selected["list_level"] = 99
            core.save_json(expected_path, proposal)
            if "expected_source" in request:
                request["expected_source"]["sha256"] = workflow.digest_file(expected_path)
            if case in {"wrong_hash", "malformed_hash"}:
                request["expected_source"]["sha256"] = "0" * 64 if case == "wrong_hash" else "not-sha256"
            elif case == "wrong_submitted":
                request["submitted_review"]["sha256"] = "0" * 64
            elif case == "missing_file":
                request["expected_source"]["path"] = "work/absent.json"
            core.save_json(path, request)
            before = self.recovery_tree(job)
            with self.subTest(case=case, entry="controller"), self.assertRaises(ValueError):
                workflow.plan_units(job, "source", 6, revise=True, reopen_units=["u0001"], post_review_scope=path)
            self.assertEqual(self.recovery_tree(job), before, case)
            _, _, _, seal, bindings = workflow.role_readiness(job, "source", revise=True)
            with self.subTest(case=case, entry="domain"), self.assertRaises(ValueError):
                units.create_plan(job, "source", pages_per_unit=6, revise=True, reopen_units=["u0001"],
                                  readiness={"source_digest": seal, "bindings": bindings}, post_review_scope=path)
            self.assertEqual(self.recovery_tree(job), before, case)
        core.save_json(expected_path, expected)
        good["expected_source"]["sha256"] = workflow.digest_file(expected_path)
        core.save_json(path, good)
        outside = self.root / "outside-expected.json"
        core.save_json(outside, expected)
        link = job / "work/escape.json"
        link.symlink_to(outside)
        for escaped in ("../outside-expected.json", str(outside), "work/escape.json"):
            request = copy.deepcopy(good)
            request["expected_source"]["path"] = escaped
            core.save_json(path, request)
            before = self.recovery_tree(job)
            with self.subTest(expected_path=escaped), self.assertRaises(ValueError):
                workflow.plan_units(job, "source", 6, revise=True, reopen_units=["u0001"], post_review_scope=path)
            self.assertEqual(self.recovery_tree(job), before)
        core.save_json(path, good)
        outside_scope = self.root / "outside-scope.json"
        core.save_json(outside_scope, good)
        for request_path in (outside_scope, job / "work/scope-escape.json"):
            if request_path.parent == job / "work":
                request_path.symlink_to(outside_scope)
            before = self.recovery_tree(job)
            with self.subTest(request_path=request_path.name), self.assertRaises(ValueError):
                workflow.plan_units(job, "source", 6, revise=True, reopen_units=["u0001"], post_review_scope=request_path)
            self.assertEqual(self.recovery_tree(job), before)

    def test_post_review_source_native_whole_owner_and_exact_candidate_are_mandatory(self):
        job, _, _, _ = self.recovery_job()
        path, _, expected = self.recovery_request(job)
        reference = workflow.plan_units(job, "source", 6, revise=True, reopen_units=["u0001"], post_review_scope=path)
        revision = core.load_json(job / reference["plan"])
        selected = next(spec for spec in revision["units"] if spec["unit_id"] == "u0001")
        prepared, binding, packet, complete = self.prepare(job, "source", "u0001")
        next(block for block in complete["blocks"] if block["id"] == "cross6").update(
            kind="list_item", label="6", list_type="ordered", list_level=1)
        canonical_before = {name: (job / name).read_bytes() for name in ("job.json", "book-source.json", "book.json", "source.sha256")}
        for case in ("patch_only", "extra_owner_field", "inspection"):
            output = copy.deepcopy(complete)
            if case == "patch_only":
                output["blocks"] = [block for block in output["blocks"] if block["id"] == "cross6"]
            elif case == "extra_owner_field":
                output["owner"] = "u0001"
            else:
                output["inspection"].pop()
            core.save_json(job / binding["result"], output)
            task = domain_fixtures.save_task_result(self.root / "coordinator-results", "source", PROVIDER, MODEL)
            before = self.recovery_tree(job)
            with self.subTest(case=case), self.assertRaises(ValueError):
                workflow.checkpoint_unit(job, "source", "u0001", task)
            self.assertEqual(self.recovery_tree(job), before)
            self.assertFalse((job / selected["checkpoint"]).exists())
        self.finish(job, prepared, complete)
        base = core.load_json(job / revision["source_revision"]["base"]["path"])
        for ref in (base["post_review"]["expected_source"], base["post_review"]["scope_request"]):
            frozen = job / ref["path"]
            content = frozen.read_bytes()
            try:
                frozen.write_bytes(content + b" ")
                before = self.recovery_tree(job)
                with self.subTest(frozen=frozen.name), self.assertRaises(ValueError):
                    workflow.assemble_units(job, "source")
                self.assertEqual(self.recovery_tree(job), before)
            finally:
                frozen.write_bytes(content)
        for name, content in canonical_before.items():
            self.assertEqual((job / name).read_bytes(), content, name)
        workflow.assemble_units(job, "source")
        self.assertEqual(core.load_json(job / "book-source.json"), expected)

    def test_post_review_source_native_complete_disagreement_never_publishes(self):
        for case in ("extra_selected_owner_edit", "different_allowed_value", "metadata"):
            with self.subTest(case=case):
                job, _, _, _ = self.recovery_job()
                path, _, _ = self.recovery_request(job)
                workflow.plan_units(job, "source", 6, revise=True, reopen_units=["u0001"], post_review_scope=path)
                prepared, _, _, output = self.prepare(job, "source", "u0001")
                next(block for block in output["blocks"] if block["id"] == "cross6").update(
                    kind="list_item", label="6", list_type="ordered", list_level=1)
                if case == "extra_selected_owner_edit":
                    output["blocks"][1]["source"].append({"text": "Unapproved edit elsewhere inside selected whole owner."})
                elif case == "different_allowed_value":
                    next(block for block in output["blocks"] if block["id"] == "cross6")["label"] = "unapproved"
                else:
                    output["metadata"]["title"] = "Unapproved complete-source title"
                self.finish(job, prepared, output)
                before = self.recovery_tree(job)
                with self.assertRaisesRegex(ValueError, "expected_source"):
                    workflow.assemble_units(job, "source")
                self.assertEqual(self.recovery_tree(job), before)
                with self.assertRaises(ValueError):
                    workflow.seal_job(job, reseal=True)
                self.assertEqual(self.recovery_tree(job), before)

    def test_post_review_source_admission_rejects_changed_frozen_inputs_without_writes(self):
        job, target, review, _ = self.recovery_job()
        path, _, _ = self.recovery_request(job)
        data = workflow.load_job(job)
        receipt_events = [event for event in data["history"] if "receipt" in event]
        source_plan = core.load_json(job / core.load_json(job / "units/source/active.json")["plan"])
        names = {"book-source.json", "source.sha256", "book.json", "terms.json", "handoff.md", "extraction.json",
                 "build/book.pdf", "build/verification.json", "note-evidence.png", data["source_file"]}
        names.update(event["receipt"] for event in receipt_events)
        names.update({"reviews/round-1.json", "reviews/round-1.receipt.json"})
        for plan in (source_plan, target, review):
            for spec in plan["units"]:
                names.update(spec[field] for field in ("checkpoint", "packet", "result"))
            # One member per role exercises hash-pinned origin closure without duplicate siblings.
            if plan is not review:
                for spec in plan["units"][1:]:
                    names.difference_update(spec[field] for field in ("checkpoint", "packet", "result"))
        names.add(next(iter(source_plan["pages"].values()))["image"])
        for name in sorted(names):
            artifact = job / name
            content = artifact.read_bytes()
            try:
                artifact.write_bytes(content + b"\n ")
                before = self.recovery_tree(job)
                with self.subTest(artifact=name), self.assertRaises(ValueError):
                    workflow.plan_units(job, "source", 6, revise=True, reopen_units=["u0001"], post_review_scope=path)
                self.assertEqual(self.recovery_tree(job), before)
            finally:
                artifact.write_bytes(content)
        for field, value in (("round", 0), ("round", 2), ("max_rounds", 4), ("state", "translated"),
                             ("source_language", "fr"), ("target_language", "fr"), ("title", "Changed original title"),
                             ("layout", {**data["layout"], "outer_mm": data["layout"]["outer_mm"] + 1}),
                             ("history", [{**data["history"][0], "event": "changed_prefix"}, *data["history"][1:]])):
            content = (job / "job.json").read_bytes()
            try:
                core.save_json(job / "job.json", {**data, field: value})
                before = self.recovery_tree(job)
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    workflow.plan_units(job, "source", 6, revise=True, reopen_units=["u0001"], post_review_scope=path)
                self.assertEqual(self.recovery_tree(job), before)
            finally:
                (job / "job.json").write_bytes(content)
        for role in workflow.ROLES:
            content = (job / "job.json").read_bytes()
            try:
                core.save_json(job / "job.json", {**data, "models": {**data["models"], role: {"provider": "openai-codex", "model": "gpt-6-luna"}}})
                before = self.recovery_tree(job)
                with self.subTest(changed_model=role), self.assertRaises(ValueError):
                    workflow.plan_units(job, "source", 6, revise=True, reopen_units=["u0001"], post_review_scope=path)
                self.assertEqual(self.recovery_tree(job), before)
            finally:
                (job / "job.json").write_bytes(content)


    def test_post_review_source_feedback_closure_includes_context_crossings_notes_shared_and_global_scopes(self):
        expected_forced = {"multiple_check_only": {"u0003", "u0004", "u0005"},
                           "shared_definition": {"u0004", "u0005", "u0006"},
                           "physical_overlap": {"u0003", "u0004", "u0005", "u0006"}}
        for mode in (*expected_forced, "metadata", "global_check", "findings_only", "pdf_overflow"):
            with self.subTest(mode=mode):
                job, target, review, failed = self.recovery_job(shared=mode == "shared_definition",
                    overflow=mode == "pdf_overflow", failure_mode=mode)
                if mode == "multiple_check_only":
                    check_only = next(spec for spec in review["units"] if "cross18" in spec["owned_block_ids"])
                    output = core.load_json(job / check_only["result"])
                    self.assertEqual(output["findings"], [])
                    self.assertFalse(output["checks"]["source_pages"])
                if mode == "pdf_overflow":
                    self.assertTrue(any("_pdf002" in identifier for identifier in failed))
                path, _, expected = self.recovery_request(job)
                reference, revision = self.recovery_source(job, path, expected)
                base = core.load_json(job / revision["source_revision"]["base"]["path"])
                forced = base["post_review"]["forced_pending"]
                self.assertEqual(base["post_review"]["failed_review_units"], failed)
                self.assertEqual(set(forced), expected_forced.get(mode, {spec["unit_id"] for spec in target["units"]}))
                self.assertEqual(set(identifier for reasons in forced.values() for identifier in reasons), set(failed))
                rebased = self.recovery_terms_and_rebase(job, reference)
                carried = set(rebased["source_rebase"]["carried"])
                expected_carry = {"u0003", "u0006"} - set(forced)
                self.assertEqual(carried, expected_carry)
                for identifier in forced:
                    self.assertEqual(rebased["source_rebase"]["footprints"][identifier]["decision"], "pending")
                    self.assertEqual(rebased["source_rebase"]["footprints"][identifier]["review_exclusions"], forced[identifier])
                if mode == "physical_overlap":
                    # No prose-location parser can derive note18/paragraph32 ownership from ACK wording.
                    self.assertEqual(set(forced["u0003"]), set(failed))
                    self.assertEqual(set(forced["u0006"]), set(failed))


    def corrected_source_revision(self, packet, binding):
        output = unit_output(packet, binding)
        output["blocks"] = [block for block in output["blocks"] if block["id"] not in {"phantom20", "duplicate21"}]
        math = next(block for block in output["blocks"] if block["id"] == "paragraph22")
        math.update(kind="display_math", source=[token for token in math["source"] if "page" in token], protected_id="Formula")
        next(item for item in output["protected"] if item["id"] == "Formula")["value"] = "x^2"
        cross = next(block for block in output["blocks"] if block["id"] == "cross24")
        next(token for token in cross["source"] if "text" in token)["text"] = "Verified corrected crossing paragraph. "
        next(note for note in output["notes"] if note["id"] == "note24")["source"][0]["text"] = "Verified corrected crossing note. "
        return output

    def test_pending_translation_resize_preserves_completed_progress_and_one_round(self):
        for completed_index, changes_requested in ((0, False), (1, False), (0, True)):
            with self.subTest(completed="prefix" if completed_index == 0 else "interior", changes_requested=changes_requested):
                if changes_requested:
                    job, original = self.pending_translation_job(page_count=8, spans=((3, 4), (6, 7)))
                    self.admit_translation(job, original)
                    review = domain_fixtures.passing_review(job, 1)
                    review.update(verdict="changes_requested", checks={**review["checks"], "coverage": False})
                    core.save_json(job / "reviews/round-1.json", review)
                    task = domain_fixtures.save_task_result(self.root / "coordinator-results", "review", PROVIDER, MODEL)
                    workflow.checkpoint_role(job, "review", task)
                    workflow.submit_review(job, job / "reviews/round-1.json")
                    original = self.plan(job, "translation", pages_per_unit=6)
                else:
                    job, original = self.pending_translation_job()
                completed = original["units"][completed_index]
                prepared, _, _, output = self.prepare(job, "translation", completed["unit_id"])
                self.finish(job, prepared, output)
                for spec in original["units"]:
                    if spec == completed:
                        continue
                    _, binding, _, draft = self.prepare(job, "translation", spec["unit_id"])
                    draft["blocks"] = draft["blocks"][:1]
                    draft["blocks"][0]["target"] = [{"text": "UNADMITTED OLD PARTIAL DRAFT"}]
                    core.save_json(job / binding["result"], draft)
                    self.assertFalse((job / spec["checkpoint"]).exists())
                active = job / "units/translation/active.json"
                previous = core.load_json(active)
                before_job = (job / "job.json").read_bytes()
                before_files = {path: path.read_bytes() for path in job.rglob("*") if path.is_file() and path != active}
                before_tasks = {path: path.read_bytes() for path in (self.root / "coordinator-results").glob("*.json")}
                completed_reference = {"path": completed["checkpoint"],
                                       "sha256": workflow.digest_file(job / completed["checkpoint"])}

                reference = workflow.plan_units(job, "translation", 3, replan_pending=True)
                resized = core.load_json(job / reference["plan"])
                self.assertEqual(resized["pending_replan"], previous)
                self.assertNotEqual(reference["plan"], previous["plan"])
                self.assertEqual((job / "job.json").read_bytes(), before_job)
                for path, content in (before_files | before_tasks).items():
                    self.assertEqual(path.read_bytes(), content, str(path))
                for field in ("job_sha256", "base_state", "base_round", "revision", "selected_model", "source_file_sha256",
                              "source_digest", "baseline", "extraction_sha256", "page_ids", "max_context_pages", "readiness"):
                    self.assertEqual(resized[field], original[field], field)
                carried = next(spec for spec in resized["units"] if spec["unit_id"] == completed["unit_id"])
                self.assertEqual(carried, {**completed, "carried_checkpoint": completed_reference})
                self.assertEqual(len(carried["owned_pages"]), 6)
                self.assertLessEqual(len(carried["owned_pages"]), 8)
                fresh = [spec for spec in resized["units"] if spec["unit_id"] != completed["unit_id"]]
                expected_pages = [original["page_ids"][offset:offset + 3] for offset in range(0, len(original["page_ids"]), 3)
                                  if original["page_ids"][offset] not in completed["owned_pages"]]
                highest = max(int(spec["unit_id"][1:]) for spec in original["units"])
                self.assertEqual([spec["unit_id"] for spec in fresh],
                                 [f"u{number:04d}" for number in range(highest + 1, highest + 1 + len(expected_pages))])
                self.assertEqual([spec["owned_pages"] for spec in fresh], expected_pages)
                self.assertTrue(all(1 <= len(spec["owned_pages"]) <= 3 for spec in fresh))
                self.assertEqual(Counter(page for spec in resized["units"] for page in spec["owned_pages"]),
                                 Counter(original["page_ids"]))
                progress = units.status(job, "translation")
                self.assertEqual(progress["admitted"], [completed["unit_id"]])
                self.assertEqual(progress["pending"], [spec["unit_id"] for spec in fresh])
                self.assertFalse(progress["complete"])
                with self.assertRaisesRegex(ValueError, "already checkpointed"):
                    units.unit_binding(job, "translation", completed["unit_id"])
                with self.assertRaisesRegex(ValueError, "Every planned unit"):
                    workflow.assemble_units(job, "translation")
                self.assertEqual((job / "job.json").read_bytes(), before_job)
                self.assertEqual(workflow.digest_file(job / "book.json") if (job / "book.json").is_file() else None,
                                 original["baseline"]["book.json"])

                source = core.load_json(job / "book-source.json")
                block_owners = {name: spec["unit_id"] for spec in resized["units"] for name in spec["owned_block_ids"]}
                note_owners = {name: spec["unit_id"] for spec in resized["units"] for name in spec["owned_note_ids"]}
                self.assertEqual(resized["metadata_owner"], block_owners[source["main_body_start"]])
                self.assertEqual(original["metadata_owner"] == completed["unit_id"],
                                 resized["metadata_owner"] == completed["unit_id"])
                earliest = next(spec for spec in resized["units"] if original["page_ids"][0] in spec["owned_pages"])
                self.assertEqual([spec["unit_id"] for spec in resized["units"] if spec["owned_protected_ids"]],
                                 [earliest["unit_id"]])
                for category, singular in (("blocks", "block"), ("notes", "note"), ("protected", "protected")):
                    self.assertEqual(Counter(name for spec in resized["units"] for name in spec[f"owned_{singular}_ids"]),
                                     Counter(item["id"] for item in source[category]))
                readonly_rejected = False
                for spec in fresh:
                    prepared, _, packet, output = self.prepare(job, "translation", spec["unit_id"])
                    for category, singular in (("blocks", "block"), ("notes", "note")):
                        self.assertEqual(packet[category], [item for item in source[category]
                                                           if item["id"] in spec[f"owned_{singular}_ids"]])
                    contexts = [block for block in source["blocks"] if block["id"] not in spec["owned_block_ids"]
                                and set(block["source_pages"]) & set(spec["owned_pages"])]
                    context_note_ids = {token["note"] for block in contexts for token in block["source"] if "note" in token}
                    self.assertEqual(packet["context_blocks"], contexts)
                    self.assertEqual(packet["context_notes"], [note for note in source["notes"] if note["id"] in context_note_ids])
                    self.assertEqual(packet["context_block_owners"], {item["id"]: block_owners[item["id"]] for item in contexts})
                    self.assertEqual(packet["context_note_owners"], {name: note_owners[name] for name in context_note_ids})
                    self.assertEqual(packet["outgoing_block_ids"], [block["id"] for block in packet["blocks"]
                                     if set(block["source_pages"]) - set(spec["owned_pages"])])
                    self.assertEqual(packet["protected"], source["protected"])
                    self.assertEqual(packet["shared_protected_ids"], ["SharedName"])
                    self.assertEqual(packet["metadata_owner"], spec["unit_id"] == resized["metadata_owner"])
                    self.assertEqual(packet["metadata"], {"title": source["title"], "main_body_start": source["main_body_start"]})
                    self.assertLessEqual(len(packet["context_pages"]), 4)
                    self.assertTrue(all(set(block["source_pages"]) <= set(packet["owned_pages"] + packet["context_pages"])
                                        for block in packet["blocks"] + contexts))
                    if contexts and not readonly_rejected:
                        changed = copy.deepcopy(output)
                        changed["blocks"].append({"id": contexts[0]["id"], "target": [{"text": "Unauthorized context edit"}]})
                        with self.assertRaisesRegex(ValueError, "exactly its owned blocks"):
                            self.finish(job, prepared, changed)
                        self.assertFalse((job / spec["checkpoint"]).exists())
                        readonly_rejected = True
                    self.finish(job, prepared, output)
                self.assertTrue(readonly_rejected)
                self.assertTrue(units.status(job, "translation")["complete"])
                self.assertEqual((job / "job.json").read_bytes(), before_job)
                with patch("render.build", side_effect=synthetic_build):
                    result = workflow.assemble_units(job, "translation")
                current = workflow.load_job(job)
                expected_round = original["base_round"] + 1
                self.assertEqual((result["state"], result["round"], current["state"], current["round"]),
                                 ("translated", expected_round, "translated", expected_round))
                events = [event for event in current["history"] if event["event"] == "stage_translation"]
                prior_events = [event for event in json.loads(before_job)["history"] if event["event"] == "stage_translation"]
                self.assertEqual(len(events), len(prior_events) + 1)
                receipt = core.load_json(job / events[-1]["receipt"])
                self.assertIn(completed_reference, receipt["unit_checkpoints"])
                self.assertEqual(receipt["unit_checkpoints"], [
                    {"path": spec["checkpoint"], "sha256": workflow.digest_file(job / spec["checkpoint"])}
                    for spec in resized["units"]])
                workflow.translation_ready(job, current)
                book = core.validate_book(job, translated=True)
                self.assertEqual(book["protected"], source["protected"])
                for category in ("blocks", "notes"):
                    self.assertEqual([item["id"] for item in book[category]], [item["id"] for item in source[category]])
                    self.assertTrue(all(item["target"] for item in book[category]))
                self.assertNotIn("UNADMITTED OLD PARTIAL DRAFT", json.dumps(book))
                with self.assertRaises(ValueError):
                    workflow.finalize_translation(job)
                self.assertEqual(workflow.load_job(job)["round"], expected_round)
                for path, content in (before_files | before_tasks).items():
                    if path not in {job / "job.json", job / "book.json"} and not path.is_relative_to(job / "build"):
                        self.assertEqual(path.read_bytes(), content, str(path))

    def test_pending_translation_resize_refuses_invalid_requests_and_changed_inputs(self):
        job, original = self.pending_translation_job()
        completed = original["units"][0]
        prepared, _, _, output = self.prepare(job, "translation", completed["unit_id"])
        self.finish(job, prepared, output)
        active = job / "units/translation/active.json"
        before_active = active.read_bytes()
        before_job = (job / "job.json").read_bytes()
        requests = [("translation", size, {}) for size in (True, 0, 6, 7, 9)] + [
            ("translation", 3, {"draft": job / "draft.json"}),
            ("translation", 3, {"revise": True}),
            ("terminology", 3, {}),
        ]
        for role, size, options in requests:
            with self.subTest(role=role, size=size, options=options), self.assertRaises(ValueError):
                workflow.plan_units(job, role, size, replan_pending=True, **options)
            self.assertEqual(active.read_bytes(), before_active)
            self.assertEqual((job / "job.json").read_bytes(), before_job)
        for role, other_job in (("source", self.new_job()), ("review", self.translated_job())):
            self.plan(other_job, role, pages_per_unit=2)
            other_active = other_job / f"units/{role}/active.json"
            other_pointer = other_active.read_bytes()
            other_metadata = (other_job / "job.json").read_bytes()
            with self.subTest(eligible_nontranslation_role=role), self.assertRaises(ValueError):
                workflow.plan_units(other_job, role, 1, replan_pending=True)
            self.assertEqual(other_active.read_bytes(), other_pointer)
            self.assertEqual((other_job / "job.json").read_bytes(), other_metadata)
        active.unlink()
        try:
            with self.assertRaises(ValueError):
                workflow.plan_units(job, "translation", 3, replan_pending=True)
            self.assertFalse(active.exists())
        finally:
            active.write_bytes(before_active)

        packet = core.load_json(job / completed["packet"])
        pending = original["units"][1]
        pending_packet = core.load_json(job / pending["packet"])
        changed_files = ["job.json", workflow.load_job(job)["source_file"], "book-source.json", "source.sha256",
                         "terms.json", "handoff.md", "extraction.json", "note-evidence.png", completed["packet"],
                         completed["checkpoint"], completed["result"], packet["pages"][0]["evidence"],
                         packet["pages"][0]["image"], core.load_json(active)["plan"], pending["packet"],
                         pending_packet["pages"][0]["evidence"], pending_packet["pages"][0]["image"]]
        for name in changed_files:
            path = job / name
            content = path.read_bytes()
            try:
                if name == completed["checkpoint"]:
                    core.save_json(path, {**json.loads(content), "completed": False})
                else:
                    path.write_bytes(content + b"\n ")
                with self.subTest(changed=name), self.assertRaises(ValueError):
                    workflow.plan_units(job, "translation", 3, replan_pending=True)
                self.assertEqual(active.read_bytes(), before_active)
            finally:
                path.write_bytes(content)
        try:
            core.save_json(job / "book.json", core.load_json(job / "book-source.json"))
            with self.assertRaises(ValueError):
                workflow.plan_units(job, "translation", 3, replan_pending=True)
            self.assertEqual(active.read_bytes(), before_active)
        finally:
            (job / "book.json").unlink()
        for changes in ({"title": "Changed plan context"}, {"state": "source_ready"},
                        {"round": 1}, {"round": workflow.load_job(job)["max_rounds"]},
                        {"models": {**workflow.load_job(job)["models"],
                                    "translation": {"provider": "openai-codex", "model": "gpt-6-luna"}}}):
            try:
                core.save_json(job / "job.json", {**json.loads(before_job), **changes})
                with self.subTest(job_changes=changes), self.assertRaises(ValueError):
                    workflow.plan_units(job, "translation", 3, replan_pending=True)
                self.assertEqual(active.read_bytes(), before_active)
            finally:
                (job / "job.json").write_bytes(before_job)

        plan_path = job / core.load_json(active)["plan"]
        original_plan_bytes = plan_path.read_bytes()
        checkpoint_path = job / completed["checkpoint"]
        checkpoint_content = checkpoint_path.read_bytes()
        checkpoint_path.unlink()
        for fault in ("duplicate_page", "missing_block", "duplicate_note", "metadata_owner", "readiness"):
            altered = copy.deepcopy(original)
            if fault == "duplicate_page":
                altered["units"][2]["owned_pages"][0] = altered["units"][1]["owned_pages"][0]
            elif fault == "missing_block":
                altered["units"][1]["owned_block_ids"].pop()
            elif fault == "duplicate_note":
                altered["units"][2]["owned_note_ids"].append(altered["units"][1]["owned_note_ids"][0])
            elif fault == "metadata_owner":
                altered["metadata_owner"] = altered["units"][1]["unit_id"]
            else:
                altered["readiness"]["bindings"]["terms_sha256"] = "0" * 64
            try:
                core.save_json(plan_path, altered)
                core.save_json(active, {"plan": plan_path.relative_to(job).as_posix(),
                                        "plan_sha256": workflow.digest_file(plan_path)})
                invalid_active = active.read_bytes()
                with self.subTest(coverage=fault), self.assertRaises(ValueError):
                    workflow.plan_units(job, "translation", 3, replan_pending=True)
                self.assertEqual(active.read_bytes(), invalid_active)
            finally:
                plan_path.write_bytes(original_plan_bytes)
                active.write_bytes(before_active)
        checkpoint_path.write_bytes(checkpoint_content)
        for spec in original["units"][1:]:
            prepared, _, _, output = self.prepare(job, "translation", spec["unit_id"])
            self.finish(job, prepared, output)
        with self.assertRaises(ValueError):
            units.create_plan(job, "translation", pages_per_unit=3, readiness=original["readiness"], replan_pending=True)
        self.assertEqual(active.read_bytes(), before_active)
        self.assertEqual((job / "job.json").read_bytes(), before_job)

    def test_pending_translation_resize_refuses_unbounded_crossing_context(self):
        job, original = self.pending_translation_job(page_count=12, spans=((3, 8),))
        active = job / "units/translation/active.json"
        before_active = active.read_bytes()
        before_job = (job / "job.json").read_bytes()
        self.assertEqual(units.status(job, "translation")["pending"], [spec["unit_id"] for spec in original["units"]])
        with self.assertRaisesRegex(ValueError, "context.*(bound|exceed)|needs.*context"):
            workflow.plan_units(job, "translation", 3, replan_pending=True)
        self.assertEqual(active.read_bytes(), before_active)
        self.assertEqual((job / "job.json").read_bytes(), before_job)
        self.assertEqual(units.status(job, "translation")["pending"], [spec["unit_id"] for spec in original["units"]])

    def test_pending_translation_resize_clips_canonical_bins_and_can_resize_again(self):
        job, original = self.pending_translation_job()
        completed = original["units"][1]
        prepared, _, _, output = self.prepare(job, "translation", completed["unit_id"])
        self.finish(job, prepared, output)
        before_job = (job / "job.json").read_bytes()
        old_checkpoint = (job / completed["checkpoint"]).read_bytes()
        pages = original["page_ids"]
        previous = core.load_json(job / "units/translation/active.json")
        for size, expected, first_id in ((4, [pages[:4], pages[4:6], pages[12:16], pages[16:]], 4),
                                         (3, [pages[:3], pages[3:6], pages[12:15], pages[15:]], 8)):
            reference = workflow.plan_units(job, "translation", size, replan_pending=True)
            plan = core.load_json(job / reference["plan"])
            fresh = [spec for spec in plan["units"] if spec["unit_id"] != completed["unit_id"]]
            self.assertEqual(plan["pending_replan"], previous)
            self.assertEqual([spec["owned_pages"] for spec in fresh], expected)
            self.assertEqual([spec["unit_id"] for spec in fresh], [f"u{number:04d}" for number in range(first_id, first_id + 4)])
            self.assertEqual(units.status(job, "translation")["admitted"], [completed["unit_id"]])
            self.assertEqual((job / completed["checkpoint"]).read_bytes(), old_checkpoint)
            self.assertEqual((job / "job.json").read_bytes(), before_job)
            previous = {name: reference[name] for name in ("plan", "plan_sha256")}

    def test_translation_reopen_corrects_nested_metadata_owner_without_losing_siblings(self):
        terms = domain_fixtures.terms()
        terms["terms"][0].update(id="OriginalTerm", source="Original", target="Corrected original")
        job, original = self.pending_translation_job(terms=terms)
        for spec in original["units"][:2]:
            prepared, _, _, output = self.prepare(job, "translation", spec["unit_id"])
            if spec["unit_id"] == original["metadata_owner"]:
                for token in output["blocks"][0]["target"]:
                    if "text" in token:
                        token["text"] = "Original with incorrect earlier prose and no governed annotation."
            self.finish(job, prepared, output)
        resized_reference = workflow.plan_units(job, "translation", 3, replan_pending=True)
        resized = core.load_json(job / resized_reference["plan"])
        selected, unaffected, *pending = resized["units"]
        self.assertEqual(selected["unit_id"], resized["metadata_owner"])
        self.assertEqual(len(selected["owned_pages"]), 6)
        _, pending_binding, _, pending_draft = self.prepare(job, "translation", pending[0]["unit_id"])
        pending_draft["blocks"] = pending_draft["blocks"][:1]
        pending_draft["blocks"][0]["target"] = [{"text": "UNADMITTED RETAINED PENDING DRAFT"}]
        core.save_json(job / pending_binding["result"], pending_draft)
        for spec in (selected, pending[0]):
            assets = job / spec["assets_dir"]
            assets.mkdir(parents=True, exist_ok=True)
            (assets / "unconsumed.txt").write_text("Historical task-owned data, not completion.\n", encoding="utf-8")
        active = job / "units/translation/active.json"
        previous = core.load_json(active)
        before_job = (job / "job.json").read_bytes()
        before_files = {path: path.read_bytes() for path in job.rglob("*") if path.is_file() and path != active}
        before_tasks = {path: path.read_bytes() for path in (self.root / "coordinator-results").glob("*.json")}
        prior_checkpoint = {"path": selected["checkpoint"], "sha256": workflow.digest_file(job / selected["checkpoint"])}
        old_selected_result = core.load_json(job / selected["result"])
        old_selected_checkpoint = core.load_json(job / selected["checkpoint"])

        reference = workflow.plan_units(job, "translation", 3, reopen_units=[selected["unit_id"]])
        reopened = core.load_json(job / reference["plan"])
        self.assertEqual(reopened["translation_reopen"], {
            **previous, "reopened": [selected["unit_id"]], "prior_checkpoints": {selected["unit_id"]: prior_checkpoint}})
        self.assertEqual([spec["unit_id"] for spec in reopened["units"]], [spec["unit_id"] for spec in resized["units"]])
        for field in ("job_sha256", "base_state", "base_round", "revision", "selected_model", "source_file_sha256",
                      "source_digest", "baseline", "extraction_sha256", "page_ids", "pages", "pages_per_unit",
                      "max_context_pages", "metadata_owner", "readiness"):
            self.assertEqual(reopened[field], resized[field], field)
        replacement = reopened["units"][0]
        changed_paths = {"result", "assets_dir", "checkpoint"}
        unchanged = lambda spec: {name: value for name, value in spec.items() if name not in changed_paths | {"carried_checkpoint"}}
        self.assertEqual(unchanged(replacement), unchanged(selected))
        self.assertNotIn("carried_checkpoint", replacement)
        for field in changed_paths:
            self.assertNotEqual(replacement[field], selected[field], field)
        self.assertFalse((job / replacement["checkpoint"]).exists())
        self.assertFalse((job / replacement["result"]).exists())
        self.assertEqual(reopened["units"][1:], resized["units"][1:])
        self.assertEqual(units.status(job, "translation")["admitted"], [unaffected["unit_id"]])
        self.assertEqual(units.status(job, "translation")["pending"], [selected["unit_id"]] + [spec["unit_id"] for spec in pending])
        self.assertEqual((job / "job.json").read_bytes(), before_job)
        for path, content in (before_files | before_tasks).items():
            self.assertEqual(path.read_bytes(), content, str(path))
        self.assertEqual(workflow.digest_file(job / "book.json") if (job / "book.json").is_file() else None,
                         resized["baseline"]["book.json"])
        for spec in pending:
            prepared, _, _, output = self.prepare(job, "translation", spec["unit_id"])
            self.finish(job, prepared, output)
        _, binding, packet, corrected = self.prepare(job, "translation", selected["unit_id"])
        self.assertEqual(binding["packet"], selected["packet"])
        self.assertEqual(binding["packet_sha256"], selected["packet_sha256"])
        self.assertTrue(packet["metadata_owner"])
        corrected["metadata"]["title"] = "Corrected metadata-owner title"
        corrected["blocks"][0]["target"] = [
            {"page": packet["owned_pages"][0]}, {"term": "OriginalTerm"},
            {"text": " with corrected translated prose."}, {"protected": "SharedName"},
        ]
        core.save_json(job / binding["result"], corrected)
        self.assertEqual(units.status(job, "translation")["pending"], [selected["unit_id"]])
        with self.assertRaisesRegex(ValueError, "Every planned unit"):
            workflow.assemble_units(job, "translation")
        self.assertEqual(workflow.digest_file(job / "book.json") if (job / "book.json").is_file() else None,
                         resized["baseline"]["book.json"])
        self.assertEqual((job / "job.json").read_bytes(), before_job)
        task = domain_fixtures.save_task_result(self.root / "coordinator-results", "translation", PROVIDER, MODEL)
        checkpoint = workflow.checkpoint_unit(job, "translation", selected["unit_id"], task)
        self.assertNotEqual(checkpoint["task"]["id"], old_selected_checkpoint["task"]["id"])
        self.assertTrue(units.status(job, "translation")["complete"])
        self.assertEqual((job / "job.json").read_bytes(), before_job)
        with patch("render.build", side_effect=synthetic_build):
            result = workflow.assemble_units(job, "translation")
        self.assertEqual((result["state"], result["round"]), ("translated", 1))
        current = workflow.load_job(job)
        workflow.translation_ready(job, current)
        book = core.validate_book(job, translated=True)
        self.assertEqual(book["title"], corrected["metadata"]["title"])
        first = next(block for block in book["blocks"] if block["id"] == corrected["blocks"][0]["id"])
        self.assertEqual(first["target"], corrected["blocks"][0]["target"])
        self.assertNotEqual(first["target"], old_selected_result["blocks"][0]["target"])
        self.assertEqual(core.load_json(job / selected["result"]), old_selected_result)
        unaffected_result = core.load_json(job / unaffected["result"])
        for category in ("blocks", "notes"):
            assembled = {item["id"]: item for item in book[category]}
            for item in unaffected_result[category]:
                self.assertEqual(assembled[item["id"]]["target"], item["target"])
        stages = [event for event in current["history"] if event["event"] == "stage_translation"]
        self.assertEqual(len(stages), 1)
        aggregate = core.load_json(job / stages[0]["receipt"])
        self.assertIn(unaffected["carried_checkpoint"], aggregate["unit_checkpoints"])
        self.assertNotIn(prior_checkpoint, aggregate["unit_checkpoints"])
        self.assertIn({"path": replacement["checkpoint"], "sha256": workflow.digest_file(job / replacement["checkpoint"])},
                      aggregate["unit_checkpoints"])
        pending_results = {job / spec["result"] for spec in pending}
        for path, content in (before_files | before_tasks).items():
            if path != job / "job.json" and path not in pending_results:
                self.assertEqual(path.read_bytes(), content, str(path))
        final_pointer = active.read_bytes()
        with self.assertRaises(ValueError):
            workflow.plan_units(job, "translation", 3, reopen_units=[selected["unit_id"]])
        self.assertEqual(active.read_bytes(), final_pointer)
        self.assertEqual(workflow.load_job(job)["round"], 1)

    def test_translation_reopen_refuses_invalid_selectors_flags_and_stale_inputs(self):
        job, plan = self.pending_translation_job()
        for spec in plan["units"][:2]:
            prepared, _, _, output = self.prepare(job, "translation", spec["unit_id"])
            self.finish(job, prepared, output)
        selected, unaffected, pending = plan["units"]
        active = job / "units/translation/active.json"
        before_active = active.read_bytes()
        before_job = (job / "job.json").read_bytes()
        before_tree = {path: path.read_bytes() if path.is_file() else None for path in job.rglob("*")}
        invalid = ([], [""], [" "], [None], [1], selected["unit_id"], ["u9999"],
                   [pending["unit_id"]], [selected["unit_id"], pending["unit_id"]], [selected["unit_id"]] * 2)
        for selectors in invalid:
            with self.subTest(selectors=selectors), self.assertRaises(ValueError):
                workflow.plan_units(job, "translation", 6, reopen_units=selectors)
            self.assertEqual(active.read_bytes(), before_active)
            self.assertEqual((job / "job.json").read_bytes(), before_job)
            self.assertEqual({path: path.read_bytes() if path.is_file() else None for path in job.rglob("*")}, before_tree)
        for size, options in ((3, {}), (7, {}), (True, {}), (6, {"replan_pending": True}),
                              (6, {"draft": job / "draft.json"}), (6, {"revise": True})):
            with self.subTest(size=size, options=options), self.assertRaises(ValueError):
                workflow.plan_units(job, "translation", size, reopen_units=[selected["unit_id"]], **options)
            self.assertEqual(active.read_bytes(), before_active)
            self.assertEqual((job / "job.json").read_bytes(), before_job)
            self.assertEqual({path: path.read_bytes() if path.is_file() else None for path in job.rglob("*")}, before_tree)
        other_job = self.new_job()
        other_plan = self.plan(other_job, "source", pages_per_unit=2)
        prepared, _, _, output = self.prepare(other_job, "source", other_plan["units"][0]["unit_id"])
        self.finish(other_job, prepared, output)
        other_active = other_job / "units/source/active.json"
        other_pointer = other_active.read_bytes()
        other_metadata = (other_job / "job.json").read_bytes()
        with self.assertRaises(ValueError):
            workflow.plan_units(other_job, "source", 2, reopen_units=[other_plan["units"][0]["unit_id"]])
        self.assertEqual(other_active.read_bytes(), other_pointer)
        self.assertEqual((other_job / "job.json").read_bytes(), other_metadata)
        active.unlink()
        try:
            with self.assertRaises(ValueError):
                workflow.plan_units(job, "translation", 6, reopen_units=[selected["unit_id"]])
            self.assertFalse(active.exists())
        finally:
            active.write_bytes(before_active)
        packet = core.load_json(job / pending["packet"])
        changed_files = ["job.json", workflow.load_job(job)["source_file"], "book-source.json", "source.sha256",
                         "terms.json", "handoff.md", "extraction.json", "note-evidence.png", selected["packet"],
                         selected["checkpoint"], selected["result"], unaffected["checkpoint"], unaffected["result"],
                         pending["packet"], packet["pages"][0]["evidence"], packet["pages"][0]["image"],
                         core.load_json(active)["plan"]]
        for name in changed_files:
            path = job / name
            content = path.read_bytes()
            try:
                if name in (selected["checkpoint"], unaffected["checkpoint"]):
                    core.save_json(path, {**json.loads(content), "completed": False})
                else:
                    path.write_bytes(content + b"\n ")
                with self.subTest(changed=name), self.assertRaises(ValueError):
                    workflow.plan_units(job, "translation", 6, reopen_units=[selected["unit_id"]])
                self.assertEqual(active.read_bytes(), before_active)
            finally:
                path.write_bytes(content)
        for changes in ({"state": "changes_requested"}, {"round": 1}, {"round": workflow.load_job(job)["max_rounds"]},
                        {"models": {**workflow.load_job(job)["models"],
                                    "translation": {"provider": "openai-codex", "model": "gpt-6-luna"}}}):
            try:
                core.save_json(job / "job.json", {**json.loads(before_job), **changes})
                with self.subTest(job_changes=changes), self.assertRaises(ValueError):
                    workflow.plan_units(job, "translation", 6, reopen_units=[selected["unit_id"]])
                self.assertEqual(active.read_bytes(), before_active)
            finally:
                (job / "job.json").write_bytes(before_job)
        plan_path = job / core.load_json(active)["plan"]
        old_plan = plan_path.read_bytes()
        try:
            core.save_json(plan_path, {**plan, "kind": "historical-nondomain-plan"})
            core.save_json(active, {"plan": plan_path.relative_to(job).as_posix(), "plan_sha256": workflow.digest_file(plan_path)})
            unsupported_pointer = active.read_bytes()
            with self.assertRaises(ValueError):
                workflow.plan_units(job, "translation", 6, reopen_units=[selected["unit_id"]])
            self.assertEqual(active.read_bytes(), unsupported_pointer)
        finally:
            plan_path.write_bytes(old_plan)
            active.write_bytes(before_active)
        prepared, _, _, output = self.prepare(job, "translation", pending["unit_id"])
        self.finish(job, prepared, output)
        with patch("render.build", side_effect=RuntimeError("Synthetic build failure")), self.assertRaises(RuntimeError):
            workflow.assemble_units(job, "translation")
        authored = (job / "job.json").read_bytes()
        self.assertEqual(workflow.load_job(job)["history"][-1]["event"], "translation_content_authored")
        self.assertEqual((workflow.load_job(job)["state"], workflow.load_job(job)["round"]), ("terminology_ready", 0))
        with self.assertRaises(ValueError):
            units.create_plan(job, "translation", pages_per_unit=6, readiness=plan["readiness"], reopen_units=[selected["unit_id"]])
        self.assertEqual(active.read_bytes(), before_active)
        self.assertEqual((job / "job.json").read_bytes(), authored)
        with patch("render.build", side_effect=synthetic_build):
            result = workflow.finalize_translation(job)
        self.assertEqual((result["state"], result["round"]), ("translated", 1))
        with self.assertRaises(ValueError):
            workflow.plan_units(job, "translation", 6, reopen_units=[selected["unit_id"]])
        self.assertEqual(active.read_bytes(), before_active)
        self.assertEqual(workflow.load_job(job)["round"], 1)

    def test_translation_reopen_accepts_multiple_completed_selectors_without_pending_work(self):
        job = self.new_job(page_count=4)
        self.admit_source(job)
        self.admit_terminology(job)
        candidate = core.load_json(job / "book-source.json")
        for block in candidate["blocks"]:
            block["target"] = copy.deepcopy(block["source"])
        candidate["agent_preface"] = [{"text": "Synthetic unadmitted baseline candidate, not an authored checkpoint."}]
        core.save_json(job / "book.json", candidate)
        core.validate_book(job, translated=True)
        candidate_bytes = (job / "book.json").read_bytes()
        self.assertFalse(any(event["event"] in {"translation_content_authored", "stage_translation"}
                             for event in workflow.load_job(job)["history"]))
        plan = self.plan(job, "translation", pages_per_unit=2)
        for spec in plan["units"]:
            prepared, _, _, output = self.prepare(job, "translation", spec["unit_id"])
            self.finish(job, prepared, output)
        before_job = (job / "job.json").read_bytes()
        initial = {spec["unit_id"]: {"path": spec["checkpoint"], "sha256": workflow.digest_file(job / spec["checkpoint"])}
                   for spec in plan["units"]}
        first, second = plan["units"]
        single_reference = workflow.plan_units(job, "translation", 2, reopen_units=[first["unit_id"]])
        single = core.load_json(job / single_reference["plan"])
        self.assertEqual(single["units"][1], {**second, "carried_checkpoint": initial[second["unit_id"]]})
        self.assertEqual(units.status(job, "translation")["admitted"], [second["unit_id"]])
        self.assertEqual(units.status(job, "translation")["pending"], [first["unit_id"]])
        prepared, _, _, output = self.prepare(job, "translation", first["unit_id"])
        self.finish(job, prepared, output)
        plan = single
        previous = core.load_json(job / "units/translation/active.json")
        old = {spec["unit_id"]: {"path": spec["checkpoint"], "sha256": workflow.digest_file(job / spec["checkpoint"])}
               for spec in plan["units"]}
        selectors = [spec["unit_id"] for spec in reversed(plan["units"])]
        reference = workflow.plan_units(job, "translation", 2, reopen_units=selectors)
        reopened = core.load_json(job / reference["plan"])
        history = reopened["translation_reopen"]
        self.assertEqual({name: history[name] for name in ("plan", "plan_sha256")}, previous)
        self.assertEqual(Counter(history["reopened"]), Counter(selectors))
        self.assertEqual(history["prior_checkpoints"], old)
        self.assertEqual([spec["unit_id"] for spec in reopened["units"]], [spec["unit_id"] for spec in plan["units"]])
        self.assertEqual(units.status(job, "translation")["admitted"], [])
        self.assertEqual(units.status(job, "translation")["pending"], [spec["unit_id"] for spec in plan["units"]])
        self.assertEqual((job / "job.json").read_bytes(), before_job)
        self.assertEqual((job / "book.json").read_bytes(), candidate_bytes)
        resized_reference = workflow.plan_units(job, "translation", 1, replan_pending=True)
        resized = core.load_json(job / resized_reference["plan"])
        self.assertEqual(resized["pending_replan"], {name: reference[name] for name in ("plan", "plan_sha256")})
        self.assertEqual([spec["unit_id"] for spec in resized["units"]], ["u0003", "u0004", "u0005", "u0006"])
        self.assertEqual([spec["owned_pages"] for spec in resized["units"]], [[page] for page in plan["page_ids"]])
        self.assertEqual((job / "job.json").read_bytes(), before_job)
        self.assertEqual((job / "book.json").read_bytes(), candidate_bytes)
        self.admit_translation(job, resized)
        self.assertEqual((workflow.load_job(job)["state"], workflow.load_job(job)["round"]), ("translated", 1))
        for member in list(initial.values()) + list(old.values()):
            self.assertEqual(workflow.digest_file(job / member["path"]), member["sha256"])

    def test_translation_reopen_keeps_historical_context_until_fresh_pending_resize(self):
        job, original = self.pending_translation_job()
        completed = original["units"][1]
        prepared, _, _, output = self.prepare(job, "translation", completed["unit_id"])
        self.finish(job, prepared, output)
        historical_packet = (job / completed["packet"]).read_bytes()
        self.assertEqual(json.loads(historical_packet)["context_block_owners"]["cross6"], "u0001")
        resized_reference = workflow.plan_units(job, "translation", 3, replan_pending=True)
        resized = core.load_json(job / resized_reference["plan"])
        self.assertNotIn("u0001", [spec["unit_id"] for spec in resized["units"]])
        pending = resized["units"][0]
        _, binding, _, draft = self.prepare(job, "translation", pending["unit_id"])
        draft["blocks"] = draft["blocks"][:1]
        core.save_json(job / binding["result"], draft)
        preserved = {job / name: (job / name).read_bytes() for name in
                     (completed["packet"], completed["result"], completed["checkpoint"], pending["result"])}
        before_job = (job / "job.json").read_bytes()
        reopened_reference = workflow.plan_units(job, "translation", 3, reopen_units=[completed["unit_id"]])
        reopened = core.load_json(job / reopened_reference["plan"])
        selected = next(spec for spec in reopened["units"] if spec["unit_id"] == completed["unit_id"])
        self.assertEqual((job / selected["packet"]).read_bytes(), historical_packet)
        self.assertEqual(len(selected["owned_pages"]), 6)
        fresh_reference = workflow.plan_units(job, "translation", 2, replan_pending=True)
        fresh = core.load_json(job / fresh_reference["plan"])
        owner = next(spec for spec in fresh["units"] if original["page_ids"][5] in spec["owned_pages"])
        neighbor = next(spec for spec in fresh["units"] if original["page_ids"][6] in spec["owned_pages"])
        _, _, packet, _ = self.prepare(job, "translation", neighbor["unit_id"])
        self.assertEqual(packet["context_block_owners"]["cross6"], owner["unit_id"])
        self.assertNotEqual(owner["unit_id"], "u0001")
        self.assertEqual(Counter(page for spec in fresh["units"] for page in spec["owned_pages"]), Counter(original["page_ids"]))
        self.assertTrue(all(1 <= len(spec["owned_pages"]) <= 2 for spec in fresh["units"]))
        self.assertEqual(units.status(job, "translation")["admitted"], [])
        self.assertEqual((job / "job.json").read_bytes(), before_job)
        for path, content in preserved.items():
            self.assertEqual(path.read_bytes(), content, str(path))

    def test_source_revision_rebases_only_exact_source_compatible_translation_progress(self):
        job, original, pending, drafts = self.source_rebase_job()
        source_active = job / "units/source/active.json"
        translation_active = job / "units/translation/active.json"
        old_source_pointer = core.load_json(source_active)
        old_target_pointer = core.load_json(translation_active)
        source_plan = core.load_json(job / old_source_pointer["plan"])
        old_source = core.load_json(job / "book-source.json")
        old_job = workflow.load_job(job)
        old_terms = (job / "terms.json").read_bytes()
        old_seal = (job / "source.sha256").read_bytes()
        old_handoff_sha = workflow.digest_file(job / "handoff.md")
        old_files = {path: path.read_bytes() for path in job.rglob("*") if path.is_file()}
        old_completed = {spec["unit_id"]: {"path": spec["checkpoint"], "sha256": workflow.digest_file(job / spec["checkpoint"])}
                         for spec in pending["units"] if (job / spec["checkpoint"]).is_file()}
        self.assertEqual(set(old_completed), {"u0001", "u0003", "u0005"})
        self.assertEqual(len(drafts), 4)
        self.assertEqual(pending["pages_per_unit"], 3)
        for identifier in old_completed:
            self.assertEqual(len(next(spec for spec in pending["units"] if spec["unit_id"] == identifier)["owned_pages"]), 6)
        with self.assertRaises(ValueError):
            workflow.plan_units(job, "translation", 3, rebase_source=job / old_source_pointer["plan"],
                                accept_policy_compatibility=old_handoff_sha)
        for size, options in ((3, {"revise": True, "reopen_units": ["u0004"]}),
                              (6, {"reopen_units": ["u0004"]}), (6, {"revise": True, "reopen_units": []}),
                              (6, {"revise": True, "reopen_units": ["u9999"]}),
                              (6, {"revise": True, "reopen_units": ["u0004", "u0004"]})):
            with self.subTest(source_request=(size, options)), self.assertRaises(ValueError):
                workflow.plan_units(job, "source", size, **options)
            self.assertEqual(core.load_json(source_active), old_source_pointer)
            self.assertEqual(core.load_json(translation_active), old_target_pointer)
            self.assertEqual((job / "job.json").read_bytes(), old_files[job / "job.json"])

        source_member = next(spec for spec in source_plan["units"] if spec["unit_id"] == "u0003")
        for path in (job / "source.sha256", job / source_member["result"], job / "note-evidence.png"):
            content = path.read_bytes()
            try:
                path.write_bytes(content + b"\n ")
                with self.subTest(source_entry_tamper=path.relative_to(job).as_posix()), self.assertRaises(ValueError):
                    workflow.plan_units(job, "source", 6, revise=True, reopen_units=["u0004"])
                self.assertEqual(core.load_json(source_active), old_source_pointer)
                self.assertEqual(core.load_json(translation_active), old_target_pointer)
                self.assertEqual((job / "job.json").read_bytes(), old_files[job / "job.json"])
            finally:
                path.write_bytes(content)
        revision_reference = workflow.plan_units(job, "source", 6, revise=True, reopen_units=["u0004"])
        revision_path = job / revision_reference["plan"]
        revision = core.load_json(revision_path)
        base_reference = revision["source_revision"]["base"]
        base = core.load_json(job / base_reference["path"])
        self.assertEqual(base["kind"], "source-revision-base")
        self.assertEqual(base["source_plan"], old_source_pointer)
        self.assertEqual(base["target_plan"], old_target_pointer)
        self.assertEqual({item["unit_id"]: {"path": item["path"], "sha256": item["sha256"]}
                          for item in base["target_checkpoints"]}, old_completed)
        self.assertEqual(base["target_drafts"], {name: workflow.digest_file(job / name) for name in drafts})
        for name, canonical in (("job", "job.json"), ("source", "book-source.json"), ("seal", "source.sha256"),
                                ("terms", "terms.json"), ("handoff", "handoff.md")):
            reference = base[name]
            self.assertEqual((job / reference["path"]).read_bytes(), old_files[job / canonical], name)
            self.assertEqual(workflow.digest_file(job / reference["path"]), reference["sha256"], name)
        self.assertEqual(units.status(job, "source")["pending"], ["u0004"])
        self.assertEqual([spec["unit_id"] for spec in revision["units"]], [spec["unit_id"] for spec in source_plan["units"]])
        projection_spec = next(spec for spec in revision["units"] if spec["unit_id"] == "u0003")
        original_spec = next(spec for spec in source_plan["units"] if spec["unit_id"] == "u0003")
        self.assertEqual(projection_spec["source_carry"]["checkpoint"], {
            "path": original_spec["checkpoint"], "sha256": workflow.digest_file(job / original_spec["checkpoint"])})
        projection = core.load_json(job / projection_spec["result"])
        self.assertEqual(projection["kind"], "source-unit-projection")
        canonical_blocks = [block for block in old_source["blocks"] if block["source_pages"][0] in original_spec["owned_pages"]]
        self.assertEqual(projection["blocks"], canonical_blocks)
        self.assertEqual(projection_spec["owned_block_ids"], [block["id"] for block in canonical_blocks])
        self.assertNotEqual(projection_spec["owned_block_ids"], original_spec["owned_block_ids"])
        self.assertIn("u0003_canonical14", projection_spec["owned_block_ids"])
        self.assertEqual(projection["notes"], [note for note in old_source["notes"] if note["id"] in original_spec["owned_note_ids"]])
        self.assertEqual(projection["protected"], [])
        self.assertNotEqual(projection["protected"], core.load_json(job / original_spec["result"])["protected"])
        for spec in revision["units"]:
            if spec["unit_id"] == "u0004":
                continue
            previous = next(item for item in source_plan["units"] if item["unit_id"] == spec["unit_id"])
            self.assertEqual(spec["checkpoint"], previous["checkpoint"])
            self.assertEqual(spec["source_carry"]["checkpoint"], {"path": previous["checkpoint"],
                             "sha256": workflow.digest_file(job / previous["checkpoint"])})
            self.assertEqual(spec["source_carry"]["projection"]["path"], spec["result"])
        self.assertEqual((job / "job.json").read_bytes(), old_files[job / "job.json"])
        self.assertEqual((job / "book-source.json").read_bytes(), old_files[job / "book-source.json"])
        self.assertEqual((job / "source.sha256").read_bytes(), old_seal)
        with self.assertRaises(ValueError):
            workflow.plan_units(job, "translation", 3, rebase_source=revision_path, accept_policy_compatibility=old_handoff_sha)
        self.assertEqual(core.load_json(translation_active), old_target_pointer)
        prepared, binding, packet, _ = self.prepare(job, "source", "u0004")
        selected = next(spec for spec in revision["units"] if spec["unit_id"] == "u0004")
        self.assertEqual(packet["blocks"], [block for block in old_source["blocks"] if block["id"] in selected["owned_block_ids"]])
        self.assertTrue({"phantom20", "duplicate21", "paragraph22", "cross24"} <= set(packet["owned_block_ids"]))
        self.assertEqual(set(packet["source_assets"]), {"note-evidence.png"})
        corrected = self.corrected_source_revision(packet, binding)
        for fault in ("unselected", "crossing", "shared_definition"):
            invalid = copy.deepcopy(corrected)
            if fault == "unselected":
                invalid["blocks"].append(copy.deepcopy(old_source["blocks"][0]))
            elif fault == "crossing":
                next(block for block in invalid["blocks"] if block["id"] == "cross24")["source_pages"] = [packet["owned_pages"][-1]]
            else:
                next(item for item in invalid["protected"] if item["id"] == "SharedName")["value"] = "Unauthorized shared name edit"
            with self.subTest(source_output=fault), self.assertRaises(ValueError):
                self.finish(job, prepared, invalid)
            self.assertFalse((job / selected["checkpoint"]).exists())
            self.assertEqual(core.load_json(translation_active), old_target_pointer)
            self.assertEqual((job / "book-source.json").read_bytes(), old_files[job / "book-source.json"])
        self.finish(job, prepared, corrected)
        workflow.assemble_units(job, "source")
        revised_source = core.load_json(job / "book-source.json")
        self.assertFalse({"phantom20", "duplicate21"} & {block["id"] for block in revised_source["blocks"]})
        self.assertEqual(next(block for block in revised_source["blocks"] if block["id"] == "paragraph22")["kind"], "display_math")
        self.assertEqual(next(item for item in revised_source["protected"] if item["id"] == "Formula")["value"], "x^2")
        self.assertEqual((job / "source.sha256").read_bytes(), old_seal)
        with self.assertRaises(ValueError):
            units.validate_aggregate(job, core.load_json(job / base["source_receipt"]["path"]), "source")
        workflow.seal_job(job, reseal=True)
        new_seal = (job / "source.sha256").read_text(encoding="ascii").strip()
        self.assertNotEqual(new_seal, old_seal.decode().strip())
        self.assertEqual((workflow.load_job(job)["state"], workflow.load_job(job)["round"]), ("source_ready", 0))
        stale_pending = next(spec for spec in pending["units"] if spec["unit_id"] not in old_completed)
        with self.assertRaises(ValueError):
            units.unit_binding(job, "translation", stale_pending["unit_id"])
        with self.assertRaises(ValueError):
            workflow.plan_units(job, "translation", 3, rebase_source=revision_path, accept_policy_compatibility=old_handoff_sha)
        self.assertEqual(core.load_json(translation_active), old_target_pointer)
        (job / "handoff.md").write_text(
            f"Synthetic selected Term judgement for the current table. Verified corrected source has {len(revised_source['blocks'])} blocks.\n"
            "Source artifact corrections do not themselves prove policy compatibility; exact operator acceptance is required.\n", encoding="utf-8")
        acceptance = workflow.digest_file(job / "handoff.md")
        self.assertNotEqual(acceptance, old_handoff_sha)

        def term_checkpoint(revise=False):
            task = domain_fixtures.save_task_result(self.root / "coordinator-results", "terminology", PROVIDER, MODEL)
            workflow.checkpoint_role(job, "terminology", task, revise=revise)
            return workflow.terminology_ready(job, workflow.load_job(job))

        changed_terms = json.loads(old_terms)
        changed_terms["terms"][0]["target"] = "Other Literal Name"
        core.save_json(job / "terms.json", changed_terms)
        term_checkpoint()

        def refuse_rebase(role="translation", pages_per_unit=3, **overrides):
            options = {"rebase_source": revision_path, "accept_policy_compatibility": acceptance, **overrides}
            before = {path: path.read_bytes() if path.is_file() else None for path in job.rglob("*")}
            with self.assertRaises(ValueError):
                workflow.plan_units(job, role, pages_per_unit, **options)
            self.assertEqual({path: path.read_bytes() if path.is_file() else None for path in job.rglob("*")}, before)
            self.assertEqual(translation_active.read_bytes(), before[translation_active])

        refuse_rebase()
        (job / "terms.json").write_bytes(old_terms + b"\n")
        term_checkpoint(revise=True)
        refuse_rebase()
        (job / "terms.json").write_bytes(old_terms)
        term_receipt = term_checkpoint(revise=True)
        self.assertEqual(term_receipt["source_digest"], new_seal)
        self.assertEqual((job / "terms.json").read_bytes(), old_terms)
        for options in ({"accept_policy_compatibility": None}, {"accept_policy_compatibility": "0" * 64},
                        {"rebase_source": None}, {"rebase_source": job / old_source_pointer["plan"]},
                        {"replan_pending": True}, {"reopen_units": ["u0001"]}, {"draft": job / "draft.json"}, {"revise": True}):
            with self.subTest(rebase_flags=options):
                refuse_rebase(**options)
        refuse_rebase(pages_per_unit=2)
        refuse_rebase(role="source", pages_per_unit=6)
        critical = [job / name for name in ("book-source.json", "source.sha256", "terms.json", "handoff.md", "note-evidence.png", "extraction.json")]
        critical += [job / old_job["source_file"], job / old_source_pointer["plan"], job / old_target_pointer["plan"]]
        critical += [job / selected[name] for name in ("checkpoint", "result", "packet")]
        critical += [job / packet["pages"][0]["evidence"]]
        critical += [job / next(event for event in reversed(workflow.load_job(job)["history"]) if event["event"] == name)["receipt"]
                     for name in ("stage_terminology", "role_source")]
        critical += [job / base_reference["path"], revision_path, job / projection_spec["result"]]
        critical += [job / base[name]["path"] for name in ("job", "source", "seal", "terms", "handoff", "source_receipt", "terminology_receipt")]
        critical += [job / original_spec[name] for name in ("checkpoint", "result", "packet")]
        critical += [job / next(spec for spec in pending["units"] if spec["unit_id"] == identifier)[name]
                     for identifier in ("u0001", "u0005") for name in ("checkpoint", "result", "packet")]
        critical.append(job / packet["pages"][0]["image"])
        critical.append(job / next(iter(drafts)))
        for path in dict.fromkeys(critical):
            content = path.read_bytes()
            try:
                path.write_bytes(content + b"\n ")
                with self.subTest(tampered=path.relative_to(job).as_posix()):
                    refuse_rebase()
            finally:
                path.write_bytes(content)
        for changes in ({"round": 1}, {"state": "changes_requested"}, {"max_rounds": old_job["max_rounds"] + 1},
                        {"source_language": "fr"}, {"target_language": "fr"}, {"title": "Changed original metadata"},
                        {"layout": {**old_job["layout"], "outer_mm": old_job["layout"]["outer_mm"] + 1}},
                        {"models": {**old_job["models"], "translation": {"provider": "openai-codex", "model": "gpt-6-luna"}}},
                        {"models": {**old_job["models"], "review": {"provider": "openai-codex", "model": "gpt-6-luna"}}}):
            current_bytes = (job / "job.json").read_bytes()
            try:
                core.save_json(job / "job.json", {**json.loads(current_bytes), **changes})
                with self.subTest(rebase_job_changes=changes):
                    refuse_rebase()
            finally:
                (job / "job.json").write_bytes(current_bytes)

        before_rebase = {path: path.read_bytes() for path in job.rglob("*") if path.is_file() and path != translation_active}
        reference = workflow.plan_units(job, "translation", 3, rebase_source=revision_path, accept_policy_compatibility=acceptance)
        rebased = core.load_json(job / reference["plan"])
        bridge = rebased["source_rebase"]
        self.assertEqual(bridge["revision_plan"], {name: revision_reference[name] for name in ("plan", "plan_sha256")})
        self.assertEqual(bridge["base"], base_reference)
        self.assertEqual(bridge["policy_acceptance"]["handoff_sha256"], acceptance)
        self.assertIs(bridge["policy_acceptance"]["accepted"], True)
        self.assertEqual(bridge["carried"], {identifier: old_completed[identifier] for identifier in ("u0001", "u0003")})
        self.assertEqual(rebased["source_digest"], new_seal)
        self.assertEqual(rebased["pages_per_unit"], 3)
        self.assertEqual([spec["unit_id"] for spec in rebased["units"]], [spec["unit_id"] for spec in pending["units"]])
        self.assertEqual([spec["owned_pages"] for spec in rebased["units"]], [spec["owned_pages"] for spec in pending["units"]])
        self.assertEqual(units.status(job, "translation")["admitted"], ["u0001", "u0003"])
        for name in drafts:
            previous = next(spec for spec in pending["units"] if spec["result"] == name)
            replacement = next(spec for spec in rebased["units"] if spec["unit_id"] == previous["unit_id"])
            self.assertEqual(replacement["reading_aid"]["result"], {"path": name, "sha256": workflow.digest_file(job / name)})
            self.assertNotIn("checkpoint", replacement["reading_aid"])
            self.assertNotEqual(replacement["result"], name)
            self.assertFalse((job / replacement["checkpoint"]).exists())
        for identifier in ("u0001", "u0003"):
            previous = next(spec for spec in pending["units"] if spec["unit_id"] == identifier)
            carried = next(spec for spec in rebased["units"] if spec["unit_id"] == identifier)
            for name in ("packet", "packet_sha256", "result", "assets_dir", "checkpoint", "owned_pages", "owned_block_ids", "owned_note_ids", "owned_protected_ids"):
                self.assertEqual(carried[name], previous[name], (identifier, name))
            self.assertEqual(carried["carried_checkpoint"], old_completed[identifier])
            footprint = bridge["footprints"][identifier]
            self.assertEqual(footprint["before"], footprint["after"])
            self.assertEqual(footprint["decision"], "carried")
        readonly_footprint = bridge["footprints"]["u0005"]
        self.assertNotEqual(readonly_footprint["before"], readonly_footprint["after"])
        self.assertEqual(readonly_footprint["decision"], "pending")
        affected = next(spec for spec in rebased["units"] if spec["unit_id"] == "u0005")
        old_affected = next(spec for spec in pending["units"] if spec["unit_id"] == "u0005")
        old_packet = core.load_json(job / old_affected["packet"])
        prepared, _, fresh_packet, full_output = self.prepare(job, "translation", "u0005")
        self.assertEqual(fresh_packet["blocks"], old_packet["blocks"])
        self.assertEqual(fresh_packet["notes"], old_packet["notes"])
        self.assertNotEqual(fresh_packet["context_blocks"], old_packet["context_blocks"])
        self.assertNotEqual(fresh_packet["context_notes"], old_packet["context_notes"])
        self.assertEqual(affected["reading_aid"]["result"], {"path": old_affected["result"], "sha256": workflow.digest_file(job / old_affected["result"])})
        self.assertEqual(affected["reading_aid"]["checkpoint"], old_completed["u0005"])
        self.assertNotEqual(affected["packet"], old_affected["packet"])
        self.assertNotEqual(affected["checkpoint"], old_affected["checkpoint"])
        self.assertFalse((job / affected["checkpoint"]).exists())
        for path, content in before_rebase.items():
            self.assertEqual(path.read_bytes(), content, str(path))
        partial = copy.deepcopy(full_output)
        partial["blocks"] = partial["blocks"][:1]
        with self.assertRaisesRegex(ValueError, "exactly its owned blocks"):
            self.finish(job, prepared, partial)
        self.assertFalse((job / affected["checkpoint"]).exists())
        carried_quality = core.load_json(job / core.load_json(job / old_completed["u0003"]["path"])["result"])
        self.assertEqual(next(token["text"] for token in carried_quality["blocks"][0]["target"] if "text" in token),
                         "Incorrect seam interpretation retained until explicit operator reopening. ")
        quality_reference = workflow.plan_units(job, "translation", 3, reopen_units=["u0003"])
        quality_plan = core.load_json(job / quality_reference["plan"])
        self.assertEqual({name: quality_plan["translation_reopen"][name] for name in ("plan", "plan_sha256")},
                         {name: reference[name] for name in ("plan", "plan_sha256")})
        self.assertEqual(units.status(job, "translation")["admitted"], ["u0001"])
        for spec in rebased["units"]:
            replacement = next(item for item in quality_plan["units"] if item["unit_id"] == spec["unit_id"])
            if spec["unit_id"] != "u0003":
                self.assertEqual(replacement, spec)
            else:
                self.assertEqual(replacement["packet"], spec["packet"])
                self.assertEqual(replacement["packet_sha256"], spec["packet_sha256"])
                self.assertNotEqual(replacement["checkpoint"], spec["checkpoint"])
        before_completion = (job / "job.json").read_bytes()
        quality_correction = None
        for spec in quality_plan["units"]:
            if spec["unit_id"] == "u0001":
                continue
            prepared, _, current_packet, output = self.prepare(job, "translation", spec["unit_id"])
            self.assertFalse({"phantom20", "duplicate21"} & set(current_packet["owned_block_ids"]))
            if spec["unit_id"] == "u0003":
                next(token for token in output["blocks"][0]["target"] if "text" in token)["text"] = "Operator-requested semantic correction after explicit reopening. "
                quality_correction = copy.deepcopy(output["blocks"][0])
            checkpoint = self.finish(job, prepared, output)
            if spec["unit_id"] == "u0003":
                self.assertEqual(checkpoint["source_digest"], new_seal)
                self.assertNotEqual(checkpoint["task"]["id"], core.load_json(job / old_completed["u0003"]["path"])["task"]["id"])
        self.assertEqual((job / "job.json").read_bytes(), before_completion)
        with patch("render.build", side_effect=synthetic_build):
            result = workflow.assemble_units(job, "translation")
        self.assertEqual((result["state"], result["round"]), ("translated", 1))
        current = workflow.load_job(job)
        workflow.translation_ready(job, current)
        book = core.validate_book(job, translated=True)
        self.assertEqual([block["id"] for block in book["blocks"]], [block["id"] for block in revised_source["blocks"]])
        self.assertIsNotNone(quality_correction)
        self.assertEqual(next(block for block in book["blocks"] if block["id"] == quality_correction["id"])["target"],
                         quality_correction["target"])
        event = next(event for event in reversed(current["history"]) if event["event"] == "stage_translation")
        aggregate = core.load_json(job / event["receipt"])
        self.assertIn(old_completed["u0001"], aggregate["unit_checkpoints"])
        self.assertNotIn(old_completed["u0003"], aggregate["unit_checkpoints"])
        self.assertEqual(current["models"], old_job["models"])
        self.assertEqual(current["max_rounds"], old_job["max_rounds"])
        self.assertEqual(len([event for event in current["history"] if event["event"] == "stage_translation"]), 1)
        allowed_changes = {source_active, translation_active, job / "job.json", job / "book-source.json",
                           job / "source.sha256", job / "handoff.md"}
        for path, content in old_files.items():
            if path not in allowed_changes:
                self.assertEqual(path.read_bytes(), content, str(path))
        for name, content in drafts.items():
            self.assertEqual((job / name).read_bytes(), content, name)
        self.assertNotIn("UNADMITTED HISTORICAL TRANSLATION DRAFT", json.dumps(book))
        refuse_rebase()
        before_source_refusal = {path: path.read_bytes() for path in (source_active, translation_active, job / "job.json")}
        with self.assertRaises(ValueError):
            workflow.plan_units(job, "source", 6, revise=True, reopen_units=["u0004"])
        for path, content in before_source_refusal.items():
            self.assertEqual(path.read_bytes(), content, str(path))
        self.assertEqual(workflow.load_job(job)["round"], 1)

    def test_extraction_lineage_and_complete_small_source_inventory(self):
        job = self.new_job()
        extraction = core.load_json(job / "extraction.json")
        extraction["pages"] = extraction["pages"][:1]
        core.save_json(job / "extraction.json", extraction)
        with self.assertRaisesRegex(ValueError, "controller-recorded extraction"):
            self.plan(job)
        self.assertFalse((job / "book-source.json").exists())
        job = self.new_job()
        page = core.extraction_inventory(job)["pages"][0]
        core.save_json(job / "book-source.json", domain_fixtures.source_book(page["locator"]))
        task = domain_fixtures.save_task_result(self.root / "coordinator-results", "source", PROVIDER, MODEL)
        with self.assertRaisesRegex(ValueError, "every original extraction page"):
            workflow.checkpoint_role(job, "source", task)
        with self.assertRaisesRegex(ValueError, "every original extraction page"):
            workflow.seal_job(job)
        self.assertFalse((job / "source.sha256").exists())
        self.assertFalse(any(event["event"] == "role_source" for event in workflow.load_job(job)["history"]))

    def test_durable_out_of_order_siblings_keep_shared_protected_references(self):
        job = self.new_job()
        pages = core.extraction_inventory(job)["pages"]
        draft = {
            "title": "Shared protected fixture", "main_body_start": "first", "source_pages": [],
            "blocks": [
                {"id": name, "kind": "paragraph", "source_pages": [page["id"]],
                 "source": [{"page": page["id"]}, {"protected": "SharedName"}], "target": []}
                for name, page in zip(("first", "second"), pages)
            ],
            "notes": [], "protected": [{"id": "SharedName", "kind": "name", "value": "Literal Name"}],
        }
        core.save_json(job / "draft.json", draft)
        plan = self.plan(job, draft=job / "draft.json")
        siblings = [self.prepare(job, "source", spec["unit_id"]) for spec in plan["units"]]
        before = (job / "job.json").read_bytes()
        prepared, _, packet, output = siblings[1]
        self.assertEqual(packet["shared_protected_ids"], ["SharedName"])
        changed = copy.deepcopy(output)
        changed["protected"][0]["value"] = "Changed Name"
        with self.assertRaisesRegex(ValueError, "protected definitions are read-only"):
            self.finish(job, prepared, changed)
        self.finish(job, prepared, output)
        progress = units.status(job, "source")
        self.assertEqual((progress["admitted"], progress["pending"]), (["u0002"], ["u0001"]))
        with self.assertRaisesRegex(ValueError, "Every planned unit"):
            workflow.assemble_units(job, "source")
        self.assertFalse((job / "book-source.json").exists())
        self.assertEqual((job / "job.json").read_bytes(), before)
        prepared, _, _, output = siblings[0]
        self.finish(job, prepared, output)
        self.assertEqual((job / "job.json").read_bytes(), before)
        workflow.assemble_units(job, "source")
        book = core.load_json(job / "book-source.json")
        self.assertEqual(len(book["protected"]), 1)
        self.assertEqual(sum(token.get("protected") == "SharedName"
                             for block in book["blocks"] for token in block["source"]), 2)
        receipt = workflow.latest_role_receipt(job, workflow.load_job(job), "source")
        self.assertEqual(receipt["execution"], "units")
        self.assertEqual(len(receipt["unit_checkpoints"]), 2)
        self.assertNotIn("child_id", receipt)
        self.assertFalse((job / "source.sha256").exists())
        workflow.seal_job(job)

    def test_crossing_preservation_and_page_bound_raster_semantics(self):
        job = self.new_job()
        first, second = [page["id"] for page in core.extraction_inventory(job)["pages"]]
        draft = {
            "title": "Crossing fixture", "main_body_start": "first", "source_pages": [],
            "blocks": [
                {"id": "first", "kind": "paragraph", "source_pages": [first],
                 "source": [{"page": first}, {"text": "Initial paragraph."}], "target": []},
                {"id": "cross", "kind": "paragraph", "source_pages": [first, second],
                 "source": [{"text": "Begin "}, {"page": second}, {"text": "crossing continuation."}], "target": []},
                {"id": "after", "kind": "paragraph", "source_pages": [second],
                 "source": [{"text": "Independent next paragraph."}], "target": []},
            ], "notes": [], "protected": [],
        }
        core.save_json(job / "draft.json", draft)
        self.plan(job, draft=job / "draft.json")
        prepared, binding, _, original = self.prepare(job, "source", "u0001")
        _, _, neighbor, _ = self.prepare(job, "source", "u0002")
        self.assertEqual([block["id"] for block in neighbor["context_blocks"]], ["cross"])
        self.assertEqual(neighbor["context_block_owners"]["cross"], "u0001")
        for mutation in ("shrink", "drop"):
            with self.subTest(mutation=mutation):
                output = copy.deepcopy(original)
                if mutation == "shrink":
                    next(block for block in output["blocks"] if block["id"] == "cross").update(
                        source_pages=[first], source=[{"text": "Begin "}])
                else:
                    output["blocks"] = [block for block in output["blocks"] if block["id"] != "cross"]
                with self.assertRaisesRegex(ValueError, "outgoing source block/span"):
                    self.finish(job, prepared, output)
                self.assertEqual(core.load_json(job / binding["result"]), output)
        self.assertFalse((job / "book-source.json").exists())

        job = self.new_job(raster_page=2)
        self.plan(job, pages_per_unit=2)
        prepared, _, packet, output = self.prepare(job, "source", "u0001")
        first, second = packet["owned_pages"]
        first_block = next(block for block in output["blocks"] if block["source_pages"] == [first])
        inspection = next(item for item in output["inspection"] if item["page_id"] == second)
        self.assertTrue(inspection["regions"])
        inspection["regions"][0].update(classification="prose", semantic_ids=[first_block["id"]])
        with self.assertRaisesRegex(ValueError, "semantics on its actual source page"):
            self.finish(job, prepared, output)

    def test_immutable_assets_and_controller_owned_review_artifacts(self):
        job = self.new_job()
        first, second = [page["id"] for page in core.extraction_inventory(job)["pages"]]
        Image.new("RGB", (8, 8), "red").save(job / "art.png")
        draft = {
            "title": "Asset fixture", "main_body_start": "art", "source_pages": [],
            "blocks": [
                {"id": "art", "kind": "image", "source_pages": [first], "source": [{"page": first}],
                 "target": [], "asset": "art.png", "width": 8, "height": 8, "source_em": 1,
                 "scale_evidence": "Synthetic source geometry calibration."},
                {"id": "after", "kind": "paragraph", "source_pages": [second],
                 "source": [{"page": second}, {"text": "Other source paragraph."}], "target": []},
            ], "notes": [], "protected": [],
        }
        core.save_json(job / "draft.json", draft)
        self.plan(job, draft=job / "draft.json")
        prepared, _, _, output = self.prepare(job, "source", "u0001")
        Image.new("RGB", (8, 8), "blue").save(job / "art.png")
        with self.assertRaisesRegex(ValueError, "Immutable draft/source asset"):
            self.finish(job, prepared, output)
        self.assertFalse((job / "book-source.json").exists())

        job = self.translated_job()
        plan = self.plan(job, "review")
        prepared, _, _, output = self.prepare(job, "review", plan["units"][0]["unit_id"])
        before = (job / "job.json").read_bytes()
        for suffix in ("json", "receipt.json"):
            with self.subTest(artifact=suffix):
                path = job / f"reviews/round-1.{suffix}"
                core.save_json(path, {"unauthorized": "Synthetic worker canonical write."})
                with self.assertRaisesRegex(ValueError, "controller-owned canonical review artifact"):
                    self.finish(job, prepared, output)
                path.unlink()
                self.assertEqual((job / "job.json").read_bytes(), before)
        self.finish(job, prepared, output)
        self.assertFalse((job / "reviews/round-1.json").exists())

    def test_fresh_body_boundary_requires_one_owned_candidate(self):
        for mode in ("missing", "conflicting", "unique"):
            with self.subTest(boundary=mode):
                job = self.new_job()
                plan = self.plan(job)
                candidate = None
                for index, spec in enumerate(plan["units"]):
                    prepared, _, _, output = self.prepare(job, "source", spec["unit_id"])
                    output.pop("body_start", None)
                    if mode == "conflicting" or (mode == "unique" and index == 1):
                        output["body_start"] = output["blocks"][0]["id"]
                        candidate = output["body_start"]
                    self.finish(job, prepared, output)
                if mode == "unique":
                    workflow.assemble_units(job, "source")
                    self.assertEqual(core.load_json(job / "book-source.json")["main_body_start"], candidate)
                else:
                    with self.assertRaisesRegex(ValueError, "exactly one verified main-body boundary"):
                        workflow.assemble_units(job, "source")
                    self.assertFalse((job / "book-source.json").exists())
        job = self.new_job()
        self.plan(job)
        prepared, _, _, output = self.prepare(job, "source", "u0001")
        _, _, _, neighbor = self.prepare(job, "source", "u0002")
        output["body_start"] = neighbor["blocks"][0]["id"]
        with self.assertRaisesRegex(ValueError, "own nonblank source block"):
            self.finish(job, prepared, output)

    def test_review_reopen_preserves_history_and_admits_inflight_work_before_exact_aggregate(self):
        job = self.translated_job(pdf_pages=20)
        original = self.plan(job, "review")
        selected, unaffected, *pending = original["units"]
        old_checkpoints, outputs = {}, {}
        carried_finding = {"id": unaffected["unit_id"] + "_CarriedFinding", "severity": "major", "location": unaffected["unit_id"],
                           "detail": "Retain this independently completed sibling finding."}
        for spec in (selected, unaffected):
            prepared, _, _, output = self.prepare(job, "review", spec["unit_id"])
            output["evidence"] = ["Completed review scope " + spec["unit_id"]]
            if spec is unaffected:
                output.update(findings=[carried_finding], verdict="changes_requested")
                output["checks"]["typography"] = False
            outputs[spec["unit_id"]] = output
            old_checkpoints[spec["unit_id"]] = self.finish(job, prepared, output)
        self.assertEqual(outputs[selected["unit_id"]]["verdict"], "pass")
        inflight = {}
        for spec in pending:
            _, binding, _, output = self.prepare(job, "review", spec["unit_id"])
            output["evidence"] = ["Completed in-flight scope " + spec["unit_id"]]
            inflight[spec["unit_id"]] = (binding, output)
            draft = copy.deepcopy(output)
            draft["evidence"] = ["Unadmitted partial review draft " + spec["unit_id"]]
            core.save_json(job / binding["result"], draft)
        active = job / "units/review/active.json"
        previous = core.load_json(active)
        before_job = (job / "job.json").read_bytes()
        before_build = workflow.current_build(job)
        frozen = {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file() and path != active}
        prior_checkpoint = {"path": selected["checkpoint"], "sha256": workflow.digest_file(job / selected["checkpoint"])}

        reference = workflow.plan_units(job, "review", original["pages_per_unit"], reopen_units=[selected["unit_id"]])
        successor = core.load_json(job / reference["plan"])
        self.assertEqual(successor["review_reopen"], {
            **previous, "reopened": [selected["unit_id"]], "prior_checkpoints": {selected["unit_id"]: prior_checkpoint}})
        self.assertNotEqual(reference["plan"], previous["plan"])
        self.assertEqual({key: value for key, value in successor.items() if key not in {"plan_id", "units", "review_reopen"}},
                         {key: value for key, value in original.items() if key not in {"plan_id", "units"}})
        replacement, carried, *preserved_pending = successor["units"]
        changed_paths = {"result", "assets_dir", "checkpoint"}
        self.assertEqual({key: value for key, value in replacement.items() if key not in changed_paths},
                         {key: value for key, value in selected.items() if key not in changed_paths})
        for field in changed_paths:
            self.assertNotEqual(replacement[field], selected[field], field)
            self.assertFalse((job / replacement[field]).exists(), field)
        self.assertEqual(carried, {**unaffected, "carried_checkpoint": {
            "path": unaffected["checkpoint"], "sha256": workflow.digest_file(job / unaffected["checkpoint"])}})
        self.assertEqual(preserved_pending, pending)
        self.assertEqual([spec["unit_id"] for spec in successor["units"]], [spec["unit_id"] for spec in original["units"]])
        self.assertEqual(Counter(page for spec in successor["units"] for page in spec["pdf_pages"]), Counter(range(1, 21)))
        self.assertTrue(all(len(spec["pdf_pages"]) <= 8 and len(spec["context_pdf_pages"]) <= 2
                            for spec in successor["units"]))
        self.assertEqual(units.status(job, "review")["admitted"], [unaffected["unit_id"]])
        self.assertEqual(units.status(job, "review")["pending"], [selected["unit_id"]] + [spec["unit_id"] for spec in pending])
        self.assertFalse(units.status(job, "review")["complete"])
        self.assertEqual(workflow.current_build(job), before_build)
        self.assertEqual((job / "job.json").read_bytes(), before_job)
        for path, content in frozen.items():
            self.assertEqual(path.read_bytes(), content, str(path))
        for spec in (selected, unaffected):
            checkpoint_path = job / spec["checkpoint"]
            checkpoint_bytes = checkpoint_path.read_bytes()
            try:
                checkpoint_path.write_bytes(checkpoint_bytes + b"\n ")
                before_rejected_reopen = {path: path.read_bytes() if path.is_file() else None for path in self.root.rglob("*")}
                with self.subTest(bound_checkpoint=spec["unit_id"]), self.assertRaises(ValueError):
                    workflow.plan_units(job, "review", original["pages_per_unit"], reopen_units=[unaffected["unit_id"]])
                self.assertEqual({path: path.read_bytes() if path.is_file() else None for path in self.root.rglob("*")}, before_rejected_reopen)
            finally:
                checkpoint_path.write_bytes(checkpoint_bytes)
        with self.assertRaises(ValueError):
            units.unit_binding(job, "review", unaffected["unit_id"])

        for spec in pending:
            old_binding, output = inflight[spec["unit_id"]]
            current_binding = units.unit_binding(job, "review", spec["unit_id"])
            for field in ("unit_id", "packet", "packet_sha256", "result", "assets_dir"):
                self.assertEqual(current_binding[field], old_binding[field], field)
            self.assertEqual(old_binding["plan"], previous["plan"])
            self.assertNotEqual(current_binding["plan"], old_binding["plan"])
            core.save_json(job / old_binding["result"], output)
            task = domain_fixtures.save_task_result(self.root / "coordinator-results", "review", PROVIDER, MODEL)
            checkpoint = workflow.checkpoint_unit(job, "review", spec["unit_id"], task)
            self.assertEqual(checkpoint["packet_sha256"], old_binding["packet_sha256"])
            self.assertEqual(checkpoint["task"], core.load_json(task))
            outputs[spec["unit_id"]] = output
        _, binding, packet, corrected = self.prepare(job, "review", selected["unit_id"])
        new_finding = {"id": selected["unit_id"] + "_SelectedNewFinding", "severity": "major", "location": selected["unit_id"],
                       "detail": "A newly reported defect replaces the selected unit's former pass."}
        corrected.update(findings=[new_finding], verdict="changes_requested", evidence=["Replacement review scope " + selected["unit_id"]])
        corrected["checks"]["coverage"] = False
        core.save_json(job / binding["result"], corrected)
        self.assertEqual(binding["packet"], selected["packet"])
        self.assertEqual(binding["packet_sha256"], selected["packet_sha256"])
        self.assertEqual(packet["pdf_pages"], selected["pdf_pages"])
        self.assertEqual(units.status(job, "review")["pending"], [selected["unit_id"]])
        before_rejected_assembly = {path: path.read_bytes() if path.is_file() else None for path in self.root.rglob("*")}
        with self.assertRaises(ValueError):
            workflow.assemble_units(job, "review")
        self.assertEqual({path: path.read_bytes() if path.is_file() else None for path in self.root.rglob("*")}, before_rejected_assembly)
        self.assertFalse((job / "reviews/round-1.json").exists())
        task = domain_fixtures.save_task_result(self.root / "coordinator-results", "review", PROVIDER, MODEL)
        checkpoint = workflow.checkpoint_unit(job, "review", selected["unit_id"], task)
        self.assertEqual(checkpoint["task"], core.load_json(task))
        self.assertNotEqual(checkpoint["task"]["id"], old_checkpoints[selected["unit_id"]]["task"]["id"])
        self.assertEqual((job / "job.json").read_bytes(), before_job)
        self.assertTrue(units.status(job, "review")["complete"])
        result = workflow.assemble_units(job, "review")
        self.assertEqual((result["state"], result["round"]), ("translated", 1))
        report = core.load_json(job / "reviews/round-1.json")
        self.assertEqual(report["findings"], [new_finding, carried_finding])
        self.assertEqual(report["verdict"], "changes_requested")
        self.assertEqual(report["checks"], {name: name not in {"coverage", "typography"} for name in workflow.REVIEW_CHECKS})
        self.assertEqual({key: report[key] for key in ("content_digest", "pdf_sha256")},
                         {key: before_build[key] for key in ("content_digest", "pdf_sha256")})
        outputs[selected["unit_id"]] = corrected
        for output in outputs.values():
            for evidence in output["evidence"]:
                self.assertIn(evidence, report["evidence"])
        aggregate = core.load_json(result["receipt"])
        expected_members = [{"path": spec["checkpoint"], "sha256": workflow.digest_file(job / spec["checkpoint"])}
                            for spec in successor["units"]]
        self.assertEqual(aggregate["unit_checkpoints"], expected_members)
        self.assertNotIn(prior_checkpoint, aggregate["unit_checkpoints"])
        self.assertIn(carried["carried_checkpoint"], aggregate["unit_checkpoints"])
        self.assertEqual(core.load_json(job / carried["checkpoint"])["task"], old_checkpoints[unaffected["unit_id"]]["task"])
        self.assertEqual(core.load_json(job / carried["checkpoint"])["plan"], previous["plan"])
        self.assertEqual(core.load_json(job / replacement["checkpoint"])["plan"], reference["plan"])
        units.validate_aggregate(job, aggregate, "review")
        self.assertEqual(workflow.latest_role_receipt(job, workflow.load_job(job), "review"), aggregate)
        self.assertEqual(workflow.submit_review(job, job / "reviews/round-1.json"), {"state": "changes_requested", "round": 1})
        self.assertFalse((job / "output.pdf").exists())
        pending_results = {job / spec["result"] for spec in pending}
        for path, content in frozen.items():
            if path != job / "job.json" and path not in pending_results:
                self.assertEqual(path.read_bytes(), content, str(path))

    def test_review_reopen_carried_checkpoint_keeps_nested_pending_bindings_and_native_origins(self):
        job = self.translated_job(pdf_pages=20)
        original = self.plan(job, "review")
        first, second, unaffected, pending = original["units"]
        for spec in (first, second, unaffected):
            prepared, _, _, output = self.prepare(job, "review", spec["unit_id"])
            self.finish(job, prepared, output)
        active = job / "units/review/active.json"
        frozen = {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file() and path != active}
        first_reference = units.create_plan(job, "review", pages_per_unit=original["pages_per_unit"],
            readiness=original["readiness"], reopen_units=[first["unit_id"]])
        first_plan = core.load_json(job / first_reference["plan"])
        _, old_binding, _, draft = self.prepare(job, "review", first["unit_id"])
        draft["evidence"] = ["Unadmitted successor draft retained across a second reopening."]
        core.save_json(job / old_binding["result"], draft)
        draft_bytes = (job / old_binding["result"]).read_bytes()
        first_plan_bytes = (job / first_reference["plan"]).read_bytes()
        second_reference = workflow.plan_units(job, "review", original["pages_per_unit"], reopen_units=[second["unit_id"]])
        successor = core.load_json(job / second_reference["plan"])
        self.assertEqual(successor["review_reopen"]["plan"], first_reference["plan"])
        self.assertEqual(successor["review_reopen"]["prior_checkpoints"][second["unit_id"]], first_plan["units"][1]["carried_checkpoint"])
        self.assertEqual(successor["units"][0], first_plan["units"][0])
        self.assertEqual(successor["units"][2:], first_plan["units"][2:])
        self.assertEqual((job / old_binding["result"]).read_bytes(), draft_bytes)
        self.assertEqual((job / first_reference["plan"]).read_bytes(), first_plan_bytes)
        self.assertEqual(units.status(job, "review")["admitted"], [unaffected["unit_id"]])
        self.assertEqual(units.status(job, "review")["pending"], [first["unit_id"], second["unit_id"], pending["unit_id"]])
        expected_findings = []
        for spec in successor["units"]:
            if spec["unit_id"] == unaffected["unit_id"]:
                continue
            prepared, _, _, output = self.prepare(job, "review", spec["unit_id"])
            if spec["unit_id"] in {first["unit_id"], second["unit_id"]}:
                finding = {"id": spec["unit_id"] + "_NewFinding", "severity": "major", "location": spec["unit_id"],
                           "detail": "Newly completed review after explicit immutable-history reopening."}
                output.update(findings=[finding], verdict="changes_requested")
                expected_findings.append(finding)
            self.finish(job, prepared, output)
        result = workflow.assemble_units(job, "review")
        aggregate = core.load_json(result["receipt"])
        self.assertEqual(core.load_json(job / "reviews/round-1.json")["findings"], expected_findings)
        self.assertIn(successor["units"][2]["carried_checkpoint"], aggregate["unit_checkpoints"])
        self.assertNotIn(first["checkpoint"], [member["path"] for member in aggregate["unit_checkpoints"]])
        self.assertNotIn(second["checkpoint"], [member["path"] for member in aggregate["unit_checkpoints"]])
        units.validate_aggregate(job, aggregate, "review")
        for path, content in frozen.items():
            if path != job / "job.json":
                self.assertEqual(path.read_bytes(), content, str(path))

    def test_review_reopen_refuses_invalid_selection_flags_and_changed_frozen_inputs_without_writes(self):
        job = self.translated_job(pdf_pages=20)
        plan = self.plan(job, "review")
        selected, unaffected, *pending = plan["units"]
        for spec in (selected, unaffected):
            prepared, _, _, output = self.prepare(job, "review", spec["unit_id"])
            self.finish(job, prepared, output)
        snapshot = lambda: {path: path.read_bytes() if path.is_file() else None for path in self.root.rglob("*")}

        def reject(selectors, size=1, **options):
            before = snapshot()
            with self.assertRaises(ValueError):
                workflow.plan_units(job, "review", size, reopen_units=selectors, **options)
            self.assertEqual(snapshot(), before)
            domain_options = {"draft_path" if key == "draft" else key: value for key, value in options.items()}
            with self.assertRaises(ValueError):
                units.create_plan(job, "review", pages_per_unit=size, readiness=plan["readiness"],
                                  reopen_units=selectors, **domain_options)
            self.assertEqual(snapshot(), before)

        for selectors in ([], [""], [" "], [None], [1], selected["unit_id"], ["u9999"],
                          [pending[0]["unit_id"]], [selected["unit_id"], pending[0]["unit_id"]], [selected["unit_id"]] * 2):
            with self.subTest(selectors=selectors):
                reject(selectors)
        for size, options in ((2, {}), (True, {}), (1, {"replan_pending": True}), (1, {"revise": True}),
                              (1, {"draft": job / "book.json"}),
                              (1, {"rebase_source": job / "book-source.json", "accept_policy_compatibility": "0" * 64})):
            with self.subTest(size=size, options=options):
                reject([selected["unit_id"]], size, **options)
        for field in ("source_digest", "source_seal_sha256", "content_digest", "pdf_sha256", "verification_sha256"):
            readiness = copy.deepcopy(plan["readiness"])
            if field == "source_digest":
                readiness[field] = "0" * 64
            elif field == "source_seal_sha256":
                readiness["bindings"][field] = "0" * 64
            else:
                readiness["bindings"]["build"][field] = "0" * 64
            before = snapshot()
            with self.subTest(readiness=field), self.assertRaises(ValueError):
                units.create_plan(job, "review", pages_per_unit=plan["pages_per_unit"], readiness=readiness,
                                  reopen_units=[selected["unit_id"]])
            self.assertEqual(snapshot(), before)
        active = job / "units/review/active.json"
        pointer_bytes = active.read_bytes()
        plan_path = core.load_json(active)["plan"]
        active.unlink()
        try:
            reject([selected["unit_id"]])
        finally:
            active.write_bytes(pointer_bytes)
        packet = core.load_json(job / selected["packet"])
        changed_files = ["job.json", workflow.load_job(job)["source_file"], "book-source.json", "source.sha256", "book.json",
                         "terms.json", "handoff.md", "extraction.json", "build/book.pdf", "build/verification.json", plan_path,
                         selected["packet"], selected["result"], unaffected["packet"], unaffected["result"], pending[0]["packet"],
                         packet["pages"][0]["evidence"], packet["pages"][0]["image"]]
        for name in changed_files:
            path = job / name
            content = path.read_bytes()
            try:
                path.write_bytes(content + b"\n ")
                with self.subTest(changed=name):
                    reject([selected["unit_id"]])
            finally:
                path.write_bytes(content)
        job_path = job / "job.json"
        job_bytes = job_path.read_bytes()
        metadata = json.loads(job_bytes)
        mutations = [{"state": state} for state in ("initialized", "extracted", "source_ready", "terminology_ready",
                                                      "changes_requested", "approved", "exhausted")]
        mutations += [{"round": round_number} for round_number in (0, 2, metadata["max_rounds"])]
        mutations += [{"models": {**metadata["models"], "review": {"provider": "openai-codex", "model": "gpt-6-luna"}}}]
        for changes in mutations:
            try:
                core.save_json(job_path, {**metadata, **changes})
                with self.subTest(job_changes=changes):
                    reject([selected["unit_id"]])
            finally:
                job_path.write_bytes(job_bytes)
        for name, changes in ((selected["checkpoint"], {"completed": False}),
                              (unaffected["checkpoint"], {"completed": False}),
                              ("build/verification.json", {"passed": False}),
                              ("build/verification.json", {"content_digest": "0" * 64}),
                              ("build/verification.json", {"pdf_sha256": "0" * 64})):
            path = job / name
            content = path.read_bytes()
            try:
                core.save_json(path, {**json.loads(content), **changes})
                with self.subTest(artifact=name, changes=changes):
                    reject([selected["unit_id"]])
            finally:
                path.write_bytes(content)
        book_path = job / "book.json"
        book_bytes = book_path.read_bytes()
        try:
            book = json.loads(book_bytes)
            next(token for token in book["blocks"][0]["target"] if "text" in token)["text"] += " Changed reviewed content."
            core.save_json(book_path, book)
            reject([selected["unit_id"]])
        finally:
            book_path.write_bytes(book_bytes)
        for suffix in ("json", "receipt.json"):
            artifact = job / f"reviews/round-1.{suffix}"
            core.save_json(artifact, {"unauthorized": "Unadmitted canonical review artifact"})
            try:
                with self.subTest(canonical_artifact=suffix):
                    reject([selected["unit_id"]])
            finally:
                artifact.unlink()

    def test_review_reopen_refuses_complete_aggregate_and_submission_without_writes(self):
        for phase in ("content_aggregate", "aggregate", "submitted"):
            with self.subTest(phase=phase):
                job = self.translated_job(pdf_pages=20)
                plan = self.plan(job, "review")
                for spec in plan["units"]:
                    prepared, _, _, output = self.prepare(job, "review", spec["unit_id"])
                    self.finish(job, prepared, output)
                if phase == "content_aggregate":
                    units.assemble_units(job, "review")
                else:
                    workflow.assemble_units(job, "review")
                    if phase == "submitted":
                        self.assertEqual(workflow.submit_review(job, job / "reviews/round-1.json")["state"], "approved")
                before = {path: path.read_bytes() if path.is_file() else None for path in self.root.rglob("*")}
                with self.assertRaises(ValueError):
                    workflow.plan_units(job, "review", plan["pages_per_unit"], reopen_units=[plan["units"][0]["unit_id"]])
                self.assertEqual({path: path.read_bytes() if path.is_file() else None for path in self.root.rglob("*")}, before)
                with self.assertRaises(ValueError):
                    units.create_plan(job, "review", pages_per_unit=plan["pages_per_unit"], readiness=plan["readiness"],
                                      reopen_units=[plan["units"][0]["unit_id"]])
                self.assertEqual({path: path.read_bytes() if path.is_file() else None for path in self.root.rglob("*")}, before)


    def test_review_overflow_preserves_exact_pdf_union_and_all_findings(self):
        job = self.translated_job(pdf_pages=20)
        plan = self.plan(job, "review")
        with pymupdf.open(job / "build/book.pdf") as document:
            self.assertEqual(document.page_count, 20)
        owned = [page for spec in plan["units"] for page in spec["pdf_pages"]]
        self.assertEqual(Counter(owned), Counter(range(1, 21)))
        self.assertEqual([len(spec["pdf_pages"]) for spec in plan["units"] if spec["pdf_pages"]], [8, 8, 4])
        source_pages = [page for spec in plan["units"] for page in spec["owned_pages"]]
        self.assertEqual(set(source_pages), set(plan["page_ids"]))
        self.assertGreater(len(source_pages), len(set(source_pages)))
        expected_findings = []
        for index, spec in enumerate(plan["units"]):
            prepared, _, packet, output = self.prepare(job, "review", spec["unit_id"])
            self.assertLessEqual(len(packet["owned_pages"]), 8)
            self.assertLessEqual(len(packet["pdf_pages"]), 8)
            self.assertLessEqual(len(packet["context_pdf_pages"]), 2)
            if index == 0:
                incomplete = copy.deepcopy(output)
                incomplete["pdf_inspection"].pop()
                with self.assertRaisesRegex(ValueError, "every owned physical PDF page"):
                    self.finish(job, prepared, incomplete)
            if index in (1, len(plan["units"]) - 1):
                finding = {"id": spec["unit_id"] + "_Finding", "severity": "major",
                           "location": "Synthetic owned review scope", "detail": "Retain this synthetic finding."}
                output["findings"] = [finding]
                output["verdict"] = "changes_requested"
                expected_findings.append(finding)
            if index == 1:
                output["checks"]["typography"] = False
            if index == len(plan["units"]) - 1:
                with self.assertRaisesRegex(ValueError, "Every planned unit"):
                    workflow.assemble_units(job, "review")
                self.assertFalse((job / "reviews/round-1.json").exists())
            self.finish(job, prepared, output)
        workflow.assemble_units(job, "review")
        report = core.load_json(job / "reviews/round-1.json")
        self.assertEqual(report["verdict"], "changes_requested")
        self.assertFalse(report["checks"]["typography"])
        self.assertTrue(all(value for key, value in report["checks"].items() if key != "typography"))
        self.assertEqual(report["findings"], expected_findings)
        self.assertEqual(workflow.submit_review(job, job / "reviews/round-1.json")["state"], "changes_requested")
        self.assertFalse((job / "output.pdf").exists())
    
    def test_explicit_legacy_completed_subset_import_preserves_bytes_and_origin(self):
        # Two completed units and two failed output-only siblings model the historical 17/19 subset.
        job = self.new_job(page_count=4)
        plan = self.plan(job)
        active = core.load_json(job / "units/source/active.json")
        plan_path = job / active["plan"]
        legacy = copy.deepcopy(plan)
        legacy["kind"] = "native-unit-plan"
        for spec in legacy["units"]:
            spec["receipt"] = spec.pop("checkpoint").replace("/checkpoints/", "/receipts/")
            packet_path = job / spec["packet"]
            packet = core.load_json(packet_path)
            packet["kind"] = "native-unit-packet"
            core.save_json(packet_path, packet)
            spec["packet_sha256"] = workflow.digest_file(packet_path)
            core.save_json(job / spec["result"], unit_output(packet, spec))
        core.save_json(plan_path, legacy)
        legacy_digest = workflow.digest_file(plan_path)
        core.save_json(job / "units/source/active.json", {"plan": active["plan"], "plan_sha256": legacy_digest})
        evidence = plan_path.parent / "historical-events.jsonl"
        evidence.write_text('{"type":"historical_fixture_only"}\n', encoding="utf-8")
        for spec in legacy["units"][:2]:
            receipt = {"version": 1, "kind": "native-unit-completed", "completed": True,
                       "role": "source", "stage": "source", "selector": PROVIDER + "/" + MODEL,
                       "plan": active["plan"], "plan_sha256": legacy_digest,
                       **{key: spec[key] for key in ("unit_id", "packet", "packet_sha256", "result")},
                       "result_sha256": workflow.digest_file(job / spec["result"]), "assets": {},
                       **legacy["selected_model"],
                       **{key: legacy[key] for key in ("source_file_sha256", "source_digest", "base_state", "base_round", "revision")},
                       "trace": evidence.relative_to(job).as_posix(), "trace_sha256": workflow.digest_file(evidence)}
            core.save_json(job / spec["receipt"], receipt)
        old_bytes = {path.relative_to(job).as_posix(): path.read_bytes() for path in job.rglob("*") if path.is_file()}
        with self.assertRaises(ValueError):
            units.status(job, "source")
        capture = io.StringIO()
        with patch("sys.stdout", capture):
            self.assertEqual(workflow.main(["import-checkpoints", str(job), "source", "--plan", str(plan_path)]), 0)
        imported = core.load_json(job / "units/source/active.json")
        domain = core.load_json(job / imported["plan"])
        progress = units.status(job, "source")
        self.assertEqual(progress["admitted"], ["u0001", "u0002"])
        self.assertEqual(progress["pending"], ["u0003", "u0004"])
        self.assertEqual(domain["historical_plan"], {"path": active["plan"], "sha256": legacy_digest})
        self.assertEqual(json.loads(capture.getvalue())["imported"], ["u0001", "u0002"])
        for spec in domain["units"][:2]:
            checkpoint = core.load_json(job / spec["checkpoint"])
            origin = next(item["receipt"] for item in legacy["units"] if item["unit_id"] == spec["unit_id"])
            self.assertEqual(checkpoint["historical_origin"], {"path": origin, "sha256": workflow.digest_file(job / origin)})
            self.assertNotIn("task", checkpoint)
        for spec in domain["units"][2:]:
            self.assertTrue((job / spec["result"]).is_file())
            self.assertFalse((job / spec["checkpoint"]).exists())
        for name, content in old_bytes.items():
            if name != "units/source/active.json":
                self.assertEqual((job / name).read_bytes(), content, name)
        with self.assertRaisesRegex(ValueError, "Every planned unit"):
            workflow.assemble_units(job, "source")
        self.assertFalse((job / "book-source.json").exists())
        for spec in domain["units"][2:]:
            prepared, _, _, output = self.prepare(job, "source", spec["unit_id"])
            self.finish(job, prepared, output)
        workflow.assemble_units(job, "source")
        self.assertEqual(len(core.load_json(job / "book-source.json")["source_pages"]), 4)
        origin_path = job / legacy["units"][0]["receipt"]
        original = origin_path.read_bytes()
        origin_path.write_bytes(original + b"\n")
        with self.assertRaises(ValueError):
            workflow.seal_job(job)
        origin_path.write_bytes(original)
        workflow.seal_job(job)
    
    
    def test_source_page_counter_and_partial_translation_merge(self):
        job = self.new_job()
        self.plan(job, pages_per_unit=2)
        prepared, _, _, output = self.prepare(job, "source", "u0001")
        incomplete = copy.deepcopy(output)
        incomplete["source_pages"].pop()
        with self.assertRaisesRegex(ValueError, "exactly its owned original page records"):
            self.finish(job, prepared, incomplete)
        self.finish(job, prepared, output)
        workflow.assemble_units(job, "source")
        workflow.seal_job(job)
        self.admit_terminology(job)
        plan = self.plan(job, "translation")
        before = (job / "job.json").read_bytes()
        first, second = plan["units"]
        prepared, _, _, output = self.prepare(job, "translation", second["unit_id"])
        changed = copy.deepcopy(output)
        changed["blocks"][0]["target"] = [{"text": "Dropped original source-page token."}]
        with self.assertRaisesRegex(ValueError, "token order or multiplicity"):
            self.finish(job, prepared, changed)
        self.finish(job, prepared, output)
        with self.assertRaisesRegex(ValueError, "Every planned unit"):
            workflow.assemble_units(job, "translation")
        self.assertFalse((job / "book.json").exists())
        self.assertEqual((job / "job.json").read_bytes(), before)
        prepared, _, _, output = self.prepare(job, "translation", first["unit_id"])
        self.finish(job, prepared, output)
        with patch("render.build", side_effect=synthetic_build):
            result = workflow.assemble_units(job, "translation")
        self.assertEqual((result["state"], result["round"]), ("translated", 1))
        book = core.load_json(job / "book.json")
        source = core.load_json(job / "book-source.json")
        self.assertEqual([item["id"] for item in book["blocks"]], [item["id"] for item in source["blocks"]])
        self.assertTrue(all(item["target"] for item in book["blocks"]))
    
    
    def test_caption_before_graphic_page_token_rejects_complete_translation_before_publication(self):
        for relation in (None, "column"):
            with self.subTest(kind="image" if relation is None else "group"):
                job, plan = self.graphic_translation_job(relation)
                for spec in plan["units"]:
                    prepared, _, packet, output = self.prepare(job, "translation", spec["unit_id"])
                    for block in output["blocks"]:
                        if block["id"] == "InlineBody":
                            original = next(item for item in packet["blocks"] if item["id"] == block["id"])
                            self.assertEqual(block["target"][0], original["source"][0])
                            self.assertIn("page", block["target"][0])
                            self.assertIn("text", block["target"][1])
                            block["target"][0], block["target"][1] = block["target"][1], block["target"][0]
                    self.finish(job, prepared, output)
                progress = units.status(job, "translation")
                self.assertTrue(progress["complete"])
                self.assertEqual(progress["admitted"], [spec["unit_id"] for spec in plan["units"]])
                self.assertFalse((job / "book.json").exists())
                before = {path.relative_to(job).as_posix(): path.read_bytes()
                          for path in job.rglob("*") if path.is_file()}
                with patch("render.build", side_effect=synthetic_build), self.assertRaisesRegex(
                        ValueError, "Graphic block InlineBody has inconsistent leading source/target page tokens"):
                    workflow.assemble_units(job, "translation")
                self.assertEqual({path.relative_to(job).as_posix(): path.read_bytes()
                                  for path in job.rglob("*") if path.is_file()}, before)
                self.assertFalse((job / "book.json").exists())
                self.assertFalse(any(event["event"] in {"translation_content_authored", "stage_translation"}
                                     for event in workflow.load_job(job)["history"]))

    def test_exact_graphic_page_prefix_preserves_complete_translation_and_member_origins(self):
        for relation in (None, "column"):
            with self.subTest(kind="image" if relation is None else "group"):
                job, plan = self.graphic_translation_job(relation)
                source_bytes = (job / "book-source.json").read_bytes()
                source = json.loads(source_bytes)
                expected = copy.deepcopy(source)
                for spec in plan["units"]:
                    prepared, _, _, output = self.prepare(job, "translation", spec["unit_id"])
                    for category in ("blocks", "notes"):
                        for item in output[category]:
                            next(original for original in expected[category] if original["id"] == item["id"]).update(item)
                    expected.update(output.get("metadata", {}))
                    self.finish(job, prepared, output)
                members = [{"path": spec["checkpoint"], "sha256": workflow.digest_file(job / spec["checkpoint"])}
                           for spec in plan["units"]]
                evidence = {name: (job / name).read_bytes() for spec in plan["units"]
                            for name in (spec["packet"], spec["result"], spec["checkpoint"])}
                with patch("render.build", side_effect=synthetic_build):
                    result = workflow.assemble_units(job, "translation")
                self.assertEqual((result["state"], result["round"]), ("translated", 1))
                book = core.validate_book(job, translated=True)
                self.assertEqual(book, expected)
                graphic = next(block for block in book["blocks"] if block["id"] == "InlineBody")
                self.assertEqual(graphic["target"][0], graphic["source"][0])
                self.assertEqual([token for token in graphic["target"] if "page" in token],
                                 [token for token in graphic["source"] if "page" in token])
                current = workflow.load_job(job)
                authored = [event for event in current["history"] if event["event"] == "translation_content_authored"]
                self.assertEqual(len(authored), 1)
                aggregate = core.load_json(job / authored[0]["receipt"])
                self.assertEqual(aggregate["unit_checkpoints"], members)
                self.assertEqual(aggregate["merged_document"], "book.json")
                self.assertEqual(aggregate["merged_document_sha256"], workflow.digest_file(job / "book.json"))
                self.assertEqual(aggregate["content_digest"], core.content_digest(job))
                units.validate_aggregate(job, aggregate, "translation")
                workflow.translation_ready(job, current)
                self.assertEqual((job / "book-source.json").read_bytes(), source_bytes)
                for name, content in evidence.items():
                    self.assertEqual((job / name).read_bytes(), content, name)


    def test_duplicate_source_page_union_cannot_merge(self):
        job = self.new_job()
        plan = self.plan(job)
        active = core.load_json(job / "units/source/active.json")
        plan["units"][1]["owned_pages"] = plan["units"][0]["owned_pages"]
        core.save_json(job / active["plan"], plan)
        active["plan_sha256"] = workflow.digest_file(job / active["plan"])
        core.save_json(job / "units/source/active.json", active)
        with self.assertRaisesRegex(ValueError, "exact original source page union"):
            units.assemble_units(job, "source")
        self.assertFalse((job / "book-source.json").exists())
    
    def test_source_continuation_preserves_completed_origin_and_reissues_pending_work(self):
        job = self.new_job()
        plan = self.plan(job)
        completed, pending = plan["units"]
        prepared, _, _, output = self.prepare(job, "source", completed["unit_id"])
        self.finish(job, prepared, output)
        _, binding, packet, draft = self.prepare(job, "source", pending["unit_id"])
        core.save_json(job / binding["result"], draft)
        fallback_task = domain_fixtures.save_task_result(self.root / "coordinator-results", "source", PROVIDER, MODEL)
        fallback = core.load_json(fallback_task)
        fallback["resolvedModelIsFallback"] = True
        core.save_json(fallback_task, fallback)
        with self.assertRaises(ValueError):
            workflow.checkpoint_unit(job, "source", pending["unit_id"], fallback_task)
        self.assertFalse((job / pending["checkpoint"]).exists())
        original_job = workflow.load_job(job)
        original_job_bytes = (job / "job.json").read_bytes()
        active_path = job / "units/source/active.json"
        original_active = active_path.read_bytes()
        preserved = {name: (job / name).read_bytes() for spec in plan["units"]
                     for name in (spec["packet"], spec["result"])}
        preserved[completed["checkpoint"]] = (job / completed["checkpoint"]).read_bytes()
        next_model = {"provider": "openai-codex", "model": "gpt-6-luna"}
    
        for artifact in (job / "job.json", job / original_job["source_file"]):
            original = artifact.read_bytes()
            try:
                if artifact.name == "job.json":
                    metadata = core.load_json(artifact)
                    metadata["title"] = "Changed source-plan context"
                    core.save_json(artifact, metadata)
                else:
                    artifact.write_bytes(original + b"\nchanged original source")
                before = {path.relative_to(job).as_posix(): path.read_bytes()
                          for path in job.rglob("*") if path.is_file()}
                with self.subTest(artifact=artifact.name), self.assertRaises(ValueError):
                    workflow.continue_source(job, **next_model)
                self.assertEqual({path.relative_to(job).as_posix(): path.read_bytes()
                                  for path in job.rglob("*") if path.is_file()}, before)
            finally:
                artifact.write_bytes(original)
        transition = workflow.continue_source(job, **next_model)
        self.assertEqual(transition["carried"], [completed["unit_id"]])
        self.assertEqual(transition["selector"], "openai-codex/gpt-6-luna")
        self.assertEqual(transition["models"], {role: next_model for role in workflow.ROLES})
        self.assertEqual((job / transition["previous_job"]["path"]).read_bytes(), original_job_bytes)
        self.assertEqual(workflow.digest_file(job / transition["previous_job"]["path"]), transition["previous_job"]["sha256"])
        self.assertEqual((job / transition["job_snapshot"]["path"]).read_bytes(), (job / "job.json").read_bytes())
        self.assertEqual(workflow.digest_file(job / transition["job_snapshot"]["path"]), transition["job_snapshot"]["sha256"])
        current = workflow.load_job(job)
        self.assertTrue(all(selection == next_model for selection in current["models"].values()))
        self.assertEqual((current["state"], current["round"], current["max_rounds"]),
                         (original_job["state"], original_job["round"], original_job["max_rounds"]))
        self.assertNotEqual(active_path.read_bytes(), original_active)
        reference = core.load_json(active_path)
        continued = core.load_json(job / reference["plan"])
        self.assertEqual(continued["units"][0]["carried_checkpoint"], {"path": completed["checkpoint"], "sha256": workflow.digest_file(job / completed["checkpoint"])})
        progress = units.status(job, "source")
        self.assertEqual(progress["admitted"], [completed["unit_id"]])
        self.assertEqual(progress["pending"], [pending["unit_id"]])
        for previous, replacement in zip(plan["units"], continued["units"]):
            for key in ("unit_id", "packet", "packet_sha256", "owned_pages", "owned_block_ids", "owned_note_ids", "owned_protected_ids"):
                self.assertEqual(replacement[key], previous[key], key)
        replacement = continued["units"][1]
        for key in ("result", "assets_dir", "checkpoint"):
            self.assertNotEqual(replacement[key], pending[key], key)
            self.assertFalse((job / replacement[key]).exists())
        for name, content in preserved.items():
            self.assertEqual((job / name).read_bytes(), content, name)
        binding = units.unit_binding(job, "source", pending["unit_id"])
        packet = core.load_json(job / binding["packet"])
        core.save_json(job / binding["result"], unit_output(packet, binding))
        stale_task = domain_fixtures.save_task_result(self.root / "coordinator-results", "source", PROVIDER, MODEL)
        with self.assertRaises(ValueError):
            workflow.checkpoint_unit(job, "source", pending["unit_id"], stale_task)
        self.assertFalse((job / replacement["checkpoint"]).exists())
        task = domain_fixtures.save_task_result(self.root / "coordinator-results", "source", **next_model)
        workflow.checkpoint_unit(job, "source", pending["unit_id"], task)
        workflow.assemble_units(job, "source")
        aggregate = workflow.latest_role_receipt(job, workflow.load_job(job), "source")
        self.assertIn({"path": completed["checkpoint"], "sha256": workflow.digest_file(job / completed["checkpoint"])}, aggregate["unit_checkpoints"])
        members = [core.load_json(job / member["path"]) for member in aggregate["unit_checkpoints"]]
        self.assertEqual([member["task"]["resolvedModelIdentity"] for member in members],
                         [PROVIDER + "/" + MODEL, next_model["provider"] + "/" + next_model["model"]])
        self.assertEqual((job / completed["checkpoint"]).read_bytes(), preserved[completed["checkpoint"]])
        workflow.seal_job(job)
        self.assertEqual((workflow.load_job(job)["state"], workflow.load_job(job)["round"]), ("source_ready", 0))
        self.assertEqual(len(core.load_json(job / "book-source.json")["source_pages"]), 2)

    def test_reopen_carried_source_unit_preserves_history_and_current_model_guards(self):
        job = self.new_job(page_count=3)
        original_plan = self.plan(job)
        original_reference = core.load_json(job / "units/source/active.json")
        first_id, second_id, pending_id = [spec["unit_id"] for spec in original_plan["units"]]
        prepared, _, _, output = self.prepare(job, "source", first_id)
        self.finish(job, prepared, output)
        old_go = original_plan["units"][0]
        luna = {"provider": "openai-codex", "model": "gpt-6-luna"}
        transition = workflow.continue_source(job, **luna)
        current_plan = core.load_json(job / transition["plan"])
        binding = units.unit_binding(job, "source", second_id)
        core.save_json(job / binding["result"], unit_output(core.load_json(job / binding["packet"]), binding))
        task = domain_fixtures.save_task_result(self.root / "coordinator-results", "source", **luna)
        workflow.checkpoint_unit(job, "source", second_id, task)
        preserved = {name: (job / name).read_bytes() for name in (
            original_reference["plan"], transition["plan"], old_go["packet"], old_go["result"], old_go["checkpoint"],
            current_plan["units"][1]["result"], current_plan["units"][1]["checkpoint"])}
        self.assertEqual(core.load_json(job / old_go["checkpoint"])["task"]["resolvedModelIdentity"], PROVIDER + "/" + MODEL)
        for rejected in (["unknown"], [pending_id], [first_id, first_id]):
            before = {path.relative_to(job).as_posix(): path.read_bytes() for path in job.rglob("*") if path.is_file()}
            with self.subTest(reopen=rejected), self.assertRaises(ValueError):
                workflow.continue_source(job, **luna, reopen_units=rejected)
            self.assertEqual({path.relative_to(job).as_posix(): path.read_bytes() for path in job.rglob("*") if path.is_file()}, before)
        original_job = (job / "job.json").read_bytes()
        data = workflow.load_job(job)
        data["state"] = "source_ready"
        core.save_json(job / "job.json", data)
        before = {path.relative_to(job).as_posix(): path.read_bytes() for path in job.rglob("*") if path.is_file()}
        with self.assertRaises(ValueError):
            workflow.continue_source(job, **luna, reopen_units=[first_id])
        self.assertEqual({path.relative_to(job).as_posix(): path.read_bytes() for path in job.rglob("*") if path.is_file()}, before)
        (job / "job.json").write_bytes(original_job)
        (job / "source.sha256").write_text("0" * 64 + "\n", encoding="ascii")
        before = {path.relative_to(job).as_posix(): path.read_bytes() for path in job.rglob("*") if path.is_file()}
        with self.assertRaises(ValueError):
            workflow.continue_source(job, **luna, reopen_units=[first_id])
        self.assertEqual({path.relative_to(job).as_posix(): path.read_bytes() for path in job.rglob("*") if path.is_file()}, before)
        (job / "source.sha256").unlink()
        with patch("sys.stdout", new_callable=io.StringIO) as captured:
            self.assertEqual(workflow.main(["continue-source", str(job), "--provider", luna["provider"],
                                            "--model", luna["model"], "--reopen", first_id]), 0)
            correction = json.loads(captured.getvalue())
        self.assertEqual(correction["reopened"], [first_id])
        self.assertEqual(correction["carried"], [second_id])
        self.assertEqual(correction["pending"], [first_id, pending_id])
        corrected_plan = core.load_json(job / correction["plan"])
        self.assertEqual(corrected_plan["selected_model"], luna)
        self.assertEqual(corrected_plan["continuation"]["reopened"], [first_id])
        self.assertEqual(corrected_plan["units"][1]["checkpoint"], current_plan["units"][1]["checkpoint"])
        for old, new in zip(current_plan["units"], corrected_plan["units"]):
            for key in ("packet", "packet_sha256", "owned_pages", "owned_block_ids", "owned_note_ids", "owned_protected_ids"):
                self.assertEqual(new[key], old[key])
            if old["unit_id"] != second_id:
                self.assertNotIn("carried_checkpoint", new)
                for key in ("result", "assets_dir", "checkpoint"):
                    self.assertNotEqual(new[key], old[key])
                    self.assertFalse((job / new[key]).exists())
        current = workflow.load_job(job)
        self.assertEqual((current["state"], current["round"], current["max_rounds"]), ("extracted", 0, 3))
        self.assertTrue(all(selected == luna for selected in current["models"].values()))
        for unit_id in correction["pending"]:
            binding = units.unit_binding(job, "source", unit_id)
            output = unit_output(core.load_json(job / binding["packet"]), binding)
            if unit_id == first_id:
                output["blocks"][0]["source"].append({"text": " Corrected synthetic chapter heading."})
            core.save_json(job / binding["result"], output)
            task = domain_fixtures.save_task_result(self.root / "coordinator-results", "source", **luna)
            workflow.checkpoint_unit(job, "source", unit_id, task)
        workflow.assemble_units(job, "source")
        aggregate = workflow.latest_role_receipt(job, workflow.load_job(job), "source")
        self.assertIn({"path": current_plan["units"][1]["checkpoint"],
                       "sha256": workflow.digest_file(job / current_plan["units"][1]["checkpoint"])}, aggregate["unit_checkpoints"])
        self.assertNotIn(old_go["checkpoint"], [member["path"] for member in aggregate["unit_checkpoints"]])
        for name, content in preserved.items():
            self.assertEqual((job / name).read_bytes(), content, name)
        workflow.seal_job(job)
        self.assertEqual((workflow.load_job(job)["state"], workflow.load_job(job)["round"]), ("source_ready", 0))
        before = {path.relative_to(job).as_posix(): path.read_bytes() for path in job.rglob("*") if path.is_file()}
        with self.assertRaises(ValueError):
            workflow.continue_source(job, **luna, reopen_units=[first_id])
        self.assertEqual({path.relative_to(job).as_posix(): path.read_bytes() for path in job.rglob("*") if path.is_file()}, before)


    def test_source_assembly_exports_live_imports_but_preserves_authored_orphans(self):
        for mode in ("imports", "new", "modified", "target_reference"):
            with self.subTest(mode=mode):
                job = self.new_job()
                first, second = [page["id"] for page in core.extraction_inventory(job)["pages"]]
                draft = {"title": "Synthetic protected imports", "main_body_start": "first", "source_pages": [],
                    "blocks": [
                        {"id": "first", "kind": "paragraph", "source_pages": [first],
                         "source": [{"page": first}, {"protected": "OldVar"}, {"text": " + "},
                                    {"protected": "OwnedOld"}, {"text": "; "}, {"protected": "KeepName"}], "target": []},
                        {"id": "equation", "kind": "display_math", "source_pages": [first],
                         "protected_id": "KeepMath", "source": [], "target": []},
                        {"id": "second", "kind": "paragraph", "source_pages": [second],
                         "source": [{"page": second}, {"protected": "OldVar"}, {"text": " + 1; "},
                                    {"protected": "KeepName"}], "target": []}],
                    "notes": [], "protected": [
                        {"id": "OldVar", "kind": "variable", "value": "x"},
                        {"id": "OwnedOld", "kind": "variable", "value": "1"},
                        {"id": "KeepName", "kind": "name", "value": "Literal Name"},
                        {"id": "KeepMath", "kind": "math", "value": "z^2"}]}
                core.save_json(job / "draft.json", draft)
                plan = self.plan(job, draft=job / "draft.json")
                expected_blocks, expected_protected = [], {item["id"]: item for item in draft["protected"] if item["id"].startswith("Keep")}
                for index, spec in enumerate(plan["units"]):
                    prepared, _, packet, output = self.prepare(job, "source", spec["unit_id"])
                    self.assertIn("OldVar", packet["shared_protected_ids"])
                    formula = {"id": spec["unit_id"] + "_whole", "kind": "math", "value": "x+1"}
                    output["protected"].append(formula)
                    output["blocks"][0]["source"] = [
                        {"page": spec["owned_pages"][0]}, {"protected": formula["id"]},
                        {"text": "; "}, {"protected": "KeepName"}]
                    expected_protected[formula["id"]] = formula
                    if index == 0:
                        if mode == "new":
                            output["protected"].append({"id": spec["unit_id"] + "_missing", "kind": "variable", "value": "n"})
                            output["blocks"][0]["source"].append({"text": " A synthetic missing formula call remains unresolved."})
                        elif mode == "modified":
                            next(item for item in output["protected"] if item["id"] == "OwnedOld")["value"] = "2"
                        elif mode == "target_reference":
                            output["blocks"][0]["target"] = [{"protected": "OwnedOld"}]
                    expected_blocks.extend(copy.deepcopy(output["blocks"]))
                    self.finish(job, prepared, output)
                preserved = {name: (job / name).read_bytes() for spec in plan["units"]
                             for name in (spec["packet"], spec["result"], spec["checkpoint"])}
                before = (job / "job.json").read_bytes()
                if mode != "imports":
                    with self.assertRaisesRegex(ValueError, "Protected values must all be used"):
                        workflow.assemble_units(job, "source")
                    self.assertEqual((job / "job.json").read_bytes(), before)
                    self.assertFalse((job / "book-source.json").exists())
                    self.assertFalse((job / "source.sha256").exists())
                else:
                    workflow.assemble_units(job, "source")
                    book = core.validate_book(job, translated=False)
                    self.assertEqual({item["id"]: item for item in book["protected"]}, expected_protected)
                    self.assertEqual(book["blocks"], expected_blocks)
                    self.assertNotIn("OldVar", {item["id"] for item in book["protected"]})
                    self.assertNotIn("OwnedOld", {item["id"] for item in book["protected"]})
                    workflow.latest_role_receipt(job, workflow.load_job(job), "source")
                    workflow.seal_job(job)
                    self.assertEqual(workflow.load_job(job)["state"], "source_ready")
                    self.assertEqual(workflow.source_digest(job), (job / "source.sha256").read_text().strip())
                for name, content in preserved.items():
                    self.assertEqual((job / name).read_bytes(), content, name)



if __name__ == "__main__":
    unittest.main()
