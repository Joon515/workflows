"""Controller invariants with synthetic data; mocked workers never claim real inference."""
from __future__ import annotations

from contextlib import redirect_stdout
import io
import itertools
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import core
import translator as workflow

FAKE_BUILD_SEQUENCE = itertools.count(1)
PROVIDER = "anthropic"
MODEL = "claude-sonnet-4-6"


def source_book(locator="synthetic:1"):
    return {"version": 1, "title": "Synthetic source", "source_pages": [{"id": "P1", "locator": locator,
            "printed_label": None, "label_verified": False, "evidence": "Synthetic source page inspected for this controller fixture."}],
            "protected": [], "blocks": [{"id": "Paragraph", "kind": "paragraph", "source_pages": ["P1"],
            "source": [{"page": "P1"}, {"text": "Network protocol."}], "target": []}],
            "notes": [], "agent_preface": [], "human_preface": None}


def terms():
    return {"version": 1, "terms": [{"id": "Protocol", "number": 1, "source": "protocol", "target": "protocol",
            "authority": "Synthetic controller-test terminology decision", "authority_locator": "Fixture paragraph",
            "rationale": "This fixture tests routing and state, not terminology accuracy.", "protected_ids": []}]}


def passing_review(job, round_number):
    identity = workflow.current_build(job)
    return {"version": 1, "round": round_number, "content_digest": identity["content_digest"], "pdf_sha256": identity["pdf_sha256"],
            "verdict": "pass", "checks": {key: True for key in workflow.REVIEW_CHECKS},
            "findings": [], "evidence": ["Synthetic PDF fixture page 1; not a claim of professional or model review."]}


def fake_build(job):
    """Synthetic PDF/verification for controller tests only, not a renderer fallback."""
    core.validate_book(job, translated=True)
    directory = job / "build"
    directory.mkdir(exist_ok=True)
    pdf = directory / "book.pdf"
    digest = core.content_digest(job)
    pdf.write_bytes(b"%PDF-1.4\ncontroller test artifact; not compiled rendering evidence\n" + digest.encode("ascii") + f"\n% synthetic compiler generation {next(FAKE_BUILD_SEQUENCE)}\n".encode("ascii"))
    core.save_json(directory / "verification.json", {"version": 1, "content_digest": digest, "pdf_sha256": workflow.digest_file(pdf), "passed": True,
                   "checks": {key: True for key in workflow.BUILD_CHECKS}})
    return pdf


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="book-controller-test-")
        self.root = Path(self.temporary.name)
        self.source = self.root / "source.pdf"
        self.source.write_bytes(b"%PDF-1.4\nsynthetic source evidence\n")
        self.job = self.root / "job"
        workflow.init_job(self.source, self.job, "Controller fixture", "en", "zh-Hans")
        data = workflow.load_job(self.job)
        data["state"] = "extracted"
        core.save_json(self.job / "job.json", data)
        core.save_json(self.job / "book-source.json", source_book())
        workflow.seal_job(self.job)
        for stage in workflow.STAGES:
            workflow.configure_model(self.job, stage, PROVIDER, MODEL)
        self.render_patch = patch("render.build", side_effect=fake_build)
        self.render_patch.start()
        self.worker_patch = patch.object(workflow, "run_omp", side_effect=self.synthetic_worker)
        self.worker_patch.start()

    def tearDown(self):
        self.worker_patch.stop()
        self.render_patch.stop()
        self.temporary.cleanup()

    def synthetic_worker(self, job, stage, provider, model, prompt, **options):
        if options.get("check"):
            return {"checked": True, "inference": False, "provider": provider, "model": model}
        if stage == "terminology":
            core.save_json(job / "terms.json", terms())
            (job / "handoff.md").write_text("Synthetic controller test: genre, domain, authority and source caveats; no real model inference.", encoding="utf-8")
        else:
            book = core.load_json(job / "book-source.json")
            book["blocks"][0]["target"] = [{"page": "P1"}, {"text": "Network "}, {"term": "Protocol"}, {"text": "."}]
            book["agent_preface"] = [{"text": "Synthetic machine-translation controller fixture; not a real model translation or review."}]
            core.save_json(job / "book.json", book)
        return {"completed": True, "provider": provider, "model": model, "selector": f"{provider}/{model}",
                "omp_version": workflow.OMP_VERSION, "prompt_sha256": "synthetic-test", "frames": [{"type": "synthetic_test_only"}], "stderr": "", "argv": []}

    def translate(self):
        if workflow.load_job(self.job)["state"] == "source_ready":
            workflow.execute_stage(self.job, "terminology")
        return workflow.execute_stage(self.job, "translation")

    def submit(self, report):
        path = self.root / "report.json"
        core.save_json(path, report)
        return workflow.submit_review(self.job, path)

    def test_init_preserves_original_and_refuses_existing_job(self):
        data = workflow.load_job(self.job)
        self.assertEqual(data["max_rounds"], 3)
        self.assertEqual(self.source.read_bytes(), (self.job / data["source_file"]).read_bytes())
        with self.assertRaises(FileExistsError):
            workflow.init_job(self.source, self.job, "Other", "en", "fr")
        self.assertEqual(workflow.load_job(self.job)["title"], "Controller fixture")

    def test_model_rejection_before_job_mutation(self):
        old = (self.job / "job.json").read_bytes()
        for provider, model in (("openai", "gpt-5.2"), ("openrouter", "anthropic/claude-sonnet-4-6"), ("unknown", "claude-test"), ("anthropic", "@task"), ("google", "gemini-2.5-pro,openai/gpt-5.2")):
            with self.subTest(provider=provider, model=model), self.assertRaises(ValueError):
                workflow.configure_model(self.job, "translation", provider, model)
        self.assertEqual(old, (self.job / "job.json").read_bytes())

    def test_phases_provenance_and_acceptance(self):
        result = self.translate()
        self.assertEqual((result["state"], result["round"]), ("translated", 1))
        self.assertFalse((self.job / "output.pdf").exists())
        self.assertEqual(self.submit(passing_review(self.job, 1))["state"], "approved")
        path = workflow.accept_job(self.job)
        self.assertEqual(path.read_bytes(), (self.job / "build/book.pdf").read_bytes())
        self.assertTrue(workflow.latest_stage_receipt(self.job, workflow.load_job(self.job), "translation")["completed"])

    def test_hand_staged_translation_cannot_bypass_stage_provenance(self):
        self.synthetic_worker(self.job, "terminology", PROVIDER, MODEL, "")
        self.synthetic_worker(self.job, "translation", PROVIDER, MODEL, "")
        fake_build(self.job)
        data = workflow.load_job(self.job)
        data.update(state="translated", round=1)
        core.save_json(self.job / "job.json", data)
        with self.assertRaisesRegex(ValueError, "receipt"):
            self.submit(passing_review(self.job, 1))
        data["state"] = "approved"
        core.save_json(self.job / "job.json", data)
        with self.assertRaises(ValueError):
            workflow.accept_job(self.job)
        self.assertFalse((self.job / "output.pdf").exists())

    def test_translation_requires_terminology_receipt(self):
        data = workflow.load_job(self.job)
        data["state"] = "terminology_ready"
        core.save_json(self.job / "job.json", data)
        with self.assertRaisesRegex(ValueError, "receipt"):
            workflow.execute_stage(self.job, "translation")

    def test_failed_worker_does_not_consume_round(self):
        workflow.execute_stage(self.job, "terminology")
        with patch.object(workflow, "run_omp", side_effect=ValueError("provider failure")), self.assertRaisesRegex(ValueError, "provider failure"):
            workflow.execute_stage(self.job, "translation")
        self.assertEqual(workflow.load_job(self.job)["round"], 0)
        self.assertEqual(workflow.load_job(self.job)["state"], "terminology_ready")

    def test_failed_build_does_not_consume_round(self):
        workflow.execute_stage(self.job, "terminology")
        with patch("render.build", side_effect=ValueError("overflow")), self.assertRaisesRegex(ValueError, "overflow"):
            workflow.execute_stage(self.job, "translation")
        self.assertEqual(workflow.load_job(self.job)["round"], 0)

    def test_no_unreviewed_revision(self):
        self.translate()
        with self.assertRaisesRegex(ValueError, "submit the current review"):
            workflow.execute_stage(self.job, "translation")
        self.assertEqual(workflow.load_job(self.job)["round"], 1)

    def test_three_failed_pairs_exhaust_and_no_output(self):
        for number in range(1, 4):
            self.translate()
            report = passing_review(self.job, number)
            report["verdict"] = "changes_requested"
            report["checks"]["coverage"] = False
            report["findings"] = [{"id": "Missing", "severity": "major", "location": "Paragraph", "detail": "Synthetic missing coverage."}]
            state = self.submit(report)["state"]
            self.assertEqual(state, "exhausted" if number == 3 else "changes_requested")
        with self.assertRaises(ValueError):
            workflow.execute_stage(self.job, "translation")
        with self.assertRaises(ValueError):
            workflow.accept_job(self.job)
        self.assertFalse((self.job / "output.pdf").exists())

    def test_review_round_mismatch_and_replay(self):
        self.translate()
        with self.assertRaisesRegex(ValueError, "round"):
            self.submit(passing_review(self.job, 2))
        self.submit(passing_review(self.job, 1))
        with self.assertRaises(ValueError):
            self.submit(passing_review(self.job, 1))

    def test_pass_rejects_failed_check_or_finding(self):
        self.translate()
        invalid = passing_review(self.job, 1)
        invalid["checks"]["typography"] = False
        with self.assertRaises(ValueError):
            self.submit(invalid)
        invalid = passing_review(self.job, 1)
        invalid["findings"] = [{"id": "F", "severity": "minor", "location": "p1", "detail": "Not a clean pass"}]
        with self.assertRaises(ValueError):
            self.submit(invalid)

    def test_stale_manuscript_rejected_before_review(self):
        self.translate()
        authored = passing_review(self.job, 1)
        book = core.load_json(self.job / "book.json")
        book["blocks"][0]["target"].append({"text": "Changed translation."})
        core.save_json(self.job / "book.json", book)
        with self.assertRaisesRegex(ValueError, "stale"):
            self.submit(authored)

    def test_stale_pdf_rejected_before_acceptance(self):
        self.translate()
        self.submit(passing_review(self.job, 1))
        (self.job / "build/book.pdf").write_bytes(b"%PDF-1.4\nchanged PDF\n")
        with self.assertRaisesRegex(ValueError, "stale"):
            workflow.accept_job(self.job)
        self.assertFalse((self.job / "output.pdf").exists())

    def test_changed_review_and_receipt_rejected(self):
        self.translate()
        self.submit(passing_review(self.job, 1))
        path = self.job / "reviews/round-1.json"
        report = core.load_json(path)
        report["evidence"].append("Changed evidence after submission")
        core.save_json(path, report)
        with self.assertRaisesRegex(ValueError, "stale"):
            workflow.accept_job(self.job)
        receipt = self.job / "reviews/round-1.receipt.json"
        receipt.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "receipt"):
            workflow.accept_job(self.job)

    def test_changed_terms_and_trace_rejected(self):
        self.translate()
        handoff = self.job / "handoff.md"
        handoff.write_text("Altered handoff", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Terminology/handoff"):
            self.submit(passing_review(self.job, 1))

    def test_explicit_reseal_invalidates_downstream_and_preserves_unrelated_files(self):
        self.translate()
        self.submit(passing_review(self.job, 1))
        workflow.accept_job(self.job)
        unrelated = self.job / "build/user-notes.txt"
        unrelated.write_text("User-owned notes", encoding="utf-8")
        book = core.load_json(self.job / "book-source.json")
        book["blocks"][0]["source"].append({"text": "Explicit source correction."})
        core.save_json(self.job / "book-source.json", book)
        with self.assertRaisesRegex(ValueError, "reseal"):
            workflow.seal_job(self.job)
        workflow.seal_job(self.job, reseal=True)
        self.assertEqual(workflow.load_job(self.job)["state"], "source_ready")
        self.assertEqual(workflow.load_job(self.job)["round"], 0)
        self.assertTrue(unrelated.exists())
        self.assertFalse((self.job / "output.pdf").exists())
        self.assertFalse((self.job / "build/verification.json").exists())
        with self.assertRaises(ValueError):
            workflow.accept_job(self.job)
        archived = list((self.job / "reviews/archive").glob("source-*/round-1.receipt.json"))
        self.assertEqual(len(archived), 1)
        self.assertFalse((self.job / "reviews/round-1.receipt.json").exists())
        old_event = next(item for item in workflow.load_job(self.job)["history"] if item.get("event") == "review_submitted")
        self.assertEqual(self.job / old_event["receipt"], archived[0])
        self.translate()
        self.assertEqual(self.submit(passing_review(self.job, 1))["state"], "approved")
        self.assertTrue(workflow.accept_job(self.job).is_file())

    def test_unchanged_reseal_cannot_reset_round_limit(self):
        self.translate()
        with self.assertRaisesRegex(ValueError, "unchanged"):
            workflow.seal_job(self.job, reseal=True)
        self.assertEqual(workflow.load_job(self.job)["round"], 1)

    def test_invalid_max_rounds_rejected_before_creating_job(self):
        for number in (0, -1):
            destination = self.root / f"invalid-{number}"
            with self.subTest(rounds=number), self.assertRaisesRegex(ValueError, "positive"):
                workflow.init_job(self.source, destination, "Invalid", "en", "fr", max_rounds=number)
            self.assertFalse(destination.exists())

    def test_source_evidence_tampering_rejected(self):
        (self.job / "evidence/source.pdf").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "source evidence"):
            workflow.load_job(self.job)

    def test_check_does_not_advance_or_require_source_readiness(self):
        before = (self.job / "job.json").read_bytes()
        self.assertFalse(workflow.execute_stage(self.job, "translation", check=True)["inference"])
        self.assertEqual(before, (self.job / "job.json").read_bytes())

    def test_real_pdf_initial_lifecycle(self):
        import pymupdf as fitz
        source = self.root / "actual.pdf"
        with fitz.open() as document:
            page = document.new_page()
            page.insert_text((72, 72), "Network protocol.")
            document.save(source)
        job = self.root / "actual-job"
        workflow.init_job(source, job, "Actual extraction lifecycle", "en", "fr")
        result = workflow.extract_job(job, ocr="auto")
        self.assertEqual(workflow.load_job(job)["state"], "extracted")
        self.assertEqual(result["input"]["sha256"], workflow.digest_file(source))
        book = source_book(result["pages"][0]["locator"])
        core.save_json(job / "book-source.json", book)
        workflow.seal_job(job)
        self.assertEqual(workflow.load_job(job)["state"], "source_ready")
        self.assertFalse((job / "book.json").exists())


    def test_old_unsubmitted_review_rejected_after_source_revision_same_round(self):
        self.translate()
        old_report = passing_review(self.job, 1)
        old_path = self.root / "authored-old-report.json"
        core.save_json(old_path, old_report)
        source = core.load_json(self.job / "book-source.json")
        source["blocks"][0]["source"].append({"text": "A reviewed source correction changes the manuscript."})
        core.save_json(self.job / "book-source.json", source)
        workflow.seal_job(self.job, reseal=True)
        self.translate()
        current = workflow.current_build(self.job)
        self.assertEqual(workflow.load_job(self.job)["round"], old_report["round"])
        self.assertNotEqual(old_report["content_digest"], current["content_digest"])
        self.assertNotEqual(old_report["pdf_sha256"], current["pdf_sha256"])
        with self.assertRaisesRegex(ValueError, "Review describes different or stale"):
            workflow.submit_review(self.job, old_path)
        self.assertFalse((self.job / "reviews/round-1.receipt.json").exists())

    def test_review_from_different_translated_job_same_round_rejected(self):
        self.translate()
        authored = passing_review(self.job, 1)
        report_path = self.root / "first-job-report.json"
        core.save_json(report_path, authored)
        second = self.root / "second-job"
        workflow.init_job(self.source, second, "Independently translated second job", "en", "fr")
        data = workflow.load_job(second)
        data["state"] = "extracted"
        core.save_json(second / "job.json", data)
        core.save_json(second / "book-source.json", source_book())
        workflow.seal_job(second)
        for stage in workflow.STAGES:
            workflow.configure_model(second, stage, PROVIDER, MODEL)
        workflow.execute_stage(second, "terminology")
        workflow.execute_stage(second, "translation")
        self.assertEqual(workflow.load_job(second)["round"], authored["round"])
        self.assertNotEqual(workflow.current_build(second)["content_digest"], authored["content_digest"])
        with self.assertRaisesRegex(ValueError, "Review describes different or stale"):
            workflow.submit_review(second, report_path)
        self.assertFalse((second / "reviews/round-1.receipt.json").exists())

    def test_authored_pdf_identity_required_even_with_matching_content(self):
        self.translate()
        authored = passing_review(self.job, 1)
        authored["pdf_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "Review describes different or stale"):
            self.submit(authored)

    def test_status_exposes_build_identity_and_stale_error(self):
        self.translate()
        capture = io.StringIO()
        with redirect_stdout(capture):
            self.assertEqual(workflow.main(["status", str(self.job)]), 0)
        state = json.loads(capture.getvalue())
        self.assertEqual(state["current_build"], workflow.current_build(self.job))
        (self.job / "build/book.pdf").write_bytes(b"%PDF-1.4\nstale status fixture\n")
        capture = io.StringIO()
        with redirect_stdout(capture):
            self.assertEqual(workflow.main(["status", str(self.job)]), 0)
        state = json.loads(capture.getvalue())
        self.assertIsNone(state["current_build"])
        self.assertIn("stale", state["build_error"])


    def test_rebuild_same_content_allows_new_review_without_model_or_round_change(self):
        self.translate()
        data = workflow.load_job(self.job)
        receipt = workflow.latest_stage_receipt(self.job, data, "translation")
        old_identity = workflow.current_build(self.job)
        capture = io.StringIO()
        with patch.object(workflow, "run_omp", side_effect=AssertionError("Rebuilding must not invoke a model")), redirect_stdout(capture):
            self.assertEqual(workflow.main(["build", str(self.job)]), 0)
        fresh = workflow.current_build(self.job)
        self.assertEqual(fresh["content_digest"], old_identity["content_digest"])
        self.assertNotEqual(fresh["pdf_sha256"], old_identity["pdf_sha256"])
        self.assertEqual(receipt["pdf_sha256"], old_identity["pdf_sha256"])
        self.assertEqual(workflow.load_job(self.job)["round"], 1)
        self.assertEqual(workflow.load_job(self.job)["state"], "translated")
        self.assertEqual(self.submit(passing_review(self.job, 1))["state"], "approved")
        accepted = workflow.accept_job(self.job)
        self.assertEqual(workflow.digest_file(accepted), fresh["pdf_sha256"])

    def test_old_unsubmitted_report_rejected_after_same_content_rebuild(self):
        self.translate()
        authored = passing_review(self.job, 1)
        path = self.root / "pre-rebuild-report.json"
        core.save_json(path, authored)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(workflow.main(["build", str(self.job)]), 0)
        fresh = workflow.current_build(self.job)
        self.assertEqual(authored["content_digest"], fresh["content_digest"])
        self.assertNotEqual(authored["pdf_sha256"], fresh["pdf_sha256"])
        with self.assertRaisesRegex(ValueError, "Review describes different or stale"):
            workflow.submit_review(self.job, path)
        self.assertEqual(workflow.load_job(self.job)["state"], "translated")
        self.assertFalse((self.job / "reviews/round-1.receipt.json").exists())

    def test_missing_pdf_recovery_uses_admitted_content_not_another_model_round(self):
        self.translate()
        original = workflow.current_build(self.job)
        (self.job / "build/book.pdf").unlink()
        with patch.object(workflow, "run_omp", side_effect=AssertionError("PDF recovery must not invoke a model")), redirect_stdout(io.StringIO()):
            self.assertEqual(workflow.main(["build", str(self.job)]), 0)
        fresh = workflow.current_build(self.job)
        self.assertEqual(fresh["content_digest"], original["content_digest"])
        self.assertNotEqual(fresh["pdf_sha256"], original["pdf_sha256"])
        self.assertEqual(workflow.load_job(self.job)["round"], 1)
        self.submit(passing_review(self.job, 1))
        self.assertEqual(workflow.digest_file(workflow.accept_job(self.job)), fresh["pdf_sha256"])


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="book-rpc-test-")
        self.root = Path(self.temporary.name)
        self.binary = self.root / "fake-omp"
        self.write_transport()

    def tearDown(self):
        self.temporary.cleanup()

    def write_transport(self, *, version=workflow.OMP_VERSION, provider=PROVIDER, model=MODEL, status="completed", tools=workflow.TOOLS):
        # An explicit fake executable exercises RPC admission/transport only, never inference.
        script = '''#!/usr/bin/env python3
import json,sys
if '--version' in sys.argv:
    print('omp/VERSION');sys.exit(0)
model={'provider':'PROVIDER','id':'MODEL'}
for line in sys.stdin:
    command=json.loads(line);kind=command['type'];identifier=command['id']
    if kind=='get_state':
        data={'model':model,'dumpTools':[{'name':name} for name in TOOLS], 'isSettled':True,'isStreaming':False,'hasPendingAsyncWork':False}
        print(json.dumps({'type':'response','id':identifier,'success':True,'data':data}),flush=True)
    elif kind=='prompt':
        print(json.dumps({'type':'response','id':identifier,'success':True,'data':{}}),flush=True)
        print(json.dumps({'type':'message_end','message':{'role':'assistant','provider':model['provider'],'model':model['id'],'stopReason':'stop','content':[{'type':'text','text':'synthetic transport completion'}]}}),flush=True)
        print(json.dumps({'type':'prompt_result','id':identifier,'status':'STATUS','agentInvoked':True,'sessionSettled':True}),flush=True)
'''
        script = script.replace("VERSION", version).replace("PROVIDER", provider).replace("MODEL", model).replace("STATUS", status).replace("TOOLS", repr(list(tools)))
        self.binary.write_text(script, encoding="utf-8")
        self.binary.chmod(0o755)

    def test_sanitized_environment_and_normalized_google_key(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "unit-test-not-real", "ANTHROPIC_BASE_URL": "https://not-allowed.invalid", "GOOGLE_API_KEY": "unit-test-google", "PI_CONFIG_FILES": "untrusted"}, clear=True):
            environment, supplied = workflow.isolated_environment(self.root, "google", True)
            self.assertEqual(environment["GEMINI_API_KEY"], "unit-test-google")
            self.assertEqual(supplied, "GOOGLE_API_KEY")
            self.assertEqual(set(environment), {"PATH", "TERM", "HOME", "PI_CODING_AGENT_DIR", "GEMINI_API_KEY"})
            checked, _ = workflow.isolated_environment(self.root, "google", False)
            self.assertNotIn("GEMINI_API_KEY", checked)

    def test_keyless_rpc_check(self):
        with patch.dict(os.environ, {}, clear=True):
            result = workflow.run_omp(self.root, "translation", PROVIDER, MODEL, "", check=True, omp=str(self.binary), timeout=5)
        self.assertTrue(result["checked"])
        self.assertFalse(result["inference"])

    def test_key_required_only_for_inference(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(ValueError, "Preflight passed.*requires"):
            workflow.run_omp(self.root, "translation", PROVIDER, MODEL, "never sent", omp=str(self.binary), timeout=5)

    def test_exact_model_and_unexpected_tools_fail_before_prompt(self):
        for provider, model, tools in (("openai", "gpt-5.2", workflow.TOOLS), (PROVIDER, "claude-other", workflow.TOOLS), (PROVIDER, MODEL, (*workflow.TOOLS, "task"))):
            self.write_transport(provider=provider, model=model, tools=tools)
            with self.subTest(provider=provider, model=model, tools=tools), self.assertRaises(ValueError):
                workflow.run_omp(self.root, "translation", PROVIDER, MODEL, "", check=True, omp=str(self.binary), timeout=5)

    def test_version_mismatch_fails(self):
        self.write_transport(version="99.0.0")
        with self.assertRaisesRegex(ValueError, "requires omp"):
            workflow.run_omp(self.root, "translation", PROVIDER, MODEL, "", check=True, omp=str(self.binary), timeout=5)

    def test_aborted_or_error_rpc_result_fails_despite_process_status(self):
        for status in ("aborted", "error"):
            self.write_transport(status=status)
            with self.subTest(status=status), patch.dict(os.environ, {"ANTHROPIC_API_KEY": "synthetic-not-a-real-key"}), self.assertRaisesRegex(ValueError, "stage failed"):
                workflow.run_omp(self.root, "translation", PROVIDER, MODEL, "transport fixture only", omp=str(self.binary), timeout=5)

    @unittest.skipUnless(os.environ.get("BOOK_TRANSLATOR_REAL_OMP_CHECK") == "1", "opt-in real keyless omp preflight")
    def test_installed_omp_keyless_preflight(self):
        result = workflow.run_omp(self.root, "translation", PROVIDER, MODEL, "", check=True, timeout=60)
        self.assertEqual(result["omp_version"], workflow.OMP_VERSION)
        self.assertEqual(result["provider"], PROVIDER)
        self.assertEqual(result["model"], MODEL)
        self.assertNotIn("task", result["tools"])
        self.assertFalse(result["inference"])


if __name__ == "__main__":
    unittest.main()
