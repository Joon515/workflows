"""Isolated unit-contract regressions; synthetic evidence never proves inference."""
from __future__ import annotations

from collections import Counter
import copy
import io
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
import test_workflow as native_fixtures


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
        reference = workflow.plan_native_units(job, role, pages_per_unit, draft=draft)
        return core.load_json(job / reference["plan"])

    def prepare(self, job, role, unit_id):
        prepared = workflow.begin_native_role(job, role, unit=unit_id)
        request = core.load_json(Path(prepared["request_path"]))
        binding = request["bindings"]["unit"]
        packet = core.load_json(job / binding["packet"])
        return prepared, binding, packet, unit_output(packet, binding)

    def finish(self, job, prepared, output, evidence=None):
        request = core.load_json(Path(prepared["request_path"]))
        core.save_json(job / request["bindings"]["unit"]["result"], output)
        evidence_path = native_fixtures.save_evidence(prepared, evidence)
        return workflow.complete_native_role(Path(prepared["request_path"]), evidence_path)

    def admit_source(self, job):
        plan = self.plan(job)
        for spec in plan["units"]:
            prepared, _, _, output = self.prepare(job, "source", spec["unit_id"])
            self.finish(job, prepared, output)
        workflow.assemble_native_units(job, "source")
        workflow.seal_job(job)

    def admit_terminology(self, job):
        prepared = workflow.begin_native_role(job, "terminology")
        core.save_json(job / "terms.json", {"version": 1, "terms": []})
        (job / "handoff.md").write_text("Synthetic fixture: no governed terminology entries.\n", encoding="utf-8")
        workflow.complete_native_role(Path(prepared["request_path"]), native_fixtures.save_evidence(prepared))

    def admit_translation(self, job, plan, pdf_pages=2):
        for spec in plan["units"]:
            prepared, _, _, output = self.prepare(job, "translation", spec["unit_id"])
            self.finish(job, prepared, output)
        with patch("render.build", side_effect=lambda current: synthetic_build(current, pdf_pages)):
            return workflow.assemble_native_units(job, "translation")

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
        prepared = workflow.begin_native_role(job, "source")
        page = core.extraction_inventory(job)["pages"][0]
        book = native_fixtures.source_book(page["locator"])
        core.save_json(job / "book-source.json", book)
        with self.assertRaisesRegex(ValueError, "every original extraction page"):
            workflow.complete_native_role(Path(prepared["request_path"]), native_fixtures.save_evidence(prepared))
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
            workflow.assemble_native_units(job, "source")
        self.assertFalse((job / "book-source.json").exists())
        self.assertEqual((job / "job.json").read_bytes(), before)
        prepared, _, _, output = siblings[0]
        self.finish(job, prepared, output)
        self.assertEqual((job / "job.json").read_bytes(), before)
        workflow.assemble_native_units(job, "source")
        book = core.load_json(job / "book-source.json")
        self.assertEqual(len(book["protected"]), 1)
        self.assertEqual(sum(token.get("protected") == "SharedName"
                             for block in book["blocks"] for token in block["source"]), 2)
        receipt = workflow.latest_role_receipt(job, workflow.load_job(job), "source")
        self.assertEqual(receipt["execution"], "native-units")
        self.assertEqual(len(receipt["unit_receipts"]), 2)
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
                    workflow.assemble_native_units(job, "source")
                    self.assertEqual(core.load_json(job / "book-source.json")["main_body_start"], candidate)
                else:
                    with self.assertRaisesRegex(ValueError, "exactly one verified main-body boundary"):
                        workflow.assemble_native_units(job, "source")
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
                    workflow.assemble_native_units(job, "review")
                self.assertFalse((job / "reviews/round-1.json").exists())
            self.finish(job, prepared, output)
        workflow.assemble_native_units(job, "review")
        report = core.load_json(job / "reviews/round-1.json")
        self.assertEqual(report["verdict"], "changes_requested")
        self.assertFalse(report["checks"]["typography"])
        self.assertTrue(all(value for key, value in report["checks"].items() if key != "typography"))
        self.assertEqual(report["findings"], expected_findings)
        self.assertEqual(workflow.submit_review(job, job / "reviews/round-1.json")["state"], "changes_requested")
        self.assertFalse((job / "output.pdf").exists())

    def test_provisional_units_check_own_proof_and_defer_ancestor_replay(self):
        job = self.new_job()
        self.admit_source(job)
        self.admit_terminology(job)
        plan = self.plan(job, "translation")
        source_receipt = workflow.latest_role_receipt(job, workflow.load_job(job), "source")
        member = core.load_json(job / source_receipt["unit_receipts"][0]["path"])
        ancestor = job / member["trace"]
        original_ancestor = ancestor.read_bytes()
        ancestor.write_bytes(original_ancestor + b"Synthetic ancestor tampering.\n")
        before = (job / "job.json").read_bytes()
        for index, spec in enumerate(plan["units"]):
            prepared, _, _, output = self.prepare(job, "translation", spec["unit_id"])
            evidence = native_fixtures.synthetic_evidence(prepared)
            if index == 0:
                own_trace = job / evidence["trace"]
                original_own = own_trace.read_bytes()
                own_trace.write_bytes(original_own + b"Synthetic own-proof tampering.\n")
                with self.assertRaisesRegex(ValueError, "native execution trace"):
                    self.finish(job, prepared, output, evidence)
                own_trace.write_bytes(original_own)
            self.finish(job, prepared, output, evidence)
            self.assertEqual((job / "job.json").read_bytes(), before)
        with self.assertRaisesRegex(ValueError, "native execution trace"):
            workflow.assemble_native_units(job, "translation")
        self.assertFalse((job / "book.json").exists())
        self.assertEqual((job / "job.json").read_bytes(), before)
        with self.assertRaisesRegex(ValueError, "native execution trace"):
            workflow.source_digest(job)
        ancestor.write_bytes(original_ancestor)
        with patch("render.build", side_effect=synthetic_build):
            result = workflow.assemble_native_units(job, "translation")
        self.assertEqual((result["state"], result["round"]), ("translated", 1))

    def test_host_failure_rejects_otherwise_recovered_same_model_unit(self):
        job = self.new_job()
        self.plan(job)
        prepared, _, _, output = self.prepare(job, "source", "u0001")
        evidence = native_fixtures.synthetic_evidence(prepared)
        intermediate = copy.deepcopy(evidence["assistant_messages"][0])
        intermediate.update(stopReason="error", errorMessage="Synthetic transient same-model error.")
        evidence["assistant_messages"].insert(0, intermediate)
        failed = copy.deepcopy(evidence)
        failed["failure"] = "Synthetic host-observed routing failure."
        with self.assertRaisesRegex(ValueError, "Native host captured"):
            self.finish(job, prepared, output, failed)
        result = self.finish(job, prepared, output, evidence)
        self.assertTrue(result["completed"])
        self.assertEqual((result["provider"], result["model"]), (PROVIDER, MODEL))
        self.assertFalse((job / "book-source.json").exists())


if __name__ == "__main__":
    unittest.main()
