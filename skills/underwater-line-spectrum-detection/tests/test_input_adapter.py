"""Adapter tests use synthetic-only producer packets; no real user confirmation."""
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import input_adapter as adapter
import preflight as pf
import test_preflight as preflight_fixture

LIMITS = {"max_package_bytes": 8 * 1024**2, "max_block_samples": 1000}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Adapter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture_tmp = tempfile.TemporaryDirectory()
        cls.fixture_root = Path(cls.fixture_tmp.name)
        cls.addClassCleanup(cls.fixture_tmp.cleanup)
        child = subprocess.run([sys.executable, "-B", str(ROOT / "tests" / "adapter_fixture_producer.py"),
                                str(cls.fixture_root)], capture_output=True, text=True, timeout=60)
        if child.returncode:
            raise AssertionError(child.stdout + child.stderr)
        cls.packets = {key: Path(path) for key, path in json.loads(child.stdout).items()}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)

    def prepare(self, name="main"):
        folder = self.base / name
        shutil.copytree(self.packets[name].parent, folder)
        return folder / "handoff.json"

    def adapt(self, path, name="main", signal="signal_000000", **limits):
        return adapter.adapt(path, sha(path), "beamformed_handoff" if name == "main" else "bypass_handoff",
                             signal, **(limits or LIMITS))

    def main_doc(self):
        path = self.prepare()
        result = self.adapt(path)
        return path, result["signal_input"]

    def test_main_explicit_identity_and_columns(self):
        path, doc = self.main_doc()
        p = doc["payload"]
        self.assertEqual(p["beam_source"]["beamformer_algorithm"]["value"], "mvdr")
        self.assertEqual(p["beam_source"]["beam_id"]["value"], "beam_000000")
        self.assertEqual((p["beam_source"]["source_column"], p["beam_source"]["scan_column"]), (1, 0))
        self.assertEqual(p["beam_source"]["direction"]["value"]["angles_deg"], [-20])
        self.assertEqual(p["waveform"]["shape"], [4096, 1])
        self.assertEqual(p["waveform"]["axes"], ["sample", "signal"])
        self.assertEqual(p["waveform"]["file_ref"]["sha256"], sha(path.parent / "signal_000000.npy"))

    def test_second_explicit_signal_is_cbf_not_first(self):
        path = self.prepare()
        p = self.adapt(path, signal="signal_000001")["signal_input"]["payload"]
        self.assertEqual(p["beam_source"]["beamformer_algorithm"]["value"], "cbf")
        self.assertEqual((p["beam_source"]["source_column"], p["beam_source"]["scan_column"]), (0, 2))
        self.assertEqual(p["beam_source"]["direction"]["value"]["angles_deg"], [20])

    def test_time_frequency_mask_and_full_history(self):
        path, doc = self.main_doc()
        m = json.loads(path.read_text()); p = doc["payload"]
        self.assertEqual(json.loads(p["time_mapping"]["time_reference"]), m["provenance"]["time_reference"])
        self.assertEqual(p["sample_rate_hz"], m["provenance"]["sample_rate_hz"])
        self.assertEqual(p["validity"]["sample_intervals"], m["provenance"]["valid_sample_intervals"])
        self.assertEqual(p["frequency_coverage"]["band_hz"], m["provenance"]["frequency_coverage"]["requested_band_hz"])
        self.assertEqual(p["frequency_coverage"]["active_frequency_ref"], p["source_package"]["manifest"])
        recovered = {}
        for entry in p["processing_history"]["steps"]:
            label, raw = entry.split(":", 1)
            recovered[label] = json.loads(raw)
        for section in ("upstream", "this_run"):
            for i, value in enumerate(m["provenance"]["processing_history"][section]):
                self.assertEqual(recovered[section + "[" + str(i) + "]"], value)

    def test_old_files_and_historical_status_remain_unchanged(self):
        path = self.prepare()
        before = {p.name: sha(p) for p in path.parent.iterdir()}
        r = self.adapt(path)
        self.assertFalse(r["can_execute"]); self.assertFalse(r["authority_verified"])
        self.assertEqual(r["detection_status"], "not_run")
        self.assertEqual(before, {p.name: sha(p) for p in path.parent.iterdir()})
        self.assertEqual(json.loads(path.read_text())["handoff_status"], "prepared")

    def test_bypass_single_sensor_preserves_original_time(self):
        name = "single_sensor_known"; path = self.prepare(name)
        p = self.adapt(path, name)["signal_input"]["payload"]
        self.assertEqual(p["data_role"], "single_sensor")
        self.assertEqual(p["beam_source"], {"status": "not_applicable"})
        self.assertEqual(p["time_mapping"]["source_sample_zero"], 7)
        self.assertEqual(p["time_mapping"]["sample_zero_offset_seconds"], 7 / 2000)
        self.assertEqual(p["validity"]["sample_intervals"], [[13, 900], [1003, 4069]])

    def test_bypass_unknown_stays_unknown_and_reports_questions(self):
        name = "beamformed_unknown"; path = self.prepare(name)
        r = self.adapt(path, name); p = r["signal_input"]["payload"]
        for field in ("units", "frequency_coverage", "validity"):
            self.assertEqual(p[field]["status"], "unknown")
        self.assertIsNone(p["validity"]["mask_ref"]); self.assertIsNone(p["validity"]["sample_intervals"])
        for field in ("direction", "beam_id", "beamformer_algorithm"):
            self.assertEqual(p["beam_source"][field]["status"], "unknown")
            self.assertIsNone(p["beam_source"][field]["value"])
        self.assertIsNone(p["beam_source"]["source_result"])
        self.assertIsNone(p["beam_source"]["scan_column"])
        self.assertEqual(p["beam_source"]["source_column"], 1)
        self.assertEqual(len(r["unknown_items"]), 6)
        self.assertTrue(all(x["question"] for x in r["unknown_items"]))

    def test_bypass_known_direction_preserved_but_no_invented_beam_id(self):
        name = "beamformed_known"; path = self.prepare(name)
        p = self.adapt(path, name)["signal_input"]["payload"]
        self.assertEqual(p["beam_source"]["beamformer_algorithm"]["value"], "external_algorithm_not_inferred")
        self.assertEqual(p["beam_source"]["direction"]["value"]["angles_deg"], [12, 3])
        self.assertEqual(p["beam_source"]["beam_id"]["status"], "unknown")
        self.assertEqual(p["frequency_coverage"]["band_hz"], [40, 450])

    def test_source_hash_mismatch_blocked(self):
        path = self.prepare()
        with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
            adapter.adapt(path, "0" * 64, "beamformed_handoff", "signal_000000", **LIMITS)

    def test_wrong_kind_blocked(self):
        path = self.prepare()
        with self.assertRaisesRegex(ValueError, "kind/version"):
            adapter.adapt(path, sha(path), "bypass_handoff", "signal_000000", **LIMITS)

    def test_missing_signal_not_automatically_selected(self):
        path = self.prepare()
        for signal in ("", "missing"):
            with self.subTest(signal=signal), self.assertRaises(ValueError):
                self.adapt(path, signal=signal)

    def test_package_limit_blocked_before_receiver(self):
        path = self.prepare()
        with patch.object(adapter, "run_receiver", side_effect=AssertionError("Must not run")):
            with self.assertRaisesRegex(ValueError, "byte limit"):
                self.adapt(path, max_package_bytes=1, max_block_samples=1000)

    def test_block_limit_not_silently_raised(self):
        path = self.prepare()
        with patch.object(adapter, "run_receiver", side_effect=AssertionError("Must not run")):
            with self.assertRaisesRegex(ValueError, "block_samples"):
                self.adapt(path, max_package_bytes=8000000, max_block_samples=1)

    def test_source_artifact_hash_corruption_blocked(self):
        path = self.prepare(); wave = path.parent / "signal_000000.npy"
        raw = bytearray(wave.read_bytes()); raw[-1] ^= 1; wave.write_bytes(raw)
        with self.assertRaisesRegex(ValueError, "receiver rejected"):
            self.adapt(path)

    def test_nonfinite_waveform_rejected_even_after_rehash(self):
        import numpy as np
        path = self.prepare(); wave = path.parent / "signal_000000.npy"
        data = np.load(wave, allow_pickle=False); data[30, 0] = float("nan"); np.save(wave, data, allow_pickle=False)
        m = json.loads(path.read_text())
        next(a for a in m["artifacts"] if a["path"] == wave.name)["sha256"] = sha(wave)
        path.write_text(json.dumps(m))
        with self.assertRaisesRegex(ValueError, "receiver rejected"):
            self.adapt(path)

    def test_mask_disagreement_rejected_even_after_rehash(self):
        import numpy as np
        path = self.prepare(); mask = path.parent / "valid_sample_mask.npy"
        data = np.load(mask, allow_pickle=False); data[:] = ~data; np.save(mask, data, allow_pickle=False)
        m = json.loads(path.read_text())
        next(a for a in m["artifacts"] if a["path"] == mask.name)["sha256"] = sha(mask)
        path.write_text(json.dumps(m))
        with self.assertRaisesRegex(ValueError, "receiver rejected"):
            self.adapt(path)

    def test_symlink_artifact_rejected(self):
        path = self.prepare(); file = path.parent / "source_config.json"
        moved = self.base / "other.json"; file.rename(moved); file.symlink_to(moved)
        with self.assertRaises(OSError):
            self.adapt(path)

    def test_parent_traversal_rejected(self):
        path = self.prepare(); m = json.loads(path.read_text()); m["artifacts"][0]["path"] = "../secret"
        path.write_text(json.dumps(m))
        with self.assertRaisesRegex(ValueError, "relative"):
            self.adapt(path)

    def test_duplicate_json_key_rejected(self):
        path = self.prepare()
        path.write_text('{"handoff_version":"0.1","handoff_version":"0.1"}')
        with self.assertRaises(ValueError):
            self.adapt(path)

    def test_source_change_during_receiver_blocked(self):
        path = self.prepare(); run = adapter.run_receiver
        def change(*args):
            result = run(*args)
            file = path.parent / "source_config.json"
            file.write_bytes(file.read_bytes() + b" ")
            return result
        with patch.object(adapter, "run_receiver", side_effect=change), self.assertRaisesRegex(ValueError, "changed"):
            self.adapt(path)

    def test_all_payload_fields_checked_not_just_schema(self):
        path, doc = self.main_doc()
        mutations = {
            "fs": lambda p: p.update(sample_rate_hz=p["sample_rate_hz"] + 1),
            "time": lambda p: p["time_mapping"].update(sample_zero_offset_seconds=5),
            "units": lambda p: p["units"].update(status="known", value="invented"),
            "band": lambda p: p["frequency_coverage"].update(band_hz=[0, 999]),
            "mask": lambda p: p["validity"].update(sample_intervals=[[20, 80]]),
            "direction": lambda p: p["beam_source"]["direction"]["value"].update(angles_deg=[12]),
            "saved_column": lambda p: p["beam_source"].update(source_column=99),
            "scan_column": lambda p: p["beam_source"].update(scan_column=99),
            "algorithm": lambda p: p["beam_source"]["beamformer_algorithm"].update(value="cbf"),
            "beam_id": lambda p: p["beam_source"]["beam_id"].update(value="other"),
            "history": lambda p: p["processing_history"].update(steps=["invented filter"]),
            "limitations": lambda p: p.update(limitations=[]),
            "provenance": lambda p: p.update(provenance=p["provenance"][:1]),
        }
        for label, mutate in mutations.items():
            with self.subTest(field=label):
                changed = copy.deepcopy(doc); mutate(changed["payload"])
                self.assertTrue(adapter.contracts.validate_document(changed, "SignalInput")["valid"])
                result = adapter.check_document(changed, path, **LIMITS)
                self.assertEqual(result["adapter_status"], "mismatch")
                self.assertTrue(result["differences"]); self.assertFalse(result["can_execute"])

    def test_relocated_packet_keeps_identity(self):
        path, doc = self.main_doc()
        destination = self.base / "relocated"
        shutil.copytree(path.parent, destination)
        self.assertEqual(adapter.check_document(doc, destination / path.name, **LIMITS)["adapter_status"], "verified")

    def test_no_source_sample_zero_fallback(self):
        path = self.prepare()
        packet = adapter.Packet(path, sha(path), "beamformed_handoff", **LIMITS)
        packet.manifest["provenance"].pop("original_source_sample_range", None)
        doc, _, unknown = adapter.map_input(packet, "signal_000000")
        self.assertIsNone(doc["payload"]["time_mapping"]["source_sample_zero"])
        self.assertIn("/payload/time_mapping/source_sample_zero", [x["field"] for x in unknown])

    def test_duplicate_history_entries_preserved(self):
        path = self.prepare()
        packet = adapter.Packet(path, sha(path), "beamformed_handoff", **LIMITS)
        packet.manifest["provenance"]["processing_history"]["upstream"] = ["same", "same"]
        doc, _, _ = adapter.map_input(packet, "signal_000000")
        self.assertEqual(doc["payload"]["processing_history"]["steps"][:2], ['upstream[0]:"same"', 'upstream[1]:"same"'])

    def test_explicit_new_output_only_and_no_waveform_copy(self):
        path, doc = self.main_doc()
        out = self.base / "SignalInput.json"
        adapter.write_input(doc, out, path)
        self.assertEqual(json.loads(out.read_text()), doc)
        with self.assertRaises(FileExistsError):
            adapter.write_input(doc, out, path)
        with self.assertRaisesRegex(ValueError, "readonly"):
            adapter.write_input(doc, path.parent / "input.json", path)
        self.assertEqual(set(p.name for p in self.base.iterdir()), {"main", "SignalInput.json"})

    def test_cli_no_out_does_not_save(self):
        path = self.prepare(); before = set(self.base.rglob("*"))
        child = subprocess.run([sys.executable, "-B", str(ROOT / "scripts" / "input_adapter.py"), "adapt",
                                "--handoff", str(path), "--sha256", sha(path), "--kind", "beamformed_handoff",
                                "--signal-id", "signal_000000", "--max-package-bytes", "8000000",
                                "--max-block-samples", "1000"], capture_output=True, text=True, timeout=60)
        self.assertEqual(child.returncode, 0, child.stdout + child.stderr)
        self.assertFalse(json.loads(child.stdout)["can_execute"])
        self.assertEqual(before, set(self.base.rglob("*")))

    def test_preflight_opt_in_verifies_and_rejects_forged_metadata(self):
        path, doc = self.main_doc()
        fixture = preflight_fixture.Preflight(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        fixture.source = self.base
        fixture.input = doc
        fixture.descriptor["payload"]["input_requirements"]["data_roles"] = ["beamformed"]
        fixture.context["source_files"] = []
        for file in path.parent.iterdir():
            fixture.context["source_files"].append({"sha256": sha(file), "path": str(file.relative_to(self.base))})
        fixture.context["max_source_bytes"] = 8000000
        fixture.context["handoff_validation"] = LIMITS.copy()
        p = doc["payload"]; task = fixture.request["payload"]["tasks"][0]
        task["input_ref"].update(package_sha256=sha(path), signal_id=p["signal_id"])
        task["scope"].update(sample_intervals=p["validity"]["sample_intervals"],
                             search_band_hz=p["frequency_coverage"]["band_hz"],
                             time_reference=p["time_mapping"]["time_reference"])
        report = fixture.run_review()
        self.assertEqual(report["review_status"], "review_complete_pending_confirmation", report["issues"])
        self.assertNotIn("upstream_adapter_semantics_not_verified", report["execution_blockers"])
        self.assertIn("algorithm_frame_rules_not_verified", report["execution_blockers"])
        self.assertFalse(report["can_execute"])
        original_plan = report["plan_sha256"]
        self.assertEqual(original_plan, fixture.run_review()["plan_sha256"])
        fixture.input["payload"]["sample_rate_hz"] += 10
        report = fixture.run_review()
        self.assertEqual(report["review_status"], "blocked")
        self.assertIn("upstream_adapter_check_failed", fixture.codes(report))
        self.assertNotEqual(original_plan, report["plan_sha256"])

    def test_preflight_old_context_does_not_implicitly_read_packet(self):
        fixture = preflight_fixture.Preflight(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        with patch.object(adapter, "run_receiver", side_effect=AssertionError("No opt-in")):
            report = fixture.run_review()
        self.assertEqual(report["review_status"], "review_complete_pending_confirmation")
        self.assertEqual(report["adapter_checks"], {})
        self.assertIn("upstream_adapter_semantics_not_verified", report["execution_blockers"])



    def test_cli_check_mismatch_and_missing_selection_exit_codes(self):
        path, doc = self.main_doc()
        out = self.base / "input.json"
        adapter.write_input(doc, out, path)
        cmd = [sys.executable, "-B", str(ROOT / "scripts" / "input_adapter.py"), "check", str(out),
               "--handoff", str(path), "--max-package-bytes", "8000000", "--max-block-samples", "1000"]
        child = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        self.assertEqual(child.returncode, 0, child.stdout)
        doc["payload"]["beam_source"]["scan_column"] = 99
        out.write_text(json.dumps(doc))
        child = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        self.assertEqual(child.returncode, 1, child.stdout)
        self.assertEqual(json.loads(child.stdout)["differences"][0]["field"], "/payload/beam_source/scan_column")
        child = subprocess.run(cmd[:3] + ["adapt", "--handoff", str(path)],
                               capture_output=True, text=True, timeout=60)
        self.assertEqual(child.returncode, 2)

    def test_manifest_dtype_conflict_is_not_repaired(self):
        path = self.prepare()
        m = json.loads(path.read_text()); m["dtype"] = "float32"; path.write_text(json.dumps(m))
        with self.assertRaisesRegex(ValueError, "dtype"):
            self.adapt(path)


if __name__ == "__main__":
    unittest.main()
