"""Domain checkpoint/state tests; task metadata fixtures never claim real inference."""
from __future__ import annotations

from contextlib import redirect_stdout
import copy
import io
import itertools
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import core
import translator as workflow

FAKE_BUILD_SEQUENCE = itertools.count(1)
TASK_SEQUENCE = itertools.count(1)
PROVIDER = "anthropic"
MODEL = "claude-sonnet-4-6"


def source_book(locator="synthetic:1"):
    return {"version": 2, "title": "Synthetic source", "main_body_start": "Paragraph", "source_pages": [{"id": "P1", "locator": locator,
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


def save_task_result(directory, role, provider=PROVIDER, model=MODEL, result=None):
    """Coordinator-owned SingleResult fixture input, not proof of real task execution."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    number = next(TASK_SEQUENCE)
    path = directory / f"settled-task-{number}.json"
    core.save_json(path, result if result is not None else {
        "id": f"FixtureTask{number}", "agent": "book-" + role, "exitCode": 0,
        "resolvedModelIdentity": provider + "/" + model, "resolvedModelIsFallback": False,
    })
    return path





class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="book-controller-test-")
        self.root = Path(self.temporary.name)
        self.source = self.root / "source.pdf"
        self.source.write_bytes(b"%PDF-1.4\nsynthetic source evidence\n")
        self.job = self.root / "job"
        workflow.init_job(self.source, self.job, "Controller fixture", "en", "zh-Hans")
        for role in workflow.ROLES:
            workflow.configure_model(self.job, role, PROVIDER, MODEL)
        data = workflow.load_job(self.job)
        data["state"] = "extracted"
        core.save_json(self.job / "job.json", data)
        self.author_and_checkpoint("source")
        workflow.seal_job(self.job)
        self.render_patch = patch("render.build", side_effect=fake_build)
        self.render_patch.start()

    def tearDown(self):
        self.render_patch.stop()
        self.temporary.cleanup()

    def author_fixture(self, job, role):
        if role == "source":
            if not (job / "book-source.json").exists():
                core.save_json(job / "book-source.json", source_book())
        elif role == "terminology":
            core.save_json(job / "terms.json", terms())
            (job / "handoff.md").write_text("Synthetic fixture: genre, domain, authority and source caveats; no real inference.", encoding="utf-8")
        elif role == "translation":
            book = core.load_json(job / "book-source.json")
            book["blocks"][0]["target"] = [{"page": "P1"}, {"text": "Network "}, {"term": "Protocol"}, {"text": "."}]
            book["agent_preface"] = [{"text": "Synthetic translation fixture; not a real model translation or review."}]
            core.save_json(job / "book.json", book)
        else:
            core.save_json(job / f"reviews/round-{workflow.load_job(job)['round']}.json", passing_review(job, workflow.load_job(job)["round"]))

    

    def author_and_checkpoint(self, role, *, job=None, revise=False):
        job = self.job if job is None else job
        self.author_fixture(job, role)
        selected = workflow.load_job(job)["models"][role]
        result = save_task_result(self.root / "coordinator-results", role, **selected)
        return workflow.checkpoint_role(job, role, result, revise=revise)

    def translate(self):
        if workflow.load_job(self.job)["state"] == "source_ready":
            self.author_and_checkpoint("terminology")
        return self.author_and_checkpoint("translation")

    def submit(self, report):
        path = self.job / f"reviews/round-{workflow.load_job(self.job)['round']}.json"
        core.save_json(path, report)
        result = save_task_result(self.root / "coordinator-results", "review")
        workflow.checkpoint_role(self.job, "review", result)
        return workflow.submit_review(self.job, path)

    def job_artifacts(self):
        return {path.relative_to(self.job).as_posix(): path.read_bytes()
                for path in self.job.rglob("*") if path.is_file()}

    def assert_stage_rejected_without_mutation(self, stage, **options):
        result = save_task_result(self.root / "coordinator-results", stage)
        before = self.job_artifacts()
        with self.assertRaises((ValueError, OSError)):
            workflow.checkpoint_role(self.job, stage, result, **options)
        self.assertEqual(self.job_artifacts(), before)

    def author_pending_translation(self):
        if workflow.load_job(self.job)["state"] == "source_ready":
            self.author_and_checkpoint("terminology")
        with patch("render.build", side_effect=ValueError("synthetic formatter failure")), self.assertRaisesRegex(ValueError, "formatter failure"):
            self.author_and_checkpoint("translation")
        data = workflow.load_job(self.job)
        event = data["history"][-1]
        self.assertEqual(event["event"], "translation_content_authored")
        return event, core.load_json(self.job / event["receipt"])

    def assert_finalize_rejected_without_mutation(self):
        before = self.job_artifacts()
        with patch("render.build") as build:
            with self.assertRaises((ValueError, OSError)):
                workflow.finalize_translation(self.job)
        build.assert_not_called()
        self.assertEqual(self.job_artifacts(), before)


    def test_init_preserves_original_and_refuses_existing_job(self):
        data = workflow.load_job(self.job)
        self.assertEqual(data["max_rounds"], 3)
        self.assertEqual(self.source.read_bytes(), (self.job / data["source_file"]).read_bytes())
        with self.assertRaises(FileExistsError):
            workflow.init_job(self.source, self.job, "Other", "en", "fr")
        self.assertEqual(workflow.load_job(self.job)["title"], "Controller fixture")

    def test_model_rejection_before_job_mutation(self):
        old = (self.job / "job.json").read_bytes()
        for provider, model in (("openai", "@task"), ("openrouter", "anthropic/*"), ("unknown ", "claude-test"), ("anthropic", "@task"), ("google", "gemini-2.5-pro,openai/gpt-5.2"), ("opencode-go", "deepseek-v4-flash other")):
            with self.subTest(provider=provider, model=model), self.assertRaises(ValueError):
                workflow.configure_model(self.job, "translation", provider, model)
        self.assertEqual(old, (self.job / "job.json").read_bytes())

    def test_configure_model_cli_rejects_implicit_aliases_before_mutation(self):
        original = (self.job / "job.json").read_bytes()
        for provider in ("openai", "anthropic", "custom-provider"):
            for model in ("auto", "default", "Default", "auto:high", "openrouter/auto", "default@route"):
                with self.subTest(provider=provider, model=model), redirect_stdout(io.StringIO()), patch("sys.stderr", io.StringIO()):
                    self.assertEqual(workflow.main(["configure-model", str(self.job), "source", "--provider", provider, "--model", model]), 1)
                self.assertEqual((self.job / "job.json").read_bytes(), original)

    def test_configure_model_cli_repairs_stored_aliases_without_authorizing_execution(self):
        data = workflow.load_job(self.job)
        data["models"]["source"]["model"] = "auto"
        data["models"]["terminology"]["model"] = "default"
        core.save_json(self.job / "job.json", data)  # A pre-fix stored configuration, not inference evidence.
        source_hash = workflow.digest_file(self.job / data["source_file"])
        seal = (self.job / "source.sha256").read_bytes()
        with redirect_stdout(io.StringIO()), patch("sys.stderr", io.StringIO()):
            self.assertEqual(workflow.main(["configure-model", str(self.job), "translation", "--provider", "openai", "--model", "gpt-5.2"]), 0)
        stored = core.load_json(self.job / "job.json")
        self.assertEqual(stored["models"]["source"]["model"], "auto")
        self.assertEqual(stored["models"]["translation"], {"provider": "openai", "model": "gpt-5.2"})
        before = (self.job / "job.json").read_bytes()
        with self.assertRaises(ValueError):
            workflow.role_readiness(self.job, "translation")
        
        self.assertEqual((self.job / "job.json").read_bytes(), before)
        for role in ("source", "terminology", "review"):
            with redirect_stdout(io.StringIO()), patch("sys.stderr", io.StringIO()):
                self.assertEqual(workflow.main(["configure-model", str(self.job), role, "--provider", "openai", "--model", "gpt-5.2"]), 0)
        repaired = workflow.load_job(self.job)
        workflow.require_models(repaired)
        self.assertTrue(all(selected == {"provider": "openai", "model": "gpt-5.2"} for selected in repaired["models"].values()))
        self.assertEqual((repaired["state"], repaired["round"], repaired["max_rounds"]), (data["state"], data["round"], data["max_rounds"]))
        self.assertEqual(workflow.digest_file(self.job / data["source_file"]), source_hash)
        self.assertEqual((self.job / "source.sha256").read_bytes(), seal)

    def test_configuration_recovery_still_validates_structure_layout_and_source(self):
        original = workflow.load_job(self.job)
        for change in (lambda item: item.update(max_rounds=0),
                       lambda item: item["layout"].update(outer_mm=0),
                       lambda item: item["models"]["source"].update(extra_field=True)):
            data = copy.deepcopy(original)
            data["models"]["source"]["model"] = "auto"
            change(data)
            core.save_json(self.job / "job.json", data)
            before = (self.job / "job.json").read_bytes()
            with self.assertRaises(ValueError):
                workflow.configure_model(self.job, "source", "openai", "gpt-5.2")
            self.assertEqual((self.job / "job.json").read_bytes(), before)
        original["models"]["source"]["model"] = "auto"
        core.save_json(self.job / "job.json", original)
        (self.job / original["source_file"]).write_bytes(b"Changed original source evidence")
        before = (self.job / "job.json").read_bytes()
        with self.assertRaises(ValueError):
            workflow.configure_model(self.job, "source", "openai", "gpt-5.2")
        self.assertEqual((self.job / "job.json").read_bytes(), before)

    def test_all_roles_require_explicit_selection_before_source_or_inference(self):
        data = workflow.load_job(self.job)
        data["models"]["source"] = {"provider": "", "model": ""}
        core.save_json(self.job / "job.json", data)
        self.assert_stage_rejected_without_mutation("terminology")
        data["state"] = "initialized"
        core.save_json(self.job / "job.json", data)
        with patch("extract.extract") as extractor, self.assertRaisesRegex(ValueError, "Ask the user.*source"):
            workflow.extract_job(self.job)
        extractor.assert_not_called()

    def test_user_can_select_openai_for_every_role_without_consuming_rounds(self):
        for role in workflow.ROLES:
            workflow.configure_model(self.job, role, "openai", "gpt-5.2")
        data = workflow.load_job(self.job)
        workflow.require_models(data)
        self.assertEqual(set(data["models"]), set(workflow.ROLES))
        self.assertTrue(all(item == {"provider": "openai", "model": "gpt-5.2"} for item in data["models"].values()))
        self.assertEqual((data["state"], data["round"]), ("source_ready", 0))

    def test_review_checkpoint_records_task_reference_without_submitting_or_consuming_round(self):
        self.translate()
        result = self.author_and_checkpoint("review")
        receipt = core.load_json(Path(result["receipt"]))
        self.assertEqual(receipt["role"], "review")
        self.assertEqual(receipt["review_sha256"], workflow.digest_file(self.job / "reviews/round-1.json"))
        self.assertEqual((result["state"], result["round"]), ("translated", 1))
        self.assertFalse((self.job / "reviews/round-1.receipt.json").exists())
        self.assertFalse((self.job / "output.pdf").exists())
        workflow.translation_ready(self.job, workflow.load_job(self.job))
        workflow.submit_review(self.job, self.job / "reviews/round-1.json")
        released = workflow.accept_job(self.job)
        self.assertEqual(released.read_bytes(), (self.job / "build/book.pdf").read_bytes())
        self.assertEqual(workflow.load_job(self.job)["round"], 1)
    
    
    def test_review_task_reference_and_exact_build_report_cannot_go_stale(self):
        self.translate()
        result = self.author_and_checkpoint("review")
        path = Path(result["receipt"])
        original = path.read_bytes()
        receipt = core.load_json(path)
        self.assertEqual(receipt["task"]["agent"], "book-review")
        self.assertEqual(receipt["task"]["resolvedModelIdentity"], PROVIDER + "/" + MODEL)
        self.assertEqual(receipt["review_sha256"], workflow.digest_file(self.job / "reviews/round-1.json"))
        self.assertEqual({key: receipt[key] for key in workflow.current_build(self.job)}, workflow.current_build(self.job))
        receipt["task"]["id"] = "DifferentSettledTask"
        core.save_json(path, receipt)
        before = self.job_artifacts()
        with self.assertRaises(ValueError):
            workflow.submit_review(self.job, self.job / "reviews/round-1.json")
        self.assertEqual(self.job_artifacts(), before)
        self.assertFalse((self.job / "output.pdf").exists())
        path.write_bytes(original)
        verification = self.job / "build/verification.json"
        original_verification = verification.read_bytes()
        verification.write_bytes(original_verification + b"\n")
        with self.assertRaises(ValueError):
            workflow.submit_review(self.job, self.job / "reviews/round-1.json")
        verification.write_bytes(original_verification)
        workflow.submit_review(self.job, self.job / "reviews/round-1.json")
        self.assertEqual(workflow.accept_job(self.job).read_bytes(), (self.job / "build/book.pdf").read_bytes())

    def test_source_checkpoint_does_not_seal_or_advance_state(self):
        source = self.root / "native-source.pdf"
        source.write_bytes(b"%PDF-1.4 synthetic native source fixture")
        job = self.root / "native-source-job"
        workflow.init_job(source, job, "Native fixture", "en", "fr")
        for role in workflow.ROLES:
            workflow.configure_model(job, role, PROVIDER, MODEL)
        data = workflow.load_job(job)
        data["state"] = "extracted"
        core.save_json(job / "job.json", data)
        result = self.author_and_checkpoint("source", job=job)
        self.assertEqual((result["state"], result["round"]), ("extracted", 0))
        self.assertFalse((job / "source.sha256").exists())
        workflow.seal_job(job)
        self.assertEqual(workflow.load_job(job)["state"], "source_ready")
        before = {path.relative_to(job).as_posix(): path.read_bytes() for path in job.rglob("*") if path.is_file()}
        with self.assertRaises(ValueError):
            self.author_and_checkpoint("source", job=job)
        
        self.assertEqual(before, {path.relative_to(job).as_posix(): path.read_bytes() for path in job.rglob("*") if path.is_file()})

    def test_review_refuses_missing_or_failed_mandatory_build_gates(self):
        self.translate()
        report = passing_review(self.job, 1)
        path = self.job / "build/verification.json"
        original = core.load_json(path)
        for gate in workflow.BUILD_CHECKS:
            for value in (None, False, 1, "true"):
                with self.subTest(gate=gate, value=value):
                    verification = copy.deepcopy(original)
                    if value is None:
                        verification["checks"].pop(gate)
                    else:
                        verification["checks"][gate] = value
                    core.save_json(path, verification)
                    with self.assertRaisesRegex(ValueError, "required checks"):
                        self.submit(report)
                    self.assertEqual(workflow.load_job(self.job)["state"], "translated")
                    self.assertFalse((self.job / "reviews/round-1.receipt.json").exists())
                    self.assertFalse((self.job / "output.pdf").exists())
        core.save_json(path, original)
        self.assertEqual(self.submit(report)["state"], "approved")


    def test_phases_provenance_and_acceptance(self):
        result = self.translate()
        self.assertEqual((result["state"], result["round"]), ("translated", 1))
        self.assertFalse((self.job / "output.pdf").exists())
        self.assertEqual(self.submit(passing_review(self.job, 1))["state"], "approved")
        path = workflow.accept_job(self.job)
        self.assertEqual(path.read_bytes(), (self.job / "build/book.pdf").read_bytes())
        self.assertTrue(workflow.latest_stage_receipt(self.job, workflow.load_job(self.job), "translation")["completed"])

    def test_hand_staged_translation_cannot_bypass_stage_provenance(self):
        self.author_fixture(self.job, "terminology")
        self.author_fixture(self.job, "translation")
        fake_build(self.job)
        data = workflow.load_job(self.job)
        data.update(state="translated", round=1)
        core.save_json(self.job / "job.json", data)
        with self.assertRaises(ValueError):
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
        with self.assertRaises(ValueError):
            self.author_and_checkpoint("translation")

    def test_explicit_pretranslation_terminology_revision_preserves_source_and_provenance(self):
        initial = self.author_and_checkpoint("terminology")
        original = workflow.load_job(self.job)
        preserved = self.job_artifacts()
        previous = workflow.terminology_ready(self.job, original)
        corrected = terms()
        corrected["terms"][0].update(target="revised protocol", rationale="Synthetic revision; no claim of normative authority.")
        core.save_json(self.job / "terms.json", corrected)
        (self.job / "handoff.md").write_text("Revised synthetic authority and source caveats.", encoding="utf-8")
        task = save_task_result(self.root / "coordinator-results", "terminology")
        revised = workflow.checkpoint_role(self.job, "terminology", task, revise=True)
        current = workflow.load_job(self.job)
        receipt = workflow.terminology_ready(self.job, current)
        self.assertEqual((revised["state"], revised["round"]), ("terminology_ready", 0))
        self.assertEqual({key: value for key, value in current.items() if key != "history"},
                         {key: value for key, value in original.items() if key != "history"})
        self.assertEqual(current["history"][:-1], original["history"])
        self.assertTrue(receipt["revision"])
        self.assertFalse(previous["revision"])
        self.assertNotEqual(revised["receipt"], initial["receipt"])
        self.assertEqual(receipt["task"], core.load_json(task))
        self.assertEqual(receipt["source_digest"], previous["source_digest"])
        self.assertNotEqual(receipt["terms_sha256"], previous["terms_sha256"])
        self.assertNotEqual(receipt["handoff_sha256"], previous["handoff_sha256"])
        for name, content in preserved.items():
            if name not in {"job.json", "terms.json", "handoff.md"}:
                self.assertEqual((self.job / name).read_bytes(), content, name)
        self.assertEqual(self.author_and_checkpoint("translation")["round"], 1)

    def test_terminology_revision_requires_prior_completion_and_explicit_intent(self):
        (self.job / "output.pdf").write_bytes(b"Must not be invalidated by admission failure")
        self.assert_stage_rejected_without_mutation("terminology", revise=True)
        self.author_fixture(self.job, "terminology")
        data = workflow.load_job(self.job)
        data["state"] = "terminology_ready"
        core.save_json(self.job / "job.json", data)
        self.assert_stage_rejected_without_mutation("terminology", revise=True)
        data["state"] = "source_ready"
        core.save_json(self.job / "job.json", data)
        self.author_and_checkpoint("terminology")
        self.assert_stage_rejected_without_mutation("terminology")

    def test_terminology_revision_rejects_every_other_state_and_later_round_before_worker(self):
        self.author_and_checkpoint("terminology")
        (self.job / "output.pdf").write_bytes(b"Must survive rejected revision")
        data = workflow.load_job(self.job)
        for state in ("initialized", "extracted", "source_ready", "terminology_ready", "translated", "changes_requested", "approved", "exhausted"):
            for round_number in range(4):
                if state == "terminology_ready" and round_number == 0:
                    continue
                with self.subTest(state=state, round=round_number):
                    data.update(state=state, round=round_number)
                    core.save_json(self.job / "job.json", data)
                    self.assert_stage_rejected_without_mutation("terminology", revise=True)

    def test_revision_flag_combinations_fail_before_worker_or_artifact_mutation(self):
        self.author_and_checkpoint("terminology")
        (self.job / "output.pdf").write_bytes(b"Must survive rejected flags")
        for role in ("translation", "review"):
            with self.subTest(role=role):
                self.assert_stage_rejected_without_mutation(role, revise=True)

    def test_terminology_revision_requires_unchanged_prior_completion_and_source(self):
        initial = self.author_and_checkpoint("terminology")
        for path in (Path(initial["receipt"]), self.job / "book-source.json", self.job / "source.sha256"):
            original = path.read_bytes()
            for missing in (False, True):
                with self.subTest(artifact=path.name, missing=missing):
                    try:
                        if missing:
                            path.unlink()
                        else:
                            path.write_bytes(original + b"\nchanged")
                        self.assert_stage_rejected_without_mutation("terminology", revise=True)
                    finally:
                        path.write_bytes(original)

    def test_terminology_revision_cannot_change_model_or_reuse_earlier_source_seal(self):
        self.author_and_checkpoint("terminology")
        data = workflow.load_job(self.job)
        original_model = data["models"]["terminology"]
        data["models"]["terminology"] = {"provider": "google", "model": "gemini-2.5-pro"}
        core.save_json(self.job / "job.json", data)
        self.assert_stage_rejected_without_mutation("terminology", revise=True)
        data["models"]["terminology"] = original_model
        core.save_json(self.job / "job.json", data)
        source = core.load_json(self.job / "book-source.json")
        source["blocks"][0]["source"].append({"text": "Changed sealed source."})
        core.save_json(self.job / "book-source.json", source)
        self.assert_stage_rejected_without_mutation("terminology", revise=True)
        core.seal_source(self.job)
        self.assert_stage_rejected_without_mutation("terminology", revise=True)

    

    def test_failed_terminology_revision_preserves_readiness_and_round_budget(self):
        self.author_and_checkpoint("terminology")
        task = save_task_result(self.root / "coordinator-results", "terminology")
        failed = core.load_json(task)
        failed["exitCode"] = 1
        core.save_json(task, failed)
        before = self.job_artifacts()
        with self.assertRaises(ValueError):
            workflow.checkpoint_role(self.job, "terminology", task, revise=True)
        self.assertEqual(self.job_artifacts(), before)
        workflow.terminology_ready(self.job, workflow.load_job(self.job))
        self.author_and_checkpoint("terminology", revise=True)
        self.assertEqual(workflow.load_job(self.job)["round"], 0)
        for number in range(1, 4):
            self.translate()
            report = passing_review(self.job, number)
            report.update(verdict="changes_requested", findings=[{"id": "Correction", "severity": "major", "location": "Term", "detail": "Synthetic correction request."}])
            report["checks"]["terminology"] = False
            self.submit(report)
        self.assertEqual((workflow.load_job(self.job)["state"], workflow.load_job(self.job)["round"]), ("exhausted", 3))
        self.assert_stage_rejected_without_mutation("terminology", revise=True)
        self.assert_stage_rejected_without_mutation("translation")

    def test_failed_settled_task_does_not_consume_round(self):
        self.author_and_checkpoint("terminology")
        self.author_fixture(self.job, "translation")
        task = save_task_result(self.root / "coordinator-results", "translation")
        failed = core.load_json(task)
        failed["exitCode"] = 1
        core.save_json(task, failed)
        before = self.job_artifacts()
        with self.assertRaises(ValueError):
            workflow.checkpoint_role(self.job, "translation", task)
        self.assertEqual(self.job_artifacts(), before)
        self.assertEqual((workflow.load_job(self.job)["state"], workflow.load_job(self.job)["round"]), ("terminology_ready", 0))

    def test_failed_build_does_not_consume_round(self):
        self.author_and_checkpoint("terminology")
        with patch("render.build", side_effect=ValueError("overflow")), self.assertRaisesRegex(ValueError, "overflow"):
            self.author_and_checkpoint("translation")
        self.assertEqual(workflow.load_job(self.job)["round"], 0)

    def test_failed_build_retains_verified_authoring_before_backend_without_advancement(self):
        self.author_and_checkpoint("terminology")
        previous = workflow.load_job(self.job)
        preserved = self.job_artifacts()

        def fail_after_authoring(job):
            data = workflow.load_job(job)
            self.assertEqual((data["state"], data["round"]), ("terminology_ready", 0))
            event = data["history"][-1]
            proof = workflow.translation_authoring_proof(job, data, event)
            self.assertFalse(proof["completed"])
            self.assertTrue(proof["authoring_complete"])
            self.assertEqual(proof["content_digest"], core.content_digest(job))
            self.assertEqual(proof["job_context_sha256"], workflow.translation_context_digest(previous))
            self.assertEqual(proof["terminology_receipt"], previous["history"][-1]["receipt"])
            self.assertEqual(proof["source_digest"], workflow.source_digest(job))
            self.assertEqual(proof["task"]["agent"], "book-translation")
            raise ValueError("formatter failed after authoring")

        with patch("render.build", side_effect=fail_after_authoring), self.assertRaisesRegex(ValueError, "formatter failed"):
            self.author_and_checkpoint("translation")
        current = workflow.load_job(self.job)
        self.assertEqual(current["history"][:-1], previous["history"])
        for name, content in preserved.items():
            if name != "job.json":
                self.assertEqual((self.job / name).read_bytes(), content, name)
        with self.assertRaises(ValueError):
            workflow.latest_stage_receipt(self.job, current, "translation")
        with self.assertRaises(ValueError):
            workflow.submit_review(self.job, self.root / "nonexistent-review.json")
        with self.assertRaisesRegex(ValueError, "passing submitted review"):
            workflow.accept_job(self.job)
        self.assertFalse((self.job / "output.pdf").exists())

    def test_failed_finalization_retains_identical_pending_proof_and_budget(self):
        self.author_pending_translation()
        before = self.job_artifacts()
        with patch("render.build", side_effect=ValueError("still overfull")):
            with self.assertRaisesRegex(ValueError, "still overfull"):
                workflow.finalize_translation(self.job)
        self.assertEqual(self.job_artifacts(), before)
        self.assertEqual((workflow.load_job(self.job)["state"], workflow.load_job(self.job)["round"]), ("terminology_ready", 0))

    def test_copied_job_and_pending_receipt_cannot_bypass_authoring_admission(self):
        event, proof = self.author_pending_translation()
        copied = self.root / "copied-job"
        shutil.copytree(self.job, copied)
        with patch("render.build") as build:
            with self.assertRaisesRegex(ValueError, "context changed"):
                workflow.finalize_translation(copied)
        
        build.assert_not_called()
        data = workflow.load_job(self.job)
        data.update(state="translated", round=1)
        data["history"].append({**event, "event": "stage_translation", "round": 1})
        core.save_json(self.job / "job.json", data)
        with self.assertRaises(ValueError):
            workflow.latest_stage_receipt(self.job, data, "translation")
        with self.assertRaises(ValueError):
            self.submit(passing_review(self.job, 1))
        self.assertFalse(proof["completed"])
        self.assertFalse((self.job / "output.pdf").exists())


    def test_finalize_rebuilds_once_without_inference_then_requires_review_acceptance(self):
        event, proof = self.author_pending_translation()
        original_proof = (self.job / event["receipt"]).read_bytes()
        # Even a valid current build is not a recovery cache.
        fake_build(self.job)
        old_pdf = workflow.digest_file(self.job / "build/book.pdf")
        with patch("render.build", side_effect=fake_build) as build:
            capture = io.StringIO()
            with redirect_stdout(capture):
                self.assertEqual(workflow.main(["finalize-translation", str(self.job)]), 0)
        
        build.assert_called_once_with(self.job)
        result = json.loads(capture.getvalue())
        self.assertEqual((result["state"], result["round"]), ("translated", 1))
        self.assertNotEqual(workflow.digest_file(self.job / "build/book.pdf"), old_pdf)
        completed = workflow.latest_stage_receipt(self.job, workflow.load_job(self.job), "translation")
        self.assertTrue(completed["completed"])
        self.assertEqual(completed["authoring_receipt"], event["receipt"])
        self.assertEqual(completed["authoring_receipt_sha256"], event["receipt_sha256"])
        self.assertEqual(completed["task"], proof["task"])
        self.assertEqual((self.job / event["receipt"]).read_bytes(), original_proof)
        self.assert_finalize_rejected_without_mutation()
        with self.assertRaises(ValueError):
            workflow.accept_job(self.job)
        self.assertFalse((self.job / "output.pdf").exists())
        self.submit(passing_review(self.job, 1))
        self.assertTrue(workflow.accept_job(self.job).is_file())

    def test_finalize_rejects_missing_or_changed_authoring_and_terminology_evidence(self):
        event, proof = self.author_pending_translation()
        for path in (self.job / event["receipt"], self.job / proof["terminology_receipt"],
                     self.job / "terms.json", self.job / "handoff.md", self.job / "book.json",
                     self.job / "book-source.json", self.job / "source.sha256", self.job / "evidence/source.pdf"):
            original = path.read_bytes()
            for missing in (False, True):
                with self.subTest(artifact=path.name, missing=missing):
                    try:
                        if missing:
                            path.unlink()
                        else:
                            path.write_bytes(b"changed proof or authoritative input")
                        self.assert_finalize_rejected_without_mutation()
                    finally:
                        path.write_bytes(original)

    def test_finalize_rejects_valid_but_changed_complete_content_and_context(self):
        self.author_pending_translation()
        for name, mutate in (
                ("book.json", lambda data: data["blocks"][0]["target"].append({"text": "Changed authoring."})),
                ("book.json", lambda data: data["agent_preface"].append({"text": "Changed preface."})),
                ("job.json", lambda data: data["layout"].update(inner_min_mm=21)),
                ("job.json", lambda data: data["models"]["translation"].update(provider="opencode-go", model="deepseek-v4-flash")),
                ("job.json", lambda data: data.update(title="Changed controller context")),
                ("job.json", lambda data: data["history"].append({"event": "intervening_event"})),
                ("terms.json", lambda data: data["terms"][0].update(target="Changed term"))):
            path = self.job / name
            original = path.read_bytes()
            with self.subTest(artifact=name, mutation=mutate):
                try:
                    data = core.load_json(path)
                    mutate(data)
                    core.save_json(path, data)
                    self.assert_finalize_rejected_without_mutation()
                finally:
                    path.write_bytes(original)
        assets = self.job / "assets"
        assets.mkdir(exist_ok=True)
        asset = assets / "unreferenced.txt"
        asset.write_text("Even unreferenced changed assets invalidate the content digest.")
        self.assert_finalize_rejected_without_mutation()

    def test_finalize_rejects_hand_staged_and_unjournaled_proof(self):
        self.author_and_checkpoint("terminology")
        self.author_fixture(self.job, "translation")
        fake_build(self.job)
        self.assert_finalize_rejected_without_mutation()
        event, _ = self.author_pending_translation()
        data = workflow.load_job(self.job)
        data["history"].pop()
        core.save_json(self.job / "job.json", data)
        self.assertTrue((self.job / event["receipt"]).is_file())
        self.assert_finalize_rejected_without_mutation()

    def test_finalize_rejects_wrong_state_round_exhausted_cap_and_replayed_proof(self):
        event, _ = self.author_pending_translation()
        original = (self.job / "job.json").read_bytes()
        for state, number, cap in (("source_ready", 0, 3), ("translated", 0, 3), ("approved", 0, 3),
                                   ("changes_requested", 0, 3), ("terminology_ready", 1, 3),
                                   ("terminology_ready", 1, 1), ("exhausted", 3, 3)):
            with self.subTest(state=state, round=number, cap=cap):
                data = json.loads(original)
                data.update(state=state, round=number, max_rounds=cap)
                core.save_json(self.job / "job.json", data)
                self.assert_finalize_rejected_without_mutation()
        (self.job / "job.json").write_bytes(original)
        workflow.finalize_translation(self.job)
        data = workflow.load_job(self.job)
        # A retained old proof cannot be reattached after its round was consumed.
        data.update(state="terminology_ready", round=0)
        data["history"].append(event)
        core.save_json(self.job / "job.json", data)
        self.assert_finalize_rejected_without_mutation()

    def test_finalize_from_changes_requested_preserves_old_review_and_consumes_one_round(self):
        self.translate()
        report = passing_review(self.job, 1)
        report.update(verdict="changes_requested", findings=[{"id": "Fix", "severity": "minor", "location": "Paragraph", "detail": "Synthetic revision."}])
        self.submit(report)
        old_review = (self.job / "reviews/round-1.receipt.json").read_bytes()
        event, proof = self.author_pending_translation()
        self.assertEqual((proof["base_state"], proof["base_round"]), ("changes_requested", 1))
        result = workflow.finalize_translation(self.job)
        self.assertEqual((result["state"], result["round"]), ("translated", 2))
        self.assertEqual((self.job / "reviews/round-1.receipt.json").read_bytes(), old_review)
        self.assertEqual(workflow.load_job(self.job)["history"][-2], event)
        self.submit(passing_review(self.job, 2))
        self.assertTrue(workflow.accept_job(self.job).is_file())

    def test_invalid_content_or_stale_context_never_creates_authoring_proof(self):
        self.author_and_checkpoint("terminology")
        for fault in ("book", "source", "handoff"):
            self.author_fixture(self.job, "translation")
            before = self.job_artifacts()
            if fault == "book":
                (self.job / "book.json").write_text("{}", encoding="utf-8")
            elif fault == "source":
                source = core.load_json(self.job / "book-source.json")
                source["blocks"][0]["source"].append({"text": "Unauthorized source mutation."})
                core.save_json(self.job / "book-source.json", source)
            else:
                (self.job / "handoff.md").write_text("Uncheckpointed terminology context", encoding="utf-8")
            task = save_task_result(self.root / "coordinator-results", "translation")
            with self.subTest(fault=fault), patch("render.build") as build:
                with self.assertRaises(ValueError):
                    workflow.checkpoint_role(self.job, "translation", task)
                build.assert_not_called()
                self.assertFalse(any(event.get("event") == "translation_content_authored" for event in workflow.load_job(self.job)["history"]))
            for name, content in before.items():
                (self.job / name).write_bytes(content)

    def test_no_unreviewed_revision(self):
        self.translate()
        with self.assertRaisesRegex(ValueError, "submit the current review"):
            self.author_and_checkpoint("translation")
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
            self.author_and_checkpoint("translation")
        with self.assertRaises(ValueError):
            workflow.accept_job(self.job)
        self.assertFalse((self.job / "output.pdf").exists())

    def test_review_round_mismatch_and_replay(self):
        self.translate()
        with self.assertRaises(ValueError):
            self.submit(passing_review(self.job, 2))
        data = workflow.load_job(self.job)
        self.assertEqual((data["state"], data["round"]), ("translated", 1))
        self.assertFalse((self.job / "reviews/round-1.receipt.json").exists())
        self.assertFalse((self.job / "output.pdf").exists())
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
        original = path.read_bytes()
        report = core.load_json(path)
        report["evidence"].append("Changed evidence after submission")
        core.save_json(path, report)
        with self.assertRaises(ValueError):
            workflow.accept_job(self.job)
        self.assertFalse((self.job / "output.pdf").exists())
        path.write_bytes(original)
        receipt = self.job / "reviews/round-1.receipt.json"
        receipt.write_text("{}", encoding="utf-8")
        with self.assertRaises(ValueError):
            workflow.accept_job(self.job)
        self.assertFalse((self.job / "output.pdf").exists())

    def test_changed_terminology_handoff_rejected(self):
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
        self.author_and_checkpoint("source", revise=True)
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

    

    def test_real_pdf_initial_lifecycle(self):
        import pymupdf as fitz
        source = self.root / "actual.pdf"
        with fitz.open() as document:
            page = document.new_page()
            page.insert_text((72, 72), "Network protocol.")
            document.save(source)
        job = self.root / "actual-job"
        workflow.init_job(source, job, "Actual extraction lifecycle", "en", "fr")
        for role in workflow.ROLES:
            workflow.configure_model(job, role, PROVIDER, MODEL)
        result = workflow.extract_job(job, ocr="auto")
        self.assertEqual(workflow.load_job(job)["state"], "extracted")
        self.assertEqual(result["input"]["sha256"], workflow.digest_file(source))
        book = source_book(result["pages"][0]["locator"])
        core.save_json(job / "book-source.json", book)
        self.author_and_checkpoint("source", job=job)
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
        self.author_and_checkpoint("source", revise=True)
        workflow.seal_job(self.job, reseal=True)
        self.translate()
        current = workflow.current_build(self.job)
        self.assertEqual(workflow.load_job(self.job)["round"], old_report["round"])
        self.assertNotEqual(old_report["content_digest"], current["content_digest"])
        self.assertNotEqual(old_report["pdf_sha256"], current["pdf_sha256"])
        with self.assertRaises(ValueError):
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
        for role in workflow.ROLES:
            workflow.configure_model(second, role, PROVIDER, MODEL)
        self.author_and_checkpoint("source", job=second)
        workflow.seal_job(second)
        self.author_and_checkpoint("terminology", job=second)
        self.author_and_checkpoint("translation", job=second)
        self.assertEqual(workflow.load_job(second)["round"], authored["round"])
        self.assertNotEqual(workflow.current_build(second)["content_digest"], authored["content_digest"])
        with self.assertRaises(ValueError):
            workflow.submit_review(second, report_path)
        self.assertFalse((second / "reviews/round-1.receipt.json").exists())

    def test_authored_pdf_identity_required_even_with_matching_content(self):
        self.translate()
        authored = passing_review(self.job, 1)
        authored["pdf_sha256"] = "0" * 64
        with self.assertRaises(ValueError):
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
        with redirect_stdout(capture):
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
        with self.assertRaises(ValueError):
            workflow.submit_review(self.job, path)
        self.assertEqual(workflow.load_job(self.job)["state"], "translated")
        self.assertFalse((self.job / "reviews/round-1.receipt.json").exists())

    def test_missing_pdf_recovery_uses_admitted_content_not_another_model_round(self):
        self.translate()
        original = workflow.current_build(self.job)
        (self.job / "build/book.pdf").unlink()
        with redirect_stdout(io.StringIO()):
            self.assertEqual(workflow.main(["build", str(self.job)]), 0)
        fresh = workflow.current_build(self.job)
        self.assertEqual(fresh["content_digest"], original["content_digest"])
        self.assertNotEqual(fresh["pdf_sha256"], original["pdf_sha256"])
        self.assertEqual(workflow.load_job(self.job)["round"], 1)
        self.submit(passing_review(self.job, 1))
        self.assertEqual(workflow.digest_file(workflow.accept_job(self.job)), fresh["pdf_sha256"])


    def test_source_seal_requires_complete_source_checkpoint(self):
        job = self.root / "unadmitted-source"
        workflow.init_job(self.source, job, "Unadmitted source", "en", "fr")
        for role in workflow.ROLES:
            workflow.configure_model(job, role, PROVIDER, MODEL)
        data = workflow.load_job(job)
        data["state"] = "extracted"
        core.save_json(job / "job.json", data)
        core.save_json(job / "book-source.json", source_book())
        before = {path.relative_to(job).as_posix(): path.read_bytes() for path in job.rglob("*") if path.is_file()}
        with self.assertRaises(ValueError):
            workflow.seal_job(job)
        self.assertFalse((job / "source.sha256").exists())
        self.assertEqual(before, {path.relative_to(job).as_posix(): path.read_bytes() for path in job.rglob("*") if path.is_file()})

    def test_review_submission_requires_complete_review_checkpoint(self):
        self.translate()
        report = self.job / "reviews/round-1.json"
        core.save_json(report, passing_review(self.job, 1))
        before = self.job_artifacts()
        with self.assertRaises(ValueError):
            workflow.submit_review(self.job, report)
        self.assertEqual(self.job_artifacts(), before)
        self.assertFalse((self.job / "output.pdf").exists())

    

    

    


    

    

    


    def test_source_checkpoint_remains_required_for_downstream_readiness_and_acceptance(self):
        for boundary in ("prepare", "accept"):
            if boundary == "accept":
                self.translate()
                self.submit(passing_review(self.job, 1))
            data = workflow.load_job(self.job)
            event = next(item for item in reversed(data["history"]) if item.get("event") == "role_source")
            path = self.job / event["receipt"]
            original = path.read_bytes()
            for missing in (False, True):
                with self.subTest(boundary=boundary, missing=missing):
                    try:
                        if missing:
                            path.unlink()
                        else:
                            path.write_bytes(original + b"\n")
                        before = self.job_artifacts()
                        with self.assertRaises(ValueError):
                            if boundary == "prepare":
                                workflow.role_readiness(self.job, "terminology")
                            else:
                                workflow.accept_job(self.job)
                        self.assertEqual(self.job_artifacts(), before)
                        self.assertFalse((self.job / "output.pdf").exists())
                    finally:
                        path.write_bytes(original)

    def test_identical_source_reinspection_preserves_round_cap_and_seal(self):
        self.translate()
        data = workflow.load_job(self.job)
        before = (data["state"], data["round"], data["max_rounds"])
        seal = (self.job / "source.sha256").read_bytes()
        build = workflow.current_build(self.job)
        self.author_and_checkpoint("source", revise=True)
        current = workflow.load_job(self.job)
        self.assertEqual((current["state"], current["round"], current["max_rounds"]), before)
        self.assertEqual((self.job / "source.sha256").read_bytes(), seal)
        self.assertEqual(workflow.current_build(self.job), build)
        with self.assertRaisesRegex(ValueError, "unchanged"):
            workflow.seal_job(self.job, reseal=True)
        self.assertEqual(workflow.load_job(self.job)["round"], data["round"])


@unittest.skipUnless(shutil.which("xelatex"), "real XeLaTeX required for standalone CLI recovery smoke")
class RealFinalizationCliTests(unittest.TestCase):
    def test_actual_cli_recovers_checkpointed_content_with_real_xelatex(self):
        import pymupdf
        with tempfile.TemporaryDirectory(prefix="synthetic-checkpoint-recovery-") as directory:
            root = Path(directory)
            source = root / "source.pdf"
            with pymupdf.open() as document:
                page = document.new_page()
                page.insert_text((72, 72), "Network protocol.")
                document.save(source)
            job = root / "job"
            home = root / "home"
            home.mkdir()
            environment = {"PATH": os.environ.get("PATH", os.defpath), "HOME": str(home), "PYTHONDONTWRITEBYTECODE": "1"}
    
            def cli(*arguments, success=True, environment=environment):
                result = subprocess.run([sys.executable, str(SCRIPTS / "translator.py"), *map(str, arguments)],
                                        env=environment, capture_output=True, text=True, timeout=120)
                self.assertEqual(result.returncode, 0 if success else 1, result.stdout + result.stderr)
                return json.loads(result.stdout) if success else result.stderr
    
            def checkpoint(role, *, environment=environment, success=True):
                if role == "source":
                    core.save_json(job / "book-source.json", source_book("source.pdf:1"))
                elif role == "terminology":
                    core.save_json(job / "terms.json", terms())
                    (job / "handoff.md").write_text("Clearly synthetic checkpoint fixture; no inference-quality claim.", encoding="utf-8")
                elif role == "translation":
                    book = core.load_json(job / "book-source.json")
                    book["blocks"][0]["target"] = [{"page": "P1"}, {"text": "Network "}, {"term": "Protocol"}, {"text": "."}]
                    book["agent_preface"] = [{"text": "Clearly synthetic recovery smoke, not a model translation. Real XeLaTeX verifies the PDF."}]
                    core.save_json(job / "book.json", book)
                else:
                    core.save_json(job / "reviews/round-1.json", passing_review(job, 1))
                task = save_task_result(root / "coordinator-results", role)
                return cli("checkpoint-role", job, role, "--task-result", task, environment=environment, success=success)
    
            cli("init", source, job, "--source-language", "en", "--target-language", "zh-Hans")
            for role in workflow.ROLES:
                cli("configure-model", job, role, "--provider", PROVIDER, "--model", MODEL)
            data = workflow.load_job(job)
            data["state"] = "extracted"
            core.save_json(job / "job.json", data)
            checkpoint("source")
            cli("seal-source", job)
            checkpoint("terminology")
            unavailable = root / "compiler-outage"
            unavailable.mkdir()
            compiler = unavailable / "xelatex"
            compiler.write_text("#!/bin/sh\necho 'Synthetic compiler outage after checkpointed authoring'\nexit 1\n", encoding="utf-8")
            compiler.chmod(0o755)
            failed_environment = {**environment, "PATH": str(unavailable) + os.pathsep + environment["PATH"]}
            error = checkpoint("translation", success=False, environment=failed_environment)
            self.assertIn("XeLaTeX compilation failed", error)
            pending = workflow.load_job(job)
            self.assertEqual((pending["state"], pending["round"]), ("terminology_ready", 0))
            event = pending["history"][-1]
            proof_path = job / event["receipt"]
            proof_bytes = proof_path.read_bytes()
            proof = workflow.translation_authoring_proof(job, pending, event)
            self.assertTrue(proof["authoring_complete"])
            task_inputs = {path.name: path.read_bytes() for path in (root / "coordinator-results").glob("*.json")}
            self.assertEqual(len(task_inputs), 3)
            cli("accept", job, success=False)
            completed = cli("finalize-translation", job)
            self.assertEqual((completed["state"], completed["round"]), ("translated", 1))
            self.assertEqual(proof_path.read_bytes(), proof_bytes)
            self.assertEqual({path.name: path.read_bytes() for path in (root / "coordinator-results").glob("*.json")}, task_inputs)
            verification = core.load_json(job / "build/verification.json")
            self.assertTrue(verification["passed"])
            self.assertTrue(all(verification["checks"][name] for name in workflow.BUILD_CHECKS))
            self.assertIn("XeTeX", (job / "build/compiler.log").read_text())
            with pymupdf.open(job / "build/book.pdf") as document:
                self.assertGreaterEqual(len(document), 2)
                self.assertAlmostEqual(document[0].rect.width, 148 * 72 / 25.4, delta=0.2)
                text = "".join(page.get_text() for page in document)
                self.assertIn("Network", text)
                self.assertIn("Clearly synthetic recovery smoke", text)
            self.assertFalse((job / "output.pdf").exists())
            snapshot = (job / "job.json").read_bytes()
            cli("finalize-translation", job, success=False)
            self.assertEqual((job / "job.json").read_bytes(), snapshot)
            checkpoint("review")
            cli("review", job, job / "reviews/round-1.json")
            cli("accept", job)
            self.assertEqual(workflow.digest_file(job / "output.pdf"), workflow.current_build(job)["pdf_sha256"])


if __name__ == "__main__":
    unittest.main()
