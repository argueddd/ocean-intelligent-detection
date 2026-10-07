"""New runtime regression, all data and approvals fabricated for development only."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from scipy.signal import periodogram
from scipy.stats import binomtest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import input_adapter as adapter
import cfar_registry as registry
import cfar_core as core
import cfar_calibration as calibration
import detection_runtime as runtime
import detection_associations as associations
import detection_products as products
import preflight as pf
from test_contract_schema import fixture

MOCK = "SYNTHETIC UNIT TEST ONLY, not real user authorization"
LIMITS = {"max_package_bytes": 64*1024**2, "max_block_samples": 1000}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def parameters(method="ca_cfar"):
    return {"spectrum": {"window_length": 128, "hop_length": 128, "nfft": 128, "window": "rectangular",
            "demean": False, "frame_origin": "each_interval_start", "invalid_frame": "skip_and_report", "unknown_validity": "reject"},
        "cfar": {"reference_per_side": 3, "guard_per_side": 1, "rank": None if method == "ca_cfar" else 5,
            "reference_band_hz": [0, 512], "insufficient_reference": "skip_and_report", "zero_background": "skip_and_report"},
        "threshold": {"route": "theory", "event_scope": "frame", "event_probability": 0.1,
            "family": "this_task_signal_detector_only_no_joint_guarantee",
            "theory_assumption": {"model": "iid_exponential_cells", "applicability": "model_asserted", "rationale": MOCK},
            "calibration_ref": None},
        "candidates": {"group_width_hz": None, "minimum_peak_distance_hz": None}, "display": None}


def make_task(inp, method="ca_cfar", tid="test_task"):
    return {"task_id": tid, "input_ref": {"package_sha256": inp["source_package"]["manifest"]["sha256"], "signal_id": inp["signal_id"]},
        "detector": registry.identity(method), "task_kind": "framewise",
        "scope": {"sample_intervals": [[0, 1024]], "search_band_hz": [64, 384], "time_reference": inp["time_mapping"]["time_reference"]},
        "resolved_parameters": parameters(method), "processing_steps": registry.processing_steps(parameters(method)),
        "parameter_evidence": [{"field": "/resolved_parameters", "basis": "user_choice", "reference": MOCK}],
        "products": {"compute": [], "view": [], "save": []}}


def mock_receipt(report):
    return runtime.confirm(report, {"actor": "user", "decision": "authorize_execution", "plan_sha256": report["plan_sha256"],
                                    "statement": MOCK, "reference": MOCK})


class Core(unittest.TestCase):
    def setUp(self):
        self.inp = fixture("SignalInput")["payload"]
        self.inp["waveform"].update(shape=[1024, 1], sample_count=1024)
        self.inp.update(sample_rate_hz=1024)
        self.inp["validity"].update(status="known", sample_intervals=[[0, 1024]], mask_ref=None)
        self.inp["frequency_coverage"].update(status="known", band_hz=[0, 512])
        self.task = make_task(self.inp)
        self.x = np.random.default_rng(7).normal(size=(1024, 1))
        self.x[:, 0] += 5*np.sin(2*np.pi*160*np.arange(1024)/1024)

    def plan(self, task=None, x=None, mask=None):
        return core.plan(task or self.task, self.inp, self.x if x is None else x, mask, 512*1024**2)

    def test_psd_matches_scipy_even_odd_windows_demean(self):
        for window in ("rectangular", "periodic_hann"):
            for nfft in (128, 129, 256):
                for demean in (False, True):
                    p = dict(parameters()["spectrum"], window=window, nfft=nfft, demean=demean)
                    actual = core.periodogram(self.x[:128, 0], 1024, p)
                    _, expected = periodogram(self.x[:128, 0], fs=1024, window="boxcar" if window == "rectangular" else "hann",
                        nfft=nfft, detrend="constant" if demean else False, return_onesided=True, scaling="density")
                    np.testing.assert_allclose(actual, expected, rtol=2e-13, atol=1e-16)

    def test_parseval_rectangular(self):
        p = parameters()["spectrum"]
        values = core.periodogram(self.x[:128, 0], 1024, p)
        self.assertAlmostEqual(values.sum()*8, np.mean(self.x[:128, 0]**2), places=12)

    def test_theory_frame_and_segment_budget(self):
        prepared = self.plan(); self.assertEqual(prepared["tests_per_event"], 41)
        self.task["resolved_parameters"]["threshold"]["event_scope"] = "segment"
        segment = self.plan(); self.assertEqual(segment["tests_per_event"], 41*8)
        self.assertEqual(segment["p_cell"], 0.1/(41*8))

    def test_dc_nyquist_full_references_and_stop(self):
        self.task["scope"]["search_band_hz"] = [0, 512]
        p = self.plan(); self.assertNotIn(0, p["cuts"]); self.assertNotIn(64, p["cuts"])
        self.assertTrue(all(k > 4 and k < 60 for k in p["cuts"]))
        self.task["resolved_parameters"]["cfar"]["insufficient_reference"] = "stop"
        with self.assertRaisesRegex(ValueError, "two-sided"):
            self.plan()

    def test_no_interval_concatenation_and_gaps(self):
        self.task["scope"]["sample_intervals"] = [[0, 200], [250, 500]]
        p = self.plan(); self.assertEqual(p["frames"], [[0, 128], [250, 378]])
        self.assertEqual(core.complement([[0, 200], [250, 500]], core.merge(p["frames"])), [[128, 200], [378, 500]])

    def test_invalid_frame_skip_stop_and_no_success(self):
        mask = np.ones(1024, dtype=bool); mask[100] = False
        p = self.plan(mask=mask); self.assertEqual(len(p["frames"]), 7)
        self.assertEqual(p["frame_ledger"][0]["status"], "skipped")
        self.task["resolved_parameters"]["spectrum"]["invalid_frame"] = "stop"
        with self.assertRaisesRegex(ValueError, "Invalid complete frame"):
            self.plan(mask=mask)
        self.task["resolved_parameters"]["spectrum"]["invalid_frame"] = "skip_and_report"
        with self.assertRaisesRegex(ValueError, "No complete valid"):
            self.plan(mask=np.zeros(1024, dtype=bool))

    def test_unknown_validity_stays_unknown(self):
        self.inp["validity"].update(status="unknown", sample_intervals=None)
        with self.assertRaisesRegex(ValueError, "Unknown validity"):
            self.plan()
        self.task["resolved_parameters"]["spectrum"]["unknown_validity"] = "analyze_unverified"
        self.assertEqual(self.plan()["validity_status"], "unknown")
        self.assertIsNone(self.inp["validity"]["sample_intervals"])

    def test_hann_requires_nominal_model_acknowledgement(self):
        self.task["resolved_parameters"]["spectrum"]["window"] = "periodic_hann"
        with self.assertRaisesRegex(ValueError, "nominal_approximation"):
            self.plan()

    def test_average_requires_matched_calibration_and_segment(self):
        self.task["task_kind"] = "average_spectrum"
        with self.assertRaisesRegex(ValueError, "segment"):
            self.plan()
        self.task["resolved_parameters"]["threshold"]["event_scope"] = "segment"
        with self.assertRaisesRegex(ValueError, "Averaged PSD"):
            self.plan()
        self.task["resolved_parameters"]["threshold"].update(route="calibration", theory_assumption=None, calibration_ref={})
        p = self.plan(); rows = list(core.spectra(self.x, 1024, self.task, p))
        np.testing.assert_allclose(rows[0][2], np.mean([core.periodogram(self.x[a:b, 0], 1024,
            self.task["resolved_parameters"]["spectrum"]) for a, b in p["frames"]], axis=0), rtol=2e-15)

    def test_ca_and_os_background_definitions(self):
        p = self.plan(); psd = np.arange(65, dtype=float)+1
        z, good = core.background(psd, self.task, p)
        k = p["cuts"][0]; vals = psd[k+p["offsets"]]
        self.assertEqual(z[0], np.mean(vals)); self.assertTrue(good.all())
        self.task["detector"] = registry.identity("os_cfar"); self.task["resolved_parameters"]["cfar"]["rank"] = 5
        z, _ = core.background(psd, self.task, p); self.assertEqual(z[0], np.sort(vals)[4])

    def test_group_ties_width_and_min_distance(self):
        p = {"cuts": np.arange(1, 9), "frequency_hz": np.arange(10, dtype=float)}
        psd = np.array([0, 1, 7, 7, 1, 8, 1, 6, 1, 0.]); z = np.ones(8); t = np.full(8, 2.); good = np.ones(8, bool)
        kept, rejected = core.candidates(psd, z, t, good, p, {"group_width_hz": None, "minimum_peak_distance_hz": None})
        self.assertEqual([v["bin"] for v in kept], [2, 5, 7]); self.assertEqual(kept[0]["tied_maximum_bins"], [2, 3])
        kept, rejected = core.candidates(psd, z, t, good, p, {"group_width_hz": [0, 1], "minimum_peak_distance_hz": 3})
        self.assertEqual([v["bin"] for v in kept], [5]); self.assertEqual(len(rejected), 2)

    def test_strict_threshold_and_no_group_across_excluded_bin(self):
        p = {"cuts": np.array([1, 2, 4]), "frequency_hz": np.arange(6, dtype=float)}
        psd = np.array([0, 2, 3, 0, 3, 0.])
        kept, _ = core.candidates(psd, np.ones(3), np.full(3, 2.), np.ones(3, bool), p,
                                 {"group_width_hz": None, "minimum_peak_distance_hz": None})
        self.assertEqual([v["bin"] for v in kept], [2, 4])

    def test_zero_background_never_epsilon_or_empty_success(self):
        p = self.plan(x=np.zeros((1024, 1)))
        with self.assertRaisesRegex(ValueError, "No tested cells"):
            core.execute(self.task, self.inp, np.zeros((1024, 1)), p)
        self.task["resolved_parameters"]["cfar"]["zero_background"] = "stop"
        with self.assertRaisesRegex(ValueError, "background"):
            core.execute(self.task, self.inp, np.zeros((1024, 1)), p)

    def test_detects_tone_keeps_zero_candidate_rows(self):
        p = self.plan(); out = core.execute(self.task, self.inp, self.x, p)
        self.assertTrue(any(v["frequency_hz"] == 160 for v in out["candidates"]))
        self.assertEqual(len(out["rows"]), 8)
        self.assertTrue(all("candidate_count" in row for row in out["rows"]))

    def test_memory_admission_precedes_fft(self):
        with patch.object(np.fft, "rfftfreq", side_effect=AssertionError("No allocation")):
            with self.assertRaisesRegex(ValueError, "Working allocation"):
                core.plan(self.task, self.inp, self.x, None, 1)

    def test_validation_upper_bound_matches_scipy(self):
        for k, n in ((0, 10), (2, 30), (30, 30)):
            v = calibration.validation_summary([2.]*k+[1.]*(n-k), 1.5, .2, .95)
            expected = binomtest(k, n, alternative="less").proportion_ci(.95, method="exact").high
            self.assertAlmostEqual(v["one_sided_clopper_pearson_upper"], expected, places=12)

    def test_calibration_tail_resolution_and_order(self):
        with self.assertRaisesRegex(ValueError, "tail resolution"):
            calibration.order_coefficient([1., 2., 3.], .01)
        self.assertEqual(calibration.order_coefficient([1., 5., 3., 2., 4.], .4), (4., 4))


class Runtime(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp_fixture = tempfile.TemporaryDirectory(prefix="line-runtime-synthetic-")
        cls.addClassCleanup(cls.tmp_fixture.cleanup)
        cls.fixture_root = Path(cls.tmp_fixture.name).resolve()
        command = subprocess.run([sys.executable, "-B", str(ROOT / "tests/runtime_fixture_producer.py"), str(cls.fixture_root)],
            capture_output=True, text=True, timeout=60)
        if command.returncode:
            raise AssertionError(command.stdout+command.stderr)
        cls.paths = json.loads(command.stdout)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="line-runtime-test-"); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve(); self.root = self.base / "source"; self.root.mkdir()
        self.context = {"context_version": "0.1.0", "document_status": "specified", "inputs": [], "descriptors": [],
            "source_files": [], "max_source_bytes": 64*1024**2, "handoff_validation": LIMITS}
        self.docs = {}; self.add_input("noise", "signal_000000")
        self.task = make_task(self.docs["noise"]["payload"])
        self.request = registry.envelope("DetectionRequest", {"request_id": "synthetic-request", "tasks": [self.task],
            "unknown_decisions": [], "resources": {"max_working_bytes": 1024**3, "max_artifact_bytes": 128*1024**2,
                "persistence": "saved", "output_directory": str(self.base / "output"), "temporary_storage_policy": "memory_only_until_publish"},
            "batch_failure_policy": "stop_batch", "approval": {"status": "pending", "bound_plan_sha256": None, "evidence_refs": []},
            "parent_request": None, "parent_result": None})
        self.sync()

    def add_input(self, name, sid):
        folder = self.root / name
        if not folder.exists():
            shutil.copytree(Path(self.paths[name]).parent, folder)
        handoff = folder / "handoff.json"
        doc = adapter.adapt(handoff, sha(handoff), "beamformed_handoff" if name == "main" else "bypass_handoff", sid, **LIMITS)["signal_input"]
        label = name if name not in self.docs else name+sid
        self.docs[label] = doc
        path = self.root / (label+".json"); path.write_bytes(products.json_bytes(doc)); self.context["inputs"].append(path.name)
        seen = {v["sha256"] for v in self.context["source_files"]}
        for path in folder.iterdir():
            if path.is_file() and sha(path) not in seen:
                self.context["source_files"].append({"sha256": sha(path), "path": path.relative_to(self.root).as_posix()}); seen.add(sha(path))
        return doc

    def sync(self):
        self.context["descriptors"] = []
        for method in sorted({t["detector"]["detector_id"] for t in self.request["payload"]["tasks"]}):
            name = method+".json"; (self.root/name).write_bytes(products.json_bytes(registry.descriptor(method)))
            self.context["descriptors"].append(name)
        for t in self.request["payload"]["tasks"]:
            t["processing_steps"] = registry.processing_steps(t["resolved_parameters"])

    def ready(self):
        self.sync(); r = runtime.review(self.request, self.context, self.root)
        self.assertEqual(r["status"], "ready_pending_execution_confirmation", r)
        self.assertFalse(r["can_execute"]); return r

    def execute(self):
        return runtime.run(self.request, self.context, self.root, mock_receipt(self.ready()))

    def test_review_is_readonly_no_psd(self):
        before = {str(p): sha(p) for p in self.root.rglob("*") if p.is_file()}
        with patch.object(core, "periodogram", side_effect=AssertionError("Review must not calculate PSD")):
            r = self.ready()
        self.assertEqual(r["tasks"][0]["valid_frames"], 8)
        self.assertEqual(before, {str(p): sha(p) for p in self.root.rglob("*") if p.is_file()})
        self.assertFalse((self.base/"output").exists())

    def test_run_complete_public_contract_and_minimal_delivery(self):
        answer = self.execute(); result = answer["result"]
        runtime.require_contract(result, "DetectionResult")
        self.assertEqual(result["payload"]["delivery_status"], "completed")
        names = {p.name for p in (self.base/"output").iterdir()}
        self.assertEqual(names, {"request.json", "resolved-configuration.json", "association.json", "detection-result.json", "package-manifest.json"})
        self.assertEqual(len(json.loads((self.base/"output/resolved-configuration.json").read_text())["detection_evidence"]["test_task"]["rows"]), 8)

    def test_ca_os_explicit_two_tasks_unique_candidate_ids(self):
        self.task["resolved_parameters"]["threshold"]["event_probability"] = .9
        other = copy.deepcopy(self.task); other["task_id"] = "os_test"; other["detector"] = registry.identity("os_cfar")
        other["resolved_parameters"]["cfar"]["rank"] = 5
        self.request["payload"]["tasks"].append(other)
        results = self.execute()["result"]["payload"]["task_results"]
        ids = [v["candidate_id"] for t in results for v in t["candidates"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_missing_parameter_or_changed_descriptor_blocks(self):
        del self.task["resolved_parameters"]["spectrum"]["hop_length"]
        self.sync(); self.assertEqual(runtime.review(self.request, self.context, self.root)["status"], "blocked")

    def test_cannot_run_with_old_preflight_receipt(self):
        with self.assertRaises(ValueError):
            runtime.run(self.request, self.context, self.root, {"scope": "preflight_plan_only_not_execution"})

    def test_changed_probability_stales_execution_receipt(self):
        receipt = mock_receipt(self.ready()); self.task["resolved_parameters"]["threshold"]["event_probability"] = .2; self.sync()
        with self.assertRaisesRegex(ValueError, "stale"):
            runtime.run(self.request, self.context, self.root, receipt)

    def test_missing_full_adapter_blocks(self):
        del self.context["handoff_validation"]
        self.assertEqual(runtime.review(self.request, self.context, self.root)["status"], "blocked")

    def test_no_source_output_overwrite(self):
        self.request["payload"]["resources"]["output_directory"] = str(self.root/"output")
        self.assertEqual(runtime.review(self.request, self.context, self.root)["status"], "blocked")
        self.request["payload"]["resources"]["output_directory"] = str(self.base/"output")
        self.execute()
        self.assertEqual(runtime.review(self.request, self.context, self.root)["status"], "blocked")

    def test_byte_budget_failure_leaves_no_manifest(self):
        self.request["payload"]["resources"]["max_artifact_bytes"] = 1
        with self.assertRaisesRegex(ValueError, "byte budget"):
            self.execute()
        self.assertFalse((self.base/"output").exists())

    def test_source_mutation_before_publication_blocks(self):
        original = core.execute
        def changed(*args, **kwargs):
            answer = original(*args, **kwargs)
            with (self.root/"noise/signal_000000.npy").open("ab") as f:
                f.write(b"MUTATED TEST FIXTURE")
            return answer
        with patch.object(core, "execute", side_effect=changed), self.assertRaisesRegex(ValueError, "changed"):
            self.execute()
        self.assertFalse((self.base/"output").exists())

    def test_session_has_no_disk_outputs(self):
        self.request["payload"]["resources"].update(persistence="session", output_directory=None, temporary_storage_policy="memory_only")
        self.task["products"].update(compute=["candidates"], view=["candidates"])
        answer = self.execute(); self.assertTrue(answer["views"]); self.assertTrue(answer["files"])
        self.assertFalse((self.base/"output").exists())

    def test_spectra_and_views_only_when_selected(self):
        self.task["products"] = {"compute": ["spectra", "spectrum_plot", "time_frequency_plot", "ledger", "report"],
            "view": ["spectrum_plot"], "save": ["spectra", "spectrum_plot", "time_frequency_plot", "ledger", "report"]}
        self.task["resolved_parameters"]["display"] = {"db_reference_psd": 1., "db_limits": [-60., 10.], "spectrum_rows": [0], "title": "Synthetic validation only"}
        answer = self.execute(); out = self.base/"output"
        self.assertTrue((out/"task-000000/spectrum_plot/spectrum-row-00000000.png").is_file())
        self.assertFalse(any("time.npy" in p.name for p in out.rglob("*")))
        with np.load(out/"task-000000/spectra/spectra.npz", allow_pickle=False) as v:
            self.assertEqual(v["psd"].shape, (8, 65)); self.assertEqual(v["cell_valid"].dtype, np.dtype(bool))
        self.assertTrue(answer["views"])

    def test_view_selection_does_not_authorize_compute(self):
        self.task["products"]["view"] = ["spectrum_plot"]
        self.sync(); self.assertEqual(runtime.review(self.request, self.context, self.root)["status"], "blocked")

    def test_main_beam_provenance_columns_bidirectional(self):
        doc = self.add_input("main", "signal_000000"); inp = doc["payload"]
        self.task.update(input_ref={"package_sha256": inp["source_package"]["manifest"]["sha256"], "signal_id": inp["signal_id"]})
        self.task["scope"].update(sample_intervals=inp["validity"]["sample_intervals"], search_band_hz=[100, 300], time_reference=inp["time_mapping"]["time_reference"])
        self.task["resolved_parameters"]["cfar"]["reference_band_hz"] = [40, 450]
        self.task["resolved_parameters"]["threshold"]["theory_assumption"]["applicability"] = "nominal_approximation"
        answer = self.execute(); assoc = answer["association"]
        beam = next(v for v in assoc["payload"]["entities"] if v["kind"] == "beam")
        down = associations.query([assoc], "beam", beam["identity"], "descendants")
        self.assertTrue(any(v["kind"] == "task" for v in down["entities"]))
        up = associations.query([assoc], "task", {"run_id": answer["result"]["payload"]["run_id"], "task_id": self.task["task_id"]}, "ancestors")
        self.assertIn(beam, up["entities"])
        mapping = json.loads(assoc["payload"]["scope_mapping"][0]["definition"])
        self.assertEqual(mapping["beam_source"]["source_column"], 1); self.assertEqual(mapping["beam_source"]["scan_column"], 0)

    def test_joint_view_does_not_detect(self):
        self.execute(); out = self.base/"output"
        cfg = {"view_version": "1.0.0", "detections": [{"directory": str(out), "manifest_sha256": sha(out/"package-manifest.json"),
            "task_ids": ["test_task"], "product_ids": []}], "beams": [],
            "alignment_rule": "native_coordinates_exact_bin_lookup_no_interpolation", "max_read_bytes": 64*1024**2,
            "max_artifact_bytes": 64*1024**2, "output_directory": None}
        with patch.object(core, "execute", side_effect=AssertionError("Must not detect")):
            answer = associations.joint_view(cfg)
        self.assertIn("joint-view.html", answer["files"])
        cfg["detections"][0]["product_ids"] = ["spectra"]
        with self.assertRaisesRegex(ValueError, "not saved"):
            associations.joint_view(cfg)

    def test_native_beam_column_lookup_not_saved_column(self):
        path = Path(self.paths["beam_result"])
        value = associations.beam_evidence({"result_path": str(path), "result_sha256": sha(path), "algorithm": "mvdr",
            "beam_ids": ["beam_000000"], "products": ["psd", "btr", "frequency_angle", "time_frequency", "scan_power"],
            "plot_products": [], "frequency_range_hz": None, "time_range_seconds": None, "display": None}, 64*1024**2)
        original = np.load(path.parent/"mvdr_psd.npy")
        np.testing.assert_array_equal(value["values"]["psd"][:, 0], original[:, 0])

    def calibration_config(self):
        self.task["scope"]["sample_intervals"] = [[32000, 32128]]
        self.task["resolved_parameters"]["threshold"].update(route="calibration", theory_assumption=None, calibration_ref=None, event_probability=.2)
        self.sync()
        trials = [{"trial_id": f"h0_{i}", "split": "calibration" if i < 50 else "validation",
            "input_ref": self.task["input_ref"], "scope": {**self.task["scope"], "sample_intervals": [[i*128, (i+1)*128]]},
            "background_statement": MOCK+" synthetic Gaussian white noise", "processing_equivalence_statement": MOCK}
            for i in range(150)]
        return {"calibration_version": "1.0.0", "target_request": self.request, "context": self.context, "trials": trials,
            "independence_statement": MOCK+" disjoint IID-generated frames", "background_evidence_reference": MOCK,
            "confidence_level": .5, "minimum_calibration_events": 50, "minimum_validation_events": 100,
            "quantile_rule": "conservative_order_statistic", "validation_rule": "one_sided_clopper_pearson_upper_le_q"}

    def test_calibration_whole_pipeline_and_independent_records(self):
        cfg = self.calibration_config(); r = calibration.review(cfg, self.root)
        self.assertEqual(r["status"], "ready_pending_execution_confirmation", r)
        answer = calibration.run(cfg, self.root, mock_receipt(r)); record = answer["record"]
        self.assertEqual(len(record["calibration_maxima"]), 50); self.assertEqual(len(record["validation_maxima"]), 100)
        self.assertEqual(len(record["trial_records"]), 150)
        self.assertEqual(record["status"] == "qualified_for_declared_scope", record["validation"]["passes_declared_rule"])

    def test_calibration_overlap_rejected(self):
        cfg = self.calibration_config(); cfg["trials"][-1]["scope"] = copy.deepcopy(cfg["trials"][0]["scope"])
        r = calibration.review(cfg, self.root); self.assertEqual(r["status"], "blocked"); self.assertTrue(any("overlap" in v for v in r["issues"]))

    def test_calibration_multiple_frame_trial_not_independent(self):
        cfg = self.calibration_config(); cfg["trials"][0]["scope"]["sample_intervals"] = [[0, 256]]
        r = calibration.review(cfg, self.root); self.assertEqual(r["status"], "blocked")


    def bind(self, path, value):
        path.write_bytes(products.json_bytes(value))
        return {"path": str(path), "sha256": sha(path)}

    def followup_fixture(self, action="detection"):
        parent = self.execute()
        parent_path = self.base/"output/detection-result.json"
        parent_refs = [{"location": {"kind": "external_reference", "path": str(parent_path)},
                        "sha256": sha(parent_path), "availability": "available"}]
        if action == "detection":
            self.request["payload"]["request_id"] = "child"
            self.request["payload"]["resources"]["output_directory"] = str(self.base/"child-output")
            child_receipt = mock_receipt(self.ready())
            child = self.bind(self.base/"child.json", self.request)
            context = self.bind(self.base/"context.json", self.context)
            child_receipt_ref = self.bind(self.base/"child-receipt.json", child_receipt)
        else:
            cfg = json.loads(Path(self.paths["beam_config"]).read_text())
            cfg["plan"]["output"]["directory"] = str(self.base/"child-beam-output")
            path = self.base/"child-beam.json"; path.write_bytes(products.json_bytes(cfg))
            bridge = "import sys,json; sys.path.insert(0,sys.argv[1]); sys.path.insert(0,sys.argv[2]); import test_numerical as t; print(json.dumps(t.mock_confirm(json.load(sys.stdin))))"
            command = subprocess.run([sys.executable, "-B", "-c", bridge,
                str(ROOT.parent/"underwater-beamforming/scripts"), str(ROOT.parent/"underwater-beamforming/tests")],
                input=json.dumps(cfg), capture_output=True, text=True, timeout=30)
            self.assertEqual(command.returncode, 0, command.stderr+command.stdout)
            cfg = json.loads(command.stdout)
            child = self.bind(path, cfg); context = None; child_receipt_ref = None
        proposed = associations.propose_followup(parent["association"], followup_id="one-shot",
            parent_refs=parent_refs, question="Synthetic follow-up test?", reason=MOCK, action=action,
            config_ref=child, context_ref=context, source_root=str(self.root) if action == "detection" else None, dependencies=[])
        ref = self.bind(self.base/"proposal.json", proposed)
        return {"followup_version": "1.0.0", "association_ref": ref, "followup_id": "one-shot", "action": action,
            "config_ref": child, "context_ref": context, "source_root": str(self.root) if action == "detection" else None,
            "child_receipt_ref": child_receipt_ref, "max_process_seconds": None if action == "detection" else 60,
            "result_record_path": str(self.base/"followup-execution.json")}

    def test_proposal_does_not_trigger_child_computation(self):
        cfg = self.followup_fixture()
        self.assertFalse((self.base/"child-output").exists())
        with patch.object(core, "execute", side_effect=AssertionError("No numerical run in proposal review")):
            report = associations.review_followup(cfg)
        self.assertEqual(report["status"], "ready_pending_execution_confirmation")
        self.assertFalse((self.base/"child-output").exists())

    def test_detection_followup_new_result_and_bidirectional_relation(self):
        cfg = self.followup_fixture()
        old = sha(self.base/"output/detection-result.json")
        report = associations.review_followup(cfg)
        record = associations.run_followup(cfg, mock_receipt(report))
        self.assertEqual(record["status"], "completed", record)
        self.assertEqual(old, sha(self.base/"output/detection-result.json"))
        new = json.loads(Path(record["association_ref"]["location"]["path"]).read_text())
        runtime.require_contract(new, "AssociationRecord")
        self.assertTrue(any(v["kind"] == "followup_of" for v in new["payload"]["relations"]))
        self.assertEqual(new["payload"]["followups"][0]["status"], "completed")

    def test_followup_cannot_use_detection_receipt_or_changed_scope(self):
        cfg = self.followup_fixture()
        child = associations.read_bound(cfg["child_receipt_ref"])
        with self.assertRaises(ValueError):
            associations.run_followup(cfg, child)
        proposed = associations.read_bound(cfg["association_ref"])
        proposed["payload"]["followups"][0]["parameters"]["config_sha256"] = "0"*64
        cfg["association_ref"] = self.bind(self.base/"different-proposal.json", proposed)
        with self.assertRaisesRegex(ValueError, "exact child"):
            associations.review_followup(cfg)

    def test_failed_followup_keeps_failure_new_log_not_old_result(self):
        cfg = self.followup_fixture()
        report = associations.review_followup(cfg)
        old = sha(self.base/"output/detection-result.json")
        with patch.object(runtime, "run", side_effect=ValueError("Synthetic execution failure")):
            record = associations.run_followup(cfg, mock_receipt(report))
        self.assertEqual(record["status"], "failed")
        self.assertEqual(old, sha(self.base/"output/detection-result.json"))
        self.assertEqual(record["result_refs"], [])
        self.assertTrue(Path(record["association_ref"]["location"]["path"]).exists())

    def test_beam_followup_uses_own_gate_and_new_output(self):
        cfg = self.followup_fixture("beam_execute")
        report = associations.review_followup(cfg)
        self.assertEqual(report["status"], "ready_pending_execution_confirmation", report)
        record = associations.run_followup(cfg, mock_receipt(report))
        self.assertEqual(record["status"], "completed", record)
        self.assertTrue((self.base/"child-beam-output/result.json").is_file())

    def test_existing_beam_plots_no_spectral_recomputation(self):
        path = Path(self.paths["beam_result"])
        data = associations.beam_evidence({"result_path": str(path), "result_sha256": sha(path), "algorithm": "cbf",
            "beam_ids": ["beam_000002", "beam_000000"], "products": ["psd", "btr", "frequency_angle", "time_frequency", "scan_power"],
            "plot_products": ["psd", "btr", "frequency_angle", "time_frequency", "scan_power"],
            "frequency_range_hz": None, "time_range_seconds": None,
            "display": {"reference_psd": 1., "reference_power": 1., "db_limits": [-60., 10.], "title": "Synthetic native evidence"}},
            64*1024**2)
        with patch.object(core, "periodogram", side_effect=AssertionError("No PSD recalculation")):
            images = products.render_beam_context(data)
        self.assertEqual(len(images), 6)
        self.assertTrue(all(value.startswith(b"\x89PNG") for value in images.values()))

    def test_band_integrated_or_averaged_results_not_silently_recropped(self):
        path = Path(self.paths["beam_result"])
        base = {"result_path": str(path), "result_sha256": sha(path), "algorithm": "cbf",
            "beam_ids": ["beam_000000"], "products": ["btr"], "plot_products": [],
            "frequency_range_hz": [100, 200], "time_range_seconds": None, "display": None}
        with self.assertRaisesRegex(ValueError, "band-integrated"):
            associations.beam_evidence(base, 64*1024**2)
        base.update(products=["psd"], frequency_range_hz=None, time_range_seconds=[.5, 1.])
        with self.assertRaisesRegex(ValueError, "time-averaged"):
            associations.beam_evidence(base, 64*1024**2)

    def test_calibration_consumption_and_mismatch_guard(self):
        cfg = self.calibration_config()
        report = calibration.review(cfg, self.root)
        record = calibration.run(cfg, self.root, mock_receipt(report))["record"]
        self.assertEqual(record["status"], "qualified_for_declared_scope", record["validation"])
        state = runtime.RuntimeReview(self.request, self.context, self.root, calibrating=True)
        self.request["payload"]["resources"]["output_directory"] = str(self.base/"detected")
        state = runtime.RuntimeReview(self.request, self.context, self.root, calibrating=True); state.run()
        entry = state.states[0]
        actual = calibration.check_record(record, self.task, entry["input"]["payload"], entry["prepared"])
        self.assertEqual(actual, record["alpha"])
        damaged = copy.deepcopy(record); damaged["alpha"] += 1
        with self.assertRaisesRegex(ValueError, "audit"):
            calibration.check_record(damaged, self.task, entry["input"]["payload"], entry["prepared"])
        raw = products.json_bytes(record); path = self.root/"calibration-record.json"; path.write_bytes(raw)
        ref = {"location": {"kind": "package_relative", "path": path.name}, "sha256": sha(path), "availability": "available"}
        self.context["source_files"].append({"path": path.name, "sha256": sha(path)})
        self.task["resolved_parameters"]["threshold"]["calibration_ref"] = ref
        answer = self.execute()
        self.assertEqual(answer["result"]["payload"]["delivery_status"], "completed")
        self.task["resolved_parameters"]["spectrum"]["demean"] = True; self.sync()
        self.request["payload"]["resources"]["output_directory"] = str(self.base/"other")
        self.assertEqual(runtime.review(self.request, self.context, self.root)["status"], "blocked")

    def test_average_spectrum_calibration_and_execution(self):
        cfg = self.calibration_config()
        self.task["task_kind"] = "average_spectrum"
        self.task["scope"]["sample_intervals"] = [[32000, 32256]]
        self.task["resolved_parameters"]["threshold"]["event_scope"] = "segment"
        cfg["trials"] = cfg["trials"][:100]
        for i, t in enumerate(cfg["trials"]):
            t["split"] = "calibration" if i < 30 else "validation"
            t["scope"]["sample_intervals"] = [[i*256, (i+1)*256]]
        cfg["minimum_calibration_events"] = 30; cfg["minimum_validation_events"] = 70
        cfg["confidence_level"] = .1
        self.sync()
        report = calibration.review(cfg, self.root)
        self.assertEqual(report["status"], "ready_pending_execution_confirmation", report)
        record = calibration.run(cfg, self.root, mock_receipt(report))["record"]
        self.assertEqual(record["status"], "qualified_for_declared_scope", record["validation"])
        path = self.root/"average-calibration.json"; path.write_bytes(products.json_bytes(record))
        self.context["source_files"].append({"path": path.name, "sha256": sha(path)})
        self.task["resolved_parameters"]["threshold"]["calibration_ref"] = {
            "location": {"kind": "package_relative", "path": path.name}, "sha256": sha(path), "availability": "available"}
        self.request["payload"]["resources"]["output_directory"] = str(self.base/"average-detected")
        answer = self.execute()
        evidence = json.loads((self.base/"average-detected/resolved-configuration.json").read_text())["detection_evidence"]["test_task"]
        self.assertEqual(len(evidence["rows"]), 1)
        self.assertEqual(evidence["rows"][0]["sample_intervals"], [[32000, 32256]])

    def test_continue_independent_preserves_failed_vs_completed(self):
        second = copy.deepcopy(self.task); second["task_id"] = "second"
        self.request["payload"]["tasks"].append(second)
        self.request["payload"]["batch_failure_policy"] = "continue_independent"
        actual = core.execute
        def fail_first(task, *args, **kwargs):
            if task["task_id"] == "test_task":
                raise ArithmeticError("Synthetic failure")
            return actual(task, *args, **kwargs)
        with patch.object(core, "execute", side_effect=fail_first):
            result = self.execute()["result"]["payload"]
        self.assertEqual(result["delivery_status"], "partial")
        self.assertIsNone(result["task_results"][0]["candidates"])
        self.assertEqual(result["task_results"][1]["execution_status"], "completed")
        self.assertEqual(json.loads((self.base/"output/package-manifest.json").read_text())["status"], "partial")

    def test_source_mutation_during_write_leaves_no_completion_marker(self):
        original = runtime.publish
        def intercepted(directory, files, marker, maximum, root, before_marker=None):
            def alter():
                with (self.root/"noise/signal_000000.npy").open("ab") as handle:
                    handle.write(b"changed during write")
                before_marker()
            return original(directory, files, marker, maximum, root, alter)
        with patch.object(runtime, "publish", side_effect=intercepted), self.assertRaises(ValueError):
            self.execute()
        self.assertTrue((self.base/"output").is_dir())
        self.assertFalse((self.base/"output/package-manifest.json").exists())

    def test_saved_contract_references_have_actual_byte_hashes(self):
        self.task["products"] = {"compute": ["candidates", "ledger"], "view": [], "save": ["candidates"]}
        result = self.execute()["result"]["payload"]
        out = self.base/"output"
        for name in ("request_ref", "resolved_configuration", "association_ref"):
            ref = result[name]; self.assertEqual(sha(out/ref["location"]["path"]), ref["sha256"])
        artifact = result["task_results"][0]["artifacts"][0]
        self.assertEqual(sha(out/artifact["file_ref"]["location"]["path"]), artifact["file_ref"]["sha256"])
        self.assertEqual(result["task_results"][0]["artifacts"][1]["status"], "not_retained")
        self.assertFalse((out/"task-000000/ledger").exists())

    def test_registry_export_real_digest_no_overwrite(self):
        path = self.base/"exported-descriptor.json"
        cmd = [sys.executable, "-B", str(ROOT/"scripts/cfar_registry.py"), "ca_cfar", "--out", str(path)]
        child = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        self.assertEqual(child.returncode, 0, child.stdout+child.stderr)
        self.assertEqual(json.loads(path.read_text()), registry.descriptor("ca_cfar"))
        child = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        self.assertNotEqual(child.returncode, 0)

    def test_calibration_target_cannot_reuse_h0_training_support(self):
        cfg = self.calibration_config()
        cfg["target_request"]["payload"]["tasks"][0]["scope"]["sample_intervals"] = [[0, 128]]
        r = calibration.review(cfg, self.root)
        self.assertEqual(r["status"], "blocked")
        self.assertTrue(any("overlap" in v for v in r["issues"]))

    def test_followup_parent_identity_and_package_are_protected(self):
        cfg = self.followup_fixture()
        cfg["result_record_path"] = str(self.base/"output/new-log.json")
        with self.assertRaisesRegex(ValueError, "parent-result"):
            associations.review_followup(cfg)

    def test_cli_review_and_unconfirmed_run(self):
        req = self.base/"request.json"; req.write_bytes(products.json_bytes(self.request))
        ctx = self.base/"context.json"; ctx.write_bytes(products.json_bytes(self.context))
        command = [sys.executable, "-B", str(ROOT/"scripts/detection_runtime.py"), "review", str(req), str(ctx), "--source-root", str(self.root)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "ready_pending_execution_confirmation")
        command[3] = "run"; result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)


class CliFailureSignals(unittest.TestCase):
    """Structured failure remains machine-visible as a nonzero CLI exit."""
    def invoke(self, module, argv, operation, result):
        import contextlib
        import io
        with patch.object(sys, "argv", argv), patch.object(pf, "explicit_json", return_value={}), \
                patch.object(module, operation, return_value=result), contextlib.redirect_stdout(io.StringIO()) as output:
            with self.assertRaises(SystemExit) as exit:
                module.main()
        self.assertEqual(exit.exception.code, 2)
        return json.loads(output.getvalue())

    def test_detection_cli_blocked_and_partial_exit_nonzero(self):
        for action, result in (("review", {"status": "blocked"}), ("run",
                {"result": {"payload": {"delivery_status": "partial"}}, "files": {}, "views": {}})):
            self.invoke(runtime, ["runtime", action, "request", "context", "--source-root", "/inputs",
                "--receipt", "receipt"], action, result)

    def test_calibration_cli_not_qualified_and_blocked_exit_nonzero(self):
        for action, result in (("review", {"status": "blocked"}), ("run",
                {"record": {"status": "not_qualified"}, "files": {}})):
            self.invoke(calibration, ["calibration", action, "config", "--source-root", "/inputs",
                "--receipt", "receipt"], action, result)

    def test_followup_cli_failed_and_blocked_exit_nonzero(self):
        for action, operation, result in (("review-followup", "review_followup", {"status": "blocked"}),
                ("run-followup", "run_followup", {"status": "failed"})):
            self.invoke(associations, ["association", action, "config", "--receipt", "receipt"], operation, result)


if __name__ == "__main__":
    unittest.main()
