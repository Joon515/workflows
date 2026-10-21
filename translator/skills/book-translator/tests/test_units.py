"""Book unit-checkpoint regressions; metadata fixtures never prove native inference."""
from __future__ import annotations

from collections import Counter
import copy
import io
import json
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

    def admit_terminology(self, job):
        core.save_json(job / "terms.json", {"version": 1, "terms": []})
        (job / "handoff.md").write_text("Synthetic fixture: no governed terminology entries.\n", encoding="utf-8")
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

    

    


if __name__ == "__main__":
    unittest.main()
