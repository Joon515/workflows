"""Domain checkpoint/state tests; task metadata fixtures never claim real inference."""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
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





class DoctorPrerequisiteTests(unittest.TestCase):
    def doctor_with_missing(self, missing=None):
        def probe(arguments, **kwargs):
            available = arguments[1] != missing
            return subprocess.CompletedProcess(arguments, 0 if available else 1,
                                               stdout="/test/tex/" + arguments[1] if available else "")

        with patch("extract.doctor", return_value={"pymupdf": {"available": True}}), \
             patch.object(workflow.shutil, "which", side_effect=lambda name: "/test/bin/" + name if name in {"xelatex", "kpsewhich"} else None), \
             patch.object(workflow.subprocess, "run", side_effect=probe):
            return workflow.doctor()

    def test_doctor_blocks_each_missing_body_font_prerequisite(self):
        self.assertTrue(self.doctor_with_missing()["render"]["ready"])
        for missing in ("ucharclasses.sty", "JuliaMono-Regular.ttf", "JuliaMono-Bold.ttf",
                        "JuliaMono-RegularItalic.ttf", "JuliaMono-BoldItalic.ttf"):
            with self.subTest(resource=missing):
                report = self.doctor_with_missing(missing)
                resources = {**report["render"]["packages"], **report["render"]["fonts"]}
                self.assertFalse(report["render"]["ready"])
                self.assertIsNone(resources[missing])
                self.assertTrue(all(value for name, value in resources.items() if name != missing))

    def test_doctor_blocks_missing_roman_text_and_optical_math_faces(self):
        self.assertTrue(self.doctor_with_missing()["render"]["ready"])
        # Exercise body styles and distinct math-alphabet optical selections, not a resource-list snapshot.
        for missing in ("FreeSerif.otf", "FreeSerifBold.otf", "FreeSerifItalic.otf", "FreeSerifBoldItalic.otf",
                        "lmroman5-regular.otf", "lmroman17-regular.otf", "lmroman12-bold.otf",
                        "lmroman7-italic.otf", "lmroman10-bolditalic.otf"):
            with self.subTest(resource=missing):
                report = self.doctor_with_missing(missing)
                self.assertFalse(report["render"]["ready"])
                self.assertIsNone(report["render"]["fonts"][missing])
                self.assertTrue(all(value for name, value in report["render"]["fonts"].items() if name != missing))


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

    def test_positive_round_reseal_refuses_reset_and_preserves_release_history_and_files(self):
        self.translate()
        self.submit(passing_review(self.job, 1))
        workflow.accept_job(self.job)
        unrelated = self.job / "build/user-notes.txt"
        unrelated.write_text("User-owned notes", encoding="utf-8")
        book = core.load_json(self.job / "book-source.json")
        book["blocks"][0]["source"].append({"text": "Explicit source correction."})
        core.save_json(self.job / "book-source.json", book)
        with self.assertRaises(ValueError):
            workflow.seal_job(self.job)
        task = save_task_result(self.root / "coordinator-results", "source")
        before = self.job_artifacts()
        with self.assertRaises(ValueError):
            workflow.checkpoint_role(self.job, "source", task, revise=True)
        self.assertEqual(self.job_artifacts(), before)
        with self.assertRaises(ValueError):
            workflow.seal_job(self.job, reseal=True)
        self.assertEqual(self.job_artifacts(), before)
        self.assertEqual((workflow.load_job(self.job)["state"], workflow.load_job(self.job)["round"]), ("approved", 1))
        self.assertEqual(unrelated.read_text(encoding="utf-8"), "User-owned notes")
        self.assertTrue((self.job / "reviews/round-1.receipt.json").is_file())
        self.assertFalse((self.job / "reviews/archive").exists())

    def test_round_zero_reseal_invalidates_downstream_but_retains_unrelated_files_and_history(self):
        self.author_and_checkpoint("terminology")
        unrelated = self.job / "build/user-notes.txt"
        unrelated.parent.mkdir(exist_ok=True)
        unrelated.write_text("User-owned notes", encoding="utf-8")
        (self.job / "output.pdf").write_bytes(b"Unreleased fixture")
        (self.job / "build/verification.json").write_bytes(b"Stale fixture")
        book = core.load_json(self.job / "book-source.json")
        book["blocks"][0]["source"].append({"text": "Explicit initial source correction."})
        core.save_json(self.job / "book-source.json", book)
        self.author_and_checkpoint("source", revise=True)
        before = workflow.load_job(self.job)
        workflow.seal_job(self.job, reseal=True)
        after = workflow.load_job(self.job)
        self.assertEqual((after["state"], after["round"], after["max_rounds"]), ("source_ready", 0, 3))
        self.assertEqual(after["history"][:-1], before["history"])
        self.assertEqual(unrelated.read_text(encoding="utf-8"), "User-owned notes")
        self.assertFalse((self.job / "output.pdf").exists())
        self.assertFalse((self.job / "build/verification.json").exists())

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


    def test_unsubmitted_review_does_not_authorize_positive_round_source_reset(self):
        self.translate()
        old_report = passing_review(self.job, 1)
        old_path = self.root / "authored-old-report.json"
        core.save_json(old_path, old_report)
        source = core.load_json(self.job / "book-source.json")
        source["blocks"][0]["source"].append({"text": "A reviewed source correction changes the manuscript."})
        core.save_json(self.job / "book-source.json", source)
        task = save_task_result(self.root / "coordinator-results", "source")
        before = self.job_artifacts()
        with self.assertRaises(ValueError):
            workflow.checkpoint_role(self.job, "source", task, revise=True)
        self.assertEqual(self.job_artifacts(), before)
        with self.assertRaises(ValueError):
            workflow.seal_job(self.job, reseal=True)
        self.assertEqual(self.job_artifacts(), before)
        self.assertEqual((workflow.load_job(self.job)["state"], workflow.load_job(self.job)["round"]), ("translated", 1))
        self.assertEqual(core.load_json(old_path), old_report)
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

    def test_noop_positive_round_source_reinspection_refuses_without_changing_budget_or_seal(self):
        self.translate()
        data = workflow.load_job(self.job)
        before = (data["state"], data["round"], data["max_rounds"])
        seal = (self.job / "source.sha256").read_bytes()
        build = workflow.current_build(self.job)
        self.assert_stage_rejected_without_mutation("source", revise=True)
        current = workflow.load_job(self.job)
        self.assertEqual((current["state"], current["round"], current["max_rounds"]), before)
        self.assertEqual((self.job / "source.sha256").read_bytes(), seal)
        self.assertEqual(workflow.current_build(self.job), build)
        with self.assertRaisesRegex(ValueError, "unchanged"):
            workflow.seal_job(self.job, reseal=True)
        self.assertEqual(workflow.load_job(self.job)["round"], data["round"])

class PostReviewSourceRecoveryControllerTests(unittest.TestCase):
    """Public lifecycle proofs with synthetic native data, not rendering/inference evidence."""

    def setUp(self):
        import pymupdf
        import units
        self.units = units
        temporary = tempfile.TemporaryDirectory(prefix="post-review-controller-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        from PIL import Image, ImageDraw
        self.math_png = self.root / "synthetic-equation.png"
        raster = Image.new("RGB", (200, 60), "white")
        drawing = ImageDraw.Draw(raster)
        drawing.text((5, 22), "stray", fill="black")
        drawing.text((100, 22), "x = 1", fill="black")
        raster.save(self.math_png)
        original = self.root / "source.pdf"
        with pymupdf.open() as document:
            for number in (1, 2, 3):
                page = document.new_page()
                text = ("Original structural correction fixture paragraph 1: deve[gap]pment" if number == 1
                        else f"Original structural correction fixture paragraph {number}.")
                page.insert_text((60, 60), text)
                if number == 1:
                    page.insert_image(pymupdf.Rect(60, 90, 260, 150), filename=str(self.math_png))
            document.save(original)
        self.job = self.root / "job"
        workflow.init_job(original, self.job, "Post-review controller fixture", "en", "en")
        for role in workflow.ROLES:
            workflow.configure_model(self.job, role, PROVIDER, MODEL)
        workflow.extract_job(self.job, ocr="never", dpi=72)
        (self.job / ".controller.lock").touch()
        self.build_patch = patch("render.build", side_effect=self.synthetic_build)
        self.build_patch.start()
        self.addCleanup(self.build_patch.stop)
        self.plan("source")
        self.complete_units("source")
        workflow.assemble_units(self.job, "source")
        workflow.seal_job(self.job)
        core.save_json(self.job / "terms.json", {"version": 1, "terms": [
            {"id": "Structure", "number": 1, "source": "structural", "target": "structural",
             "authority": "Synthetic terminology decision", "authority_locator": "Fixture source paragraphs",
             "rationale": "Controller regression only, not external terminological authority.", "protected_ids": []}]})
        (self.job / "handoff.md").write_text("Synthetic native terminology fixture: structural is governed consistently.\n", encoding="utf-8")
        self.initial_term_task = self.task("terminology")
        workflow.checkpoint_role(self.job, "terminology", self.initial_term_task)

    def task(self, role):
        return save_task_result(self.root / "coordinator-results", role)

    def files(self):
        return {path.relative_to(self.job).as_posix(): path.read_bytes()
                for path in self.job.rglob("*") if path.is_file()}

    def cli(self, *arguments, success=True):
        capture, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(capture), redirect_stderr(errors):
            try:
                code = workflow.main([str(value) for value in arguments])
            except SystemExit as error:
                code = error.code
        if success:
            self.assertEqual(code, 0, errors.getvalue())
            return json.loads(capture.getvalue())
        self.assertNotEqual(code, 0, capture.getvalue())

    def artifact_tree(self):
        return self.files(), sorted(path.relative_to(self.job).as_posix()
                                    for path in self.job.rglob("*") if path.is_dir())

    def refuse(self, callback):
        before = self.artifact_tree()
        with self.assertRaises((ValueError, OSError, RuntimeError)):
            callback()
        self.assertEqual(self.artifact_tree(), before)

    def refuse_cli(self, *arguments):
        before = self.artifact_tree()
        self.cli(*arguments, success=False)
        self.assertEqual(self.artifact_tree(), before)

    def plan(self, role, **options):
        reference = workflow.plan_units(self.job, role, 1, **options)
        return core.load_json(self.job / reference["plan"])

    def complete_units(self, role, *, source_revision=None, failed_review=False, checkpoint=True):
        bindings = []
        for identifier in self.units.status(self.job, role)["pending"]:
            binding = self.units.unit_binding(self.job, role, identifier)
            packet = core.load_json(self.job / binding["packet"])
            output = {
                "version": 1, "kind": role + "-unit-result", "unit_id": identifier,
                "packet_sha256": binding["packet_sha256"],
                "inspection": [
                    {"page_id": page["page_id"], "image_sha256": page["image_sha256"],
                     "findings": [], "protected_checked": True,
                     "regions": [{"index": index, "classification": "nonprose"}
                                 for index in range(page["raster_region_count"])]}
                    for page in packet["pages"] if page["page_id"] in packet["owned_pages"]],
            }
            if role == "source":
                output.update(
                    source_pages=[{"id": page["page_id"], "locator": page["locator"], "printed_label": None,
                                   "label_verified": False, "evidence": "Synthetic source inspection declaration."}
                                  for page in packet["pages"] if page["page_id"] in packet["owned_pages"]],
                    blocks=copy.deepcopy(packet["blocks"]), notes=copy.deepcopy(packet["notes"]),
                    protected=copy.deepcopy(packet["protected"]))
                # Author full owned fixture results from old packets, not expected_source.
                if source_revision is None and identifier == "u0001":
                    asset = self.job / binding["assets_dir"] / "equation.png"
                    asset.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(self.math_png, asset)
                    output["blocks"] = [block for block in output["blocks"] if block["kind"] != "image"]
                    output["blocks"].append({
                        "id": "u0001_equation", "kind": "image", "source_pages": packet["owned_pages"],
                        "source": [], "target": [], "asset": asset.relative_to(self.job).as_posix(),
                        "width": 200, "height": 60, "source_em": 12,
                        "scale_evidence": "Synthetic original fixture: 200 pixels span 200 source points at 12pt em."})
                elif source_revision == "list":
                    output["blocks"][0].update(kind="list_item", label="1.", list_type="ordered", list_level=0)
                elif source_revision == "page":
                    output["source_pages"][0].update(printed_label="iv", label_verified=True,
                                                      evidence="Synthetic Roman folio independently inspected.")
                elif source_revision in {"mixed", "mixed-confirmed"}:
                    confirmed = source_revision == "mixed-confirmed"
                    page = packet["owned_pages"][0]
                    output["source_pages"][0].update(printed_label="iv", label_verified=True,
                                                      evidence="Synthetic Roman folio independently inspected.")
                    output["blocks"][0]["source"] = [
                        {"page": page}, {"text": "Original structural correction fixture paragraph 1: development"},
                        {"note": "u0001_repair"}, {"text": "; example "}, {"protected": "u0001_math"}]
                    graphic = next(block for block in output["blocks"] if block["id"] == "u0001_equation")
                    graphic.update(asset="work/prepared-equation.png", width=80)
                    output["protected"].append({"id": "u0001_math", "kind": "math", "value": "x = 1"})
                    output["notes"].append({
                        "id": "u0001_repair", "content_type": "prose", "target": [],
                        "source": [{"text": "Synthetic fixture-author confirmation of intended word: development. Original fragment: "
                                   if confirmed else "Synthetic contextual conjecture, not recovered ink: development. Original fragment: "},
                                   {"text": "deve[gap]pment"}, {"text": ". Original damage: "},
                                   {"image": {"asset": "work/prepared-damage.png", "width_em": 9.25, "height_em": .5, "raise_em": 0}}],
                        "restoration": {"source_page": page, "original_fragment": "deve[gap]pment", "replacement": "development",
                                        "status": "confirmed" if confirmed else "conjectural",
                                        "evidence": "Synthetic fixture author confirms intended development; no external manuscript or scientific claim."
                                        if confirmed else "Synthetic authored gap and contextual witness; no recovered-ink or scientific claim.",
                                        "damage_asset": "work/prepared-damage.png"},
                        "source_evidence": [{"asset": "work/prepared-damage.png", "source_page": page,
                                             "description": "Synthetic original page text rectangle [60,45,430,65]."}]})
                if packet["metadata_owner"]:
                    output["metadata"] = {key: value for key, value in packet["metadata"].items() if value is not None}
                    if packet["metadata"]["main_body_start"] is None:
                        output["body_start"] = output["blocks"][0]["id"]
            elif role == "translation":
                for category in ("blocks", "notes"):
                    output[category] = [{"id": item["id"], "target": copy.deepcopy(item["source"])}
                                        for item in packet[category]]
                    for item in output[category]:
                        governed = []
                        for token in item["target"]:
                            if "structural" in token.get("text", ""):
                                before, after = token["text"].split("structural", 1)
                                governed.extend([{"text": before}, {"term": "Structure"}, {"text": after}])
                            else:
                                governed.append(token)
                        item["target"] = governed
                if packet["metadata_owner"]:
                    output["metadata"] = {"title": "Synthetic current target", "human_preface": None,
                                          "agent_preface": [{"text": "Synthetic controller data; no model quality claim."}]}
            else:
                output.update(
                    pdf_inspection=[{"page": page, "evidence": "Synthetic PDF inspection declaration."}
                                    for page in packet["pdf_pages"]],
                    checks={name: True for name in workflow.REVIEW_CHECKS},
                    verdict="changes_requested" if failed_review else "pass", findings=[],
                    evidence=["Synthetic native review fixture, not visual quality evidence."])
                if failed_review:
                    output["checks"]["coverage"] = False
                    output["findings"] = [{"id": identifier + "_fix", "severity": "minor",
                                           "location": "Synthetic source scope", "detail": "Correct structural source data."}]
            core.save_json(self.job / binding["result"], output)
            bindings.append(binding)
            if checkpoint:
                workflow.checkpoint_unit(self.job, role, identifier, self.task(role))
        return bindings

    def synthetic_build(self, job):
        """Native-controller state proof only; never a glyph or renderer assertion."""
        import pymupdf
        book = core.validate_book(job, translated=True)
        build = job / "build"
        build.mkdir(exist_ok=True)
        pdf = build / "book.pdf"
        with pymupdf.open() as document:
            for number in (1, 2):
                page = document.new_page()
                page.insert_text((60, 60), f"Synthetic controller build {next(FAKE_BUILD_SEQUENCE)} page {number}.")
            document.save(pdf)
        core.save_json(build / "verification.json", {
            "version": 1, "content_digest": core.content_digest(job), "pdf_sha256": workflow.digest_file(pdf),
            "passed": True, "checks": {name: True for name in workflow.BUILD_CHECKS},
            "pages": [{"physical_pdf_page": number} for number in (1, 2)],
            "block_boundaries": [{"id": block["id"], "start": {"page": min(index + 1, 2)},
                                  "end": {"page": min(index + 1, 2)}}
                                 for index, block in enumerate(book["blocks"])],
            "notes": [], "agent_preface_pages": [1]})
        (build / "book.tex").write_text("Synthetic generated build evidence.\n", encoding="utf-8")
        (build / "nested").mkdir(exist_ok=True)
        (build / "nested/layout.dat").write_bytes(b"Synthetic nested layout evidence")
        return pdf

    def reviewed_job(self, *, failed_review=True, submit=True):
        self.original_target_plan = self.plan("translation")
        self.complete_units("translation")
        workflow.assemble_units(self.job, "translation")
        self.original_review_plan = self.plan("review")
        self.complete_units("review", failed_review=failed_review)
        workflow.assemble_units(self.job, "review")
        if submit:
            workflow.submit_review(self.job, self.job / "reviews/round-1.json")
        self.original_job = workflow.load_job(self.job)
        self.original_files = self.files()
        self.expected = core.load_json(self.job / "book-source.json")
        block = self.expected["blocks"][0]
        block.update(kind="list_item", label="1.", list_type="ordered", list_level=0)
        self.scope = self.job / "work/recovery-scope.json"
        proposal = self.job / "work/expected-source.json"
        core.save_json(proposal, self.expected)
        submitted = "reviews/round-1.receipt.json" if submit else "reviews/round-1.json"
        self.request = {"version": 2, "kind": "post-review-source-scope",
                        "submitted_review": {"path": submitted, "sha256": workflow.digest_file(self.job / submitted)},
                        "expected_source": {"path": "work/expected-source.json", "sha256": workflow.digest_file(proposal)},
                        "source_changes": {"block_fields": {block["id"]: ["kind", "label", "list_type", "list_level"]},
                                           "deleted_blocks": [], "block_orders": [], "page_fields": {},
                                           "added_protected": [], "removed_protected_ids": [],
                                           "added_notes": [], "crop_derivations": []}}
        self.source_revision = "list"
        core.save_json(self.scope, self.request)

    def admission_arguments(self):
        return ["plan-units", self.job, "source", "--pages-per-unit", "1", "--revise", "--reopen", "u0001",
                "--post-review-scope", self.scope]

    def admit_and_reseal(self):
        reference = self.cli(*self.admission_arguments())
        self.revision_path = self.job / reference["plan"]
        self.revision = core.load_json(self.revision_path)
        self.base_reference = self.revision["source_revision"]["base"]
        self.base = core.load_json(self.job / self.base_reference["path"])
        self.complete_units("source", source_revision=self.source_revision)
        self.cli("assemble-units", self.job, "source")
        self.assertEqual(core.load_json(self.job / "book-source.json"), self.expected)
        self.assertEqual((workflow.load_job(self.job)["state"], workflow.load_job(self.job)["round"]), ("changes_requested", 1))
        self.cli("seal-source", self.job, "--reseal")
        self.assertEqual((workflow.load_job(self.job)["state"], workflow.load_job(self.job)["round"]), ("source_ready", 1))

    def fresh_terminology(self):
        (self.job / "handoff.md").write_text(
            f"Synthetic native terminology reinspection of {len(self.expected['blocks'])} current source blocks.\n"
            "The unchanged complete terms table, target language, genre, domain, protected names, register, "
            "numbering and formatting policy remain compatible; this declaration is not semantic proof.\n", encoding="utf-8")
        result = self.cli("checkpoint-role", self.job, "terminology", "--task-result", self.task("terminology"))
        self.assertEqual((result["state"], result["round"]), ("changes_requested", 1))
        self.new_term_event = workflow.load_job(self.job)["history"][-1]
        return result

    def rebase(self):
        return self.plan("translation", rebase_source=self.revision_path,
                         accept_policy_compatibility=workflow.digest_file(self.job / "handoff.md"))

    def refuse_admission(self, *, reopen_units=None):
        selected = ["u0001"] if reopen_units is None else reopen_units
        self.refuse_cli("plan-units", self.job, "source", "--pages-per-unit", "1", "--revise",
                        "--reopen", *selected, "--post-review-scope", self.scope)
        self.refuse(lambda: self.units.create_plan(
            self.job, "source", pages_per_unit=1, revise=True, reopen_units=selected, post_review_scope=self.scope))

    def save_proposal(self):
        proposal = self.job / self.request["expected_source"]["path"]
        core.save_json(proposal, self.expected)
        self.request["expected_source"]["sha256"] = workflow.digest_file(proposal)
        core.save_json(self.scope, self.request)

    def page_only_proposal(self):
        self.expected = core.load_json(self.job / "book-source.json")
        page = self.expected["source_pages"][0]
        page.update(printed_label="iv", label_verified=True,
                    evidence="Synthetic Roman folio independently inspected.")
        changes = self.request["source_changes"]
        changes["block_fields"] = {}
        changes["page_fields"] = {page["id"]: ["printed_label", "label_verified", "evidence"]}
        self.source_revision = "page"
        self.save_proposal()

    def prepare_crop(self, input_name, rect, output_name, origin, use):
        from PIL import Image
        output = self.job / output_name
        output.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(self.job / input_name) as image:
            width, height, mode = image.width, image.height, image.mode
            image.crop(rect).save(output, format="PNG")
        return {"unit_id": "u0001", "origin": origin, "use": use,
                "input": {"ref": {"path": input_name, "sha256": workflow.digest_file(self.job / input_name)},
                          "width_px": width, "height_px": height, "mode": mode},
                "rect_px": list(rect),
                "output": {"ref": {"path": output_name, "sha256": workflow.digest_file(output)},
                           "width_px": rect[2] - rect[0], "height_px": rect[3] - rect[1], "mode": mode}}

    def mixed_proposal(self):
        self.page_only_proposal()
        first = self.expected["blocks"][0]
        page = first["source_pages"][0]
        art = next(block for block in self.expected["blocks"] if block["id"] == "u0001_equation")
        self.math_candidate = "work/prepared-equation.png"
        math = self.prepare_crop(art["asset"], (80, 0, 160, 60), self.math_candidate,
                                 {"kind": "source-asset", "block_id": art["id"]},
                                 {"kind": "image-block", "block_id": art["id"]})
        pointer = core.load_json(self.job / "units/source/active.json")
        plan = core.load_json(self.job / pointer["plan"])
        packet = core.load_json(self.job / plan["units"][0]["packet"])
        original = next(item for item in packet["pages"] if item["page_id"] == page)
        self.damage_candidate = "work/prepared-damage.png"
        damage = self.prepare_crop(original["image"], (60, 45, 430, 65), self.damage_candidate,
                                   {"kind": "original-page", "page_id": page},
                                   {"kind": "restoration-note", "note_id": "u0001_repair",
                                    "callout_block_id": first["id"], "source_page": page})
        art.update(asset=self.math_candidate, width=80)
        first["source"] = [{"page": page}, {"text": "Original structural correction fixture paragraph 1: development"},
                           {"note": "u0001_repair"}, {"text": "; example "}, {"protected": "u0001_math"}]
        self.expected["protected"].append({"id": "u0001_math", "kind": "math", "value": "x = 1"})
        self.expected["notes"].append({
            "id": "u0001_repair", "content_type": "prose", "target": [],
            "source": [{"text": "Synthetic contextual conjecture, not recovered ink: development. Original fragment: "},
                       {"text": "deve[gap]pment"}, {"text": ". Original damage: "},
                       {"image": {"asset": self.damage_candidate, "width_em": 9.25, "height_em": .5, "raise_em": 0}}],
            "restoration": {"source_page": page, "original_fragment": "deve[gap]pment", "replacement": "development",
                            "status": "conjectural", "evidence": "Synthetic authored gap and contextual witness; no recovered-ink or scientific claim.",
                            "damage_asset": self.damage_candidate},
            "source_evidence": [{"asset": self.damage_candidate, "source_page": page,
                                 "description": "Synthetic original page text rectangle [60,45,430,65]."}]})
        witness = self.job / "work/restoration-witness.txt"
        witness.write_text("Synthetic contextual witness: development; the literal [gap] is deliberate, not recovered ink.\n", encoding="utf-8")
        changes = self.request["source_changes"]
        changes["block_fields"] = {first["id"]: ["source"], art["id"]: ["asset", "width"]}
        changes["added_protected"] = [{"id": "u0001_math", "unit_id": "u0001", "witnesses": []}]
        changes["added_notes"] = [{"id": "u0001_repair", "unit_id": "u0001", "callout_block_id": first["id"],
                                   "witnesses": [{"path": witness.relative_to(self.job).as_posix(),
                                                  "sha256": workflow.digest_file(witness)}]}]
        changes["crop_derivations"] = [math, damage]
        self.source_revision = "mixed"
        self.save_proposal()

    @unittest.skipUnless(shutil.which("xelatex"), "real XeLaTeX required for page-only recovery lifecycle")
    def test_page_only_scope_has_no_dummy_block_edit_and_preserves_failed_unchanged_targets(self):
        self.build_patch.stop()
        self.reviewed_job()
        self.page_only_proposal()
        self.admit_and_reseal()
        self.fresh_terminology()
        self.refuse(lambda: self.plan("translation", rebase_source=self.revision_path,
                                      accept_policy_compatibility="0" * 64))
        plan = self.rebase()
        # Owner 3 has unchanged owned AND readonly context; its failed review still excludes carry.
        bridge = plan["source_rebase"]
        self.assertEqual(bridge["carried"], {})
        unchanged = bridge["footprints"]["u0003"]
        self.assertEqual(unchanged["before"], unchanged["after"])
        self.assertEqual(unchanged["decision"], "pending")
        self.assertIn("u0003", unchanged["review_exclusions"])
        self.assertEqual(self.units.status(self.job, "translation")["pending"],
                         [spec["unit_id"] for spec in self.original_target_plan["units"]])
        self.complete_units("translation")
        result = workflow.assemble_units(self.job, "translation")
        self.assertEqual((result["state"], result["round"], workflow.load_job(self.job)["max_rounds"]), ("translated", 2, 3))
        verification = core.load_json(self.job / "build/verification.json")
        self.assertTrue(verification["passed"])
        self.assertTrue(all(verification["checks"][name] for name in workflow.BUILD_CHECKS))
        self.refuse_cli("review", self.job, self.job / "reviews/round-1.json")
        self.refuse_cli("accept", self.job)

    def test_submitted_authority_and_native_members_are_required_before_any_planning_write(self):
        self.reviewed_job()
        review_pointer = core.load_json(self.job / "units/review/active.json")
        review = core.load_json(self.job / review_pointer["plan"])
        target_pointer = core.load_json(self.job / "units/translation/active.json")
        target = core.load_json(self.job / target_pointer["plan"])
        cases = []
        data = workflow.load_job(self.job)
        unsubmitted = copy.deepcopy(data)
        unsubmitted["history"] = [event for event in data["history"] if event["event"] != "review_submitted"]
        cases.append(("unsubmitted", "job.json", unsubmitted))
        unconsumed = copy.deepcopy(data)
        unconsumed["history"] = [event for event in data["history"] if event["event"] != "translation_content_authored"]
        cases.append(("missing-complete-target-authoring-consumption", "job.json", unconsumed))
        for name, changes in (("pass", {"state": "approved"}), ("cap", {"max_rounds": 1}),
                              ("stale-round", {"round": 2})):
            cases.append((name, "job.json", {**data, **changes}))
        for role in workflow.ROLES:
            changed = copy.deepcopy(data)
            changed["models"][role]["model"] = "changed-exact-selected-model"
            cases.append(("model-" + role, "job.json", changed))
        cases.extend([
            ("partial-review", review["units"][-1]["checkpoint"], None),
            ("missing-review-origin", review["units"][0]["result"], None),
            ("partial-target", target["units"][-1]["checkpoint"], None),
            ("unconsumed-target", "units/translation/active.json", {"plan": "absent.json", "plan_sha256": "0" * 64}),
            ("changed-build-digest", "book.json", {**core.load_json(self.job / "book.json"), "title": "Changed current target"}),
            ("changed-PDF", "build/book.pdf", b"%PDF changed bytes"),
            ("changed-verifier", "build/verification.json", {"passed": True}),
            ("stale-submission", "reviews/round-1.receipt.json", {"round": 1}),
        ])
        for label, name, replacement in cases:
            with self.subTest(case=label):
                path = self.job / name
                before = path.read_bytes()
                try:
                    if replacement is None:
                        path.unlink()
                    elif isinstance(replacement, bytes):
                        path.write_bytes(replacement)
                    else:
                        core.save_json(path, replacement)
                    self.refuse_admission()
                finally:
                    path.write_bytes(before)

    def test_exact_v2_page_note_definition_crop_and_natural_owner_authority_is_closed(self):
        self.reviewed_job()
        self.mixed_proposal()
        original_request = copy.deepcopy(self.request)
        for category in ("page_fields", "added_notes", "added_protected", "crop_derivations"):
            with self.subTest(undeclared=category):
                changed = copy.deepcopy(original_request)
                changed["source_changes"][category] = {} if category == "page_fields" else []
                core.save_json(self.scope, changed)
                self.refuse_admission()
        for version in (1, True, 3):
            with self.subTest(version=version):
                core.save_json(self.scope, {**original_request, "version": version})
                self.refuse_admission()
        for category in ("added_notes", "added_protected", "crop_derivations"):
            with self.subTest(foreign_owner=category):
                changed = copy.deepcopy(original_request)
                changed["source_changes"][category][0]["unit_id"] = "u0002"
                core.save_json(self.scope, changed)
                self.refuse_admission()
        core.save_json(self.scope, original_request)
        self.refuse_admission(reopen_units=["u0002"])
        extra = copy.deepcopy(original_request)
        first = next(iter(extra["source_changes"]["block_fields"]))
        extra["source_changes"]["block_fields"][first].append("kind")
        core.save_json(self.scope, extra)
        self.refuse_admission()
        missing = copy.deepcopy(original_request)
        del missing["source_changes"]["removed_protected_ids"]
        core.save_json(self.scope, missing)
        self.refuse_admission()
        self.scope.write_text('{"version": 2, ' + json.dumps(original_request)[1:], encoding="utf-8")
        self.refuse_admission()
        before_expected = copy.deepcopy(self.expected)
        self.expected["source_pages"][1]["evidence"] = "Undeclared edit in another explicitly selected full owner."
        self.save_proposal()
        self.refuse_admission(reopen_units=["u0001", "u0002"])
        self.expected = before_expected
        self.request = original_request
        self.save_proposal()

    def test_full_native_pass_is_not_source_authority(self):
        self.reviewed_job(failed_review=False)
        self.assertEqual(workflow.load_job(self.job)["state"], "approved")
        self.refuse_admission()

    def test_unsubmitted_complete_native_failure_is_not_source_authority(self):
        self.reviewed_job(submit=False)
        self.assertEqual(workflow.load_job(self.job)["state"], "translated")
        self.refuse_admission()

    def test_independent_full_source_disagreement_cannot_publish_the_proposal(self):
        self.reviewed_job()
        self.page_only_proposal()
        self.cli(*self.admission_arguments())
        self.complete_units("source", source_revision="list")
        self.refuse_cli("assemble-units", self.job, "source")
        self.assertEqual((self.job / "book-source.json").read_bytes(), self.original_files["book-source.json"])
        self.assertEqual((self.job / "source.sha256").read_bytes(), self.original_files["source.sha256"])

    def test_confirmed_restoration_retains_ordinary_core_status_at_controller_boundary(self):
        # A synthetic fixture-author witness is not a scientific/manuscript-truth oracle.
        self.reviewed_job()
        self.mixed_proposal()
        note = self.expected["notes"][0]
        note["source"][0]["text"] = "Synthetic fixture-author confirmation of intended word: development. Original fragment: "
        note["restoration"].update(
            status="confirmed", evidence="Synthetic fixture author confirms intended development; no external manuscript or scientific claim.")
        witness = self.job / "work/restoration-witness.txt"
        witness.write_text("Synthetic fixture author confirms the intended word development; [gap] was deliberately authored.\n", encoding="utf-8")
        self.request["source_changes"]["added_notes"][0]["witnesses"][0]["sha256"] = workflow.digest_file(witness)
        self.source_revision = "mixed-confirmed"
        self.save_proposal()
        self.admit_and_reseal()
        core.validate_book(self.job, translated=False)
        self.refuse_cli("review", self.job, self.job / "reviews/round-1.json")

    def test_selected_source_checkpoint_requires_full_inspection_and_pinned_prepared_inputs(self):
        self.reviewed_job()
        self.mixed_proposal()
        self.cli(*self.admission_arguments())
        bindings = self.complete_units("source", source_revision="mixed", checkpoint=False)
        self.assertEqual(len(bindings), 1)
        binding = bindings[0]
        result_path = self.job / binding["result"]
        authored = result_path.read_bytes()
        try:
            incomplete = json.loads(authored)
            incomplete["inspection"] = []
            core.save_json(result_path, incomplete)
            self.refuse(lambda: workflow.checkpoint_unit(self.job, "source", "u0001", self.task("source")))
        finally:
            result_path.write_bytes(authored)
        witness = self.job / "work/restoration-witness.txt"
        original = witness.read_bytes()
        try:
            witness.write_bytes(original + b"Changed after admission")
            self.refuse(lambda: workflow.checkpoint_unit(self.job, "source", "u0001", self.task("source")))
        finally:
            witness.write_bytes(original)
        workflow.checkpoint_unit(self.job, "source", "u0001", self.task("source"))
        self.cli("assemble-units", self.job, "source")
        self.assertEqual(core.load_json(self.job / "book-source.json"), self.expected)

    @unittest.skipUnless(shutil.which("xelatex"), "real XeLaTeX required for v2 mixed recovery smoke")
    def test_real_xelatex_mixed_scope_recovery_preserves_all_eleven_normal_gates(self):
        self.build_patch.stop()
        self.reviewed_job()
        initial = core.load_json(self.job / "build/verification.json")
        self.assertTrue(initial["passed"])
        self.assertTrue(all(initial["checks"][name] for name in workflow.BUILD_CHECKS))
        self.mixed_proposal()
        prepared = {record["output"]["ref"]["path"]: record["output"]["ref"]["sha256"]
                    for record in self.request["source_changes"]["crop_derivations"]}
        self.exercise_recovery()
        verification = core.load_json(self.job / "build/verification.json")
        self.assertTrue(verification["passed"])
        self.assertTrue(all(verification["checks"][name] for name in workflow.BUILD_CHECKS))
        self.assertIn("XeTeX", (self.job / "build/compiler.log").read_text())
        marks = verification["source_marks"]
        self.assertTrue(any(mark["printed_label"] == "iv" and mark["display"] == "iv" for mark in marks))
        self.assertTrue(any(row["id"] == "u0001_repair" for row in verification["notes"]))
        for name, digest in prepared.items():
            self.assertEqual(workflow.digest_file(self.job / name), digest)
        print(json.dumps({"kind": "synthetic-v2-real-xelatex-recovery", "checks": verification["checks"],
                          "initial_pdf_sha256": initial["pdf_sha256"], "final_pdf_sha256": verification["pdf_sha256"],
                          "prepared_outputs": prepared, "round": workflow.load_job(self.job)["round"],
                          "limits": "Synthetic native/task data; structural/rendering evidence only, no inference or scientific/manuscript-truth claim."}, sort_keys=True, indent=2))

    def test_cli_scope_exclusivity_and_controller_admission_refuse_before_writes(self):
        self.reviewed_job()
        for role, flags in (
                ("source", []), ("source", ["--revise"]), ("source", ["--reopen", "u0001"]),
                ("translation", ["--revise", "--reopen", "u0001"]),
                ("review", ["--revise", "--reopen", "u0001"]),
                ("source", ["--revise", "--reopen", "u0001", "--draft", self.job / "book-source.json"]),
                ("source", ["--revise", "--reopen", "u0001", "--replan-pending"]),
                ("source", ["--revise", "--reopen", "u0001", "--rebase-source", self.job / "absent.json",
                            "--accept-policy-compatibility", "0" * 64])):
            with self.subTest(role=role, flags=flags):
                self.refuse_cli("plan-units", self.job, role, "--pages-per-unit", "1", *flags,
                                "--post-review-scope", self.scope)
        self.refuse_cli("checkpoint-role", self.job, "source", "--task-result", self.task("source"),
                        "--post-review-scope", self.scope)
        self.refuse(lambda: self.plan("source", revise=True, reopen_units=["u0001"]))
        for state, number, cap in (("translated", 1, 3), ("approved", 1, 3), ("exhausted", 3, 3),
                                   ("changes_requested", 0, 3), ("changes_requested", 1, 1)):
            original = (self.job / "job.json").read_bytes()
            try:
                data = json.loads(original)
                data.update(state=state, round=number, max_rounds=cap)
                core.save_json(self.job / "job.json", data)
                with self.subTest(state=state, number=number, cap=cap):
                    self.refuse_cli(*self.admission_arguments())
            finally:
                (self.job / "job.json").write_bytes(original)
        before = self.files()
        self.cli(*self.admission_arguments())
        self.assertEqual(workflow.load_job(self.job), self.original_job)
        for name, content in before.items():
            if name != "units/source/active.json":
                self.assertEqual((self.job / name).read_bytes(), content, name)

    def test_recovery_preserves_round_bindings_history_and_frozen_build_until_next_review(self):
        self.reviewed_job()
        self.exercise_recovery()

    def exercise_recovery(self):
        self.admit_and_reseal()
        tag = self.base["post_review"]
        self.assertEqual((tag["original_round"], tag["original_max_rounds"]), (1, 3))
        self.assertEqual(tag["submitted_review"], self.request["submitted_review"])
        self.assertEqual((self.job / tag["target_document"]["path"]).read_bytes(), self.original_files["book.json"])
        for name, content in self.original_files.items():
            if name.startswith("build/"):
                reference = tag["build_files"][name]
                self.assertEqual((self.job / reference["path"]).read_bytes(), content, name)
                self.assertEqual(workflow.digest_file(self.job / reference["path"]), reference["sha256"])
        self.assertFalse((self.job / "build/verification.json").exists())
        self.assertFalse((self.job / "reviews/archive").exists())
        self.fresh_terminology()
        term = core.load_json(self.job / self.new_term_event["receipt"])
        self.assertEqual(term["source_digest"], workflow.source_digest(self.job))
        self.assertNotEqual(term["source_digest"], self.original_files["source.sha256"].decode("ascii").strip())
        self.assertEqual(term["bindings"]["post_review_base"], self.base_reference)
        self.assertEqual((self.job / "terms.json").read_bytes(), self.original_files["terms.json"])
        self.refuse(lambda: self.plan("translation", rebase_source=self.revision_path,
                                      accept_policy_compatibility="0" * 64))
        plan = self.rebase()
        self.assertEqual(plan["source_rebase"]["carried"], {})
        self.assertEqual(self.base["post_review"]["failed_review_units"],
                         [spec["unit_id"] for spec in self.original_review_plan["units"]])
        self.assertTrue(self.base["post_review"]["forced_pending"]["u0003"])
        unchanged = plan["source_rebase"]["footprints"]["u0003"]
        self.assertEqual(unchanged["before"], unchanged["after"])
        self.assertEqual(unchanged["decision"], "pending")
        self.assertIn("u0003", unchanged["review_exclusions"])
        self.complete_units("translation")
        with patch("render.build", side_effect=ValueError("synthetic recovery build failure")):
            self.refuse_pending_assembly()
        pending = workflow.load_job(self.job)
        event = pending["history"][-1]
        proof = workflow.translation_authoring_proof(self.job, pending, event)
        self.assertEqual((proof["base_state"], proof["base_round"]), ("changes_requested", 1))
        self.assertEqual(proof["terminology_receipt"], self.new_term_event["receipt"])
        self.assertEqual(proof["source_digest"], workflow.source_digest(self.job))
        before = self.files()
        with patch("render.build", side_effect=ValueError("synthetic recovery build failure")):
            with self.assertRaises(ValueError):
                workflow.finalize_translation(self.job)
        self.assertEqual(self.files(), before)
        self.refuse(lambda: workflow.assemble_units(self.job, "translation"))
        for change in ({"max_rounds": 4}, {"max_rounds": 1}, {"round": 0}):
            old = (self.job / "job.json").read_bytes()
            try:
                core.save_json(self.job / "job.json", {**json.loads(old), **change})
                self.refuse(lambda: workflow.finalize_translation(self.job))
            finally:
                (self.job / "job.json").write_bytes(old)
        task_files = {path.name: path.read_bytes() for path in (self.root / "coordinator-results").glob("*.json")}
        result = self.cli("finalize-translation", self.job)
        self.assertEqual((result["state"], result["round"], workflow.load_job(self.job)["max_rounds"]), ("translated", 2, 3))
        self.assertEqual({path.name: path.read_bytes() for path in (self.root / "coordinator-results").glob("*.json")}, task_files)
        self.assertEqual((self.job / event["receipt"]).read_bytes(), before[event["receipt"]])
        finalized = core.load_json(Path(result["receipt"]))
        self.assertEqual((finalized["authoring_receipt"], finalized["authoring_receipt_sha256"]),
                         (event["receipt"], event["receipt_sha256"]))
        self.assertEqual(finalized["source_digest"], proof["source_digest"])
        self.assertEqual(finalized["terminology_receipt_sha256"], self.new_term_event["receipt_sha256"])
        self.assertEqual(finalized["content_digest"], workflow.current_build(self.job)["content_digest"])
        current = workflow.load_job(self.job)
        self.assertEqual(current["history"][:len(self.original_job["history"])], self.original_job["history"])
        old_plan_path = self.original_target_plan["units"][0]["packet"].rsplit("/packets/", 1)[0] + "/plan.json"
        self.assertEqual((self.job / old_plan_path).read_bytes(), self.original_files[old_plan_path])
        self.assertEqual(self.original_target_plan["base_round"], 0)
        for name, content in self.original_files.items():
            if name.startswith(("reviews/", "provenance/", "units/")) and not name.endswith("active.json"):
                self.assertEqual((self.job / name).read_bytes(), content, name)
        self.refuse_cli("finalize-translation", self.job)
        self.refuse_cli("review", self.job, self.job / "reviews/round-1.json")
        stale = json.loads(self.original_files["reviews/round-1.json"])
        stale["round"] = 2
        stale_path = self.root / "relabeled-old-review.json"
        core.save_json(stale_path, stale)
        self.refuse_cli("review", self.job, stale_path)
        self.refuse_cli("accept", self.job)
        self.assertFalse((self.job / "reviews/round-2.receipt.json").exists())
        self.plan("review")
        self.complete_units("review")
        self.cli("assemble-units", self.job, "review")
        self.cli("review", self.job, self.job / "reviews/round-2.json")
        self.cli("accept", self.job)
        self.assertEqual(workflow.digest_file(self.job / "output.pdf"), workflow.current_build(self.job)["pdf_sha256"])
        report = core.load_json(self.job / "reviews/round-2.json")
        self.assertEqual((report["round"], report["content_digest"], report["pdf_sha256"]),
                         (2, finalized["content_digest"], finalized["pdf_sha256"]))
        for name, reference in tag["build_files"].items():
            self.assertEqual((self.job / reference["path"]).read_bytes(), self.original_files[name], name)

    def refuse_pending_assembly(self):
        with self.assertRaisesRegex(ValueError, "synthetic recovery build failure"):
            workflow.assemble_units(self.job, "translation")
        self.assertEqual((workflow.load_job(self.job)["state"], workflow.load_job(self.job)["round"]), ("changes_requested", 1))

    def test_fresh_native_terminology_cannot_reuse_old_task_or_relabel_old_receipt(self):
        self.reviewed_job()
        old_event = next(item for item in reversed(self.original_job["history"]) if item["event"] == "stage_terminology")
        old_receipt = self.job / old_event["receipt"]
        old_bytes = old_receipt.read_bytes()
        self.admit_and_reseal()
        self.refuse(self.rebase)
        self.refuse_cli("checkpoint-role", self.job, "terminology", "--task-result", self.initial_term_task)
        self.assertEqual(old_receipt.read_bytes(), old_bytes)
        terms_path = self.job / "terms.json"
        old_terms = terms_path.read_bytes()
        try:
            changed = core.load_json(terms_path)
            changed["terms"][0]["rationale"] += " Changed whole-table policy."
            core.save_json(terms_path, changed)
            self.refuse_cli("checkpoint-role", self.job, "terminology", "--task-result", self.task("terminology"))
        finally:
            terms_path.write_bytes(old_terms)
        self.fresh_terminology()
        new_receipt = self.job / self.new_term_event["receipt"]
        fresh_bytes = new_receipt.read_bytes()
        try:
            new_receipt.write_bytes(old_bytes)
            self.refuse(self.rebase)
        finally:
            new_receipt.write_bytes(fresh_bytes)
        self.assertNotEqual(core.load_json(new_receipt)["source_digest"], core.load_json(old_receipt)["source_digest"])
        self.rebase()
        self.assertEqual(old_receipt.read_bytes(), old_bytes)

    def test_recovery_rejects_noop_replay_and_untagged_target_bypasses(self):
        self.reviewed_job()
        proposal = self.job / self.request["expected_source"]["path"]
        original_proposal = proposal.read_bytes()
        core.save_json(proposal, core.load_json(self.job / "book-source.json"))
        noop = copy.deepcopy(self.request)
        noop["expected_source"]["sha256"] = workflow.digest_file(proposal)
        core.save_json(self.scope, noop)
        self.refuse_cli(*self.admission_arguments())
        proposal.write_bytes(original_proposal)
        core.save_json(self.scope, self.request)
        self.admit_and_reseal()
        self.refuse_cli(*self.admission_arguments())
        self.refuse_cli("seal-source", self.job, "--reseal")
        self.fresh_terminology()
        self.refuse(lambda: self.plan("translation"))
        self.refuse(lambda: workflow.checkpoint_role(self.job, "translation", self.task("translation")))
        self.refuse_cli("finalize-translation", self.job)
        original_job = (self.job / "job.json").read_bytes()
        try:
            drifted = json.loads(original_job)
            drifted["round"] = 2
            core.save_json(self.job / "job.json", drifted)
            self.refuse(lambda: self.plan("translation"))
            self.refuse(lambda: workflow.checkpoint_role(self.job, "translation", self.task("translation")))
            self.refuse_cli("finalize-translation", self.job)
        finally:
            (self.job / "job.json").write_bytes(original_job)
        self.rebase()

    def test_malformed_recovery_base_cannot_fall_back_to_generic_round_reset(self):
        self.reviewed_job()
        reference = self.cli(*self.admission_arguments())
        revision = core.load_json(self.job / reference["plan"])
        self.complete_units("source", source_revision=self.source_revision)
        workflow.assemble_units(self.job, "source")
        path = self.job / revision["source_revision"]["base"]["path"]
        old = path.read_bytes()
        try:
            base = core.load_json(path)
            del base["post_review"]["submitted_review"]
            core.save_json(path, base)
            self.refuse_cli("seal-source", self.job, "--reseal")
        finally:
            path.write_bytes(old)
        self.cli("seal-source", self.job, "--reseal")
        self.assertEqual(workflow.load_job(self.job)["round"], 1)

    def test_initial_round_zero_source_recovery_still_uses_ordinary_rebase(self):
        self.plan("translation")
        self.complete_units("translation")
        expected = core.load_json(self.job / "book-source.json")
        expected["blocks"][0].update(kind="list_item", label="1.", list_type="ordered", list_level=0)
        reference = workflow.plan_units(self.job, "source", 1, revise=True, reopen_units=["u0001"])
        revision = self.job / reference["plan"]
        base_ref = core.load_json(revision)["source_revision"]["base"]
        self.assertNotIn("post_review", core.load_json(self.job / base_ref["path"]))
        self.complete_units("source", source_revision="list")
        workflow.assemble_units(self.job, "source")
        workflow.seal_job(self.job, reseal=True)
        self.assertEqual((workflow.load_job(self.job)["state"], workflow.load_job(self.job)["round"]), ("source_ready", 0))
        (self.job / "handoff.md").write_text("Synthetic fresh native terminology: initial structural correction; unchanged terms and compatible policy.\n", encoding="utf-8")
        workflow.checkpoint_role(self.job, "terminology", self.task("terminology"))
        self.assertEqual((workflow.load_job(self.job)["state"], workflow.load_job(self.job)["round"]), ("terminology_ready", 0))
        self.plan("translation", rebase_source=revision,
                  accept_policy_compatibility=workflow.digest_file(self.job / "handoff.md"))
        self.complete_units("translation")
        result = workflow.assemble_units(self.job, "translation")
        self.assertEqual((result["state"], result["round"]), ("translated", 1))
        self.assertEqual(workflow.load_job(self.job)["max_rounds"], 3)

    def test_no_source_translation_revision_keeps_ordinary_native_unit_route(self):
        self.reviewed_job()
        before = self.files()
        plan = self.plan("translation")
        self.assertNotIn("source_rebase", plan)
        self.complete_units("translation")
        result = workflow.assemble_units(self.job, "translation")
        self.assertEqual((result["state"], result["round"]), ("translated", 2))
        self.assertEqual(workflow.load_job(self.job)["max_rounds"], 3)
        for name in ("book-source.json", "source.sha256", "terms.json", "handoff.md",
                     "reviews/round-1.json", "reviews/round-1.receipt.json"):
            self.assertEqual((self.job / name).read_bytes(), before[name], name)


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
