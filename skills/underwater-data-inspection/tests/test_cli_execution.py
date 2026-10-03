"""Execution preparation preserves ambiguity, input boundaries and old CLI contracts."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
import wave

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"scripts"))
from acoustic_inspection.execution import (execute_request, existing_figure_paths,
    numeric_summary, resolve_input, select_file)
from acoustic_inspection.readers import InputRequired
from inspect_data import parse_json


class ExecutionCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="inspection-cli-")
        self.root = Path(self.temp.name).resolve()
        self.data = self.root/"中文 数据.npy"
        x = np.arange(64, dtype=float)
        np.save(self.data, np.column_stack((x, x+1)))
        self.count = 0

    def tearDown(self):
        self.temp.cleanup()

    def request(self, raw_config=None, **overrides):
        self.count += 1
        args = dict(file=self.data, selected_file=None, config=None,
                    config_json=json.dumps(raw_config) if raw_config is not None else None,
                    out=self.root/f"out{self.count}")
        args.update(overrides)
        return SimpleNamespace(**args)

    def test_inline_execute_returns_summary_and_preserves_source(self):
        before = hashlib.sha256(self.data.read_bytes()).digest()
        args = self.request({"sample_axis": 0, "mode": "check", "start_sample": 3,
                             "stop_sample": 11, "channels": [1]})
        response, code = execute_request(args, parse_json)
        self.assertEqual((response["status"], code), ("completed", 0))
        self.assertIn("[3, 11)", response["summary"])
        self.assertIn(str(args.out/"channel_quality.csv"), response["summary"])
        stored = json.loads(Path(response["result"]).read_text())
        self.assertEqual(stored["quality"]["channels"][0]["sample_count"], 8)
        self.assertEqual(stored["input_resolution"]["selected_file"], str(self.data))
        numbers = response["numeric_summary"]
        row = stored["quality"]["channels"][0]
        for key in ("mean", "std_population", "rms", "minimum", "maximum"):
            self.assertEqual(numbers[key+"_range"], [row[key], row[key]])
        self.assertEqual(numbers["zero_count_total"], row["zero_count"])
        self.assertEqual(numbers["longest_constant_run_max_samples"], row["longest_constant_run"]["length"])
        self.assertEqual(numbers["unavailable_channel_fields"], {})
        self.assertEqual(response["figure_paths"], [])
        self.assertEqual(before, hashlib.sha256(self.data.read_bytes()).digest())

    def test_numeric_summary_preserves_missing_and_invalidated_evidence(self):
        rows = [dict(channel_index=0, mean=3.0, rms=4.0, std_population=1e-300,
                     zero_count=0, longest_constant_run={"length": 2}),
                dict(channel_index=1, mean=None, std_population=1e300,
                     zero_count=None, longest_constant_run=None)]
        numbers = numeric_summary(dict(quality={"channels": rows}))
        self.assertEqual(numbers["mean_range"], [3.0, 3.0])
        self.assertIsNone(numbers["zero_count_total"])
        self.assertIsNone(numbers["minimum_range"])
        self.assertIsNone(numbers["longest_constant_run_max_samples"])
        self.assertIsNone(numbers["std_max_min_ratio"])
        self.assertEqual(numbers["unavailable_channel_fields"]["mean"], [1])
        self.assertEqual(numbers["unavailable_channel_fields"]["minimum"], [0, 1])
        json.dumps(numbers, allow_nan=False)
        self.assertEqual(numeric_summary({})["status"], "not_run")
        self.assertEqual(numeric_summary(dict(quality={"channels": rows}, results_valid=False)),
                         {"status": "invalidated"})

    def test_stdout_includes_every_existing_figure_without_another_listing(self):
        x = np.arange(64, dtype=float)
        np.save(self.data, np.column_stack((x, x+1, x+2)))
        args = self.request({"mode": "analyze", "sample_axis": 0,
            "sample_rate_hz": 64, "nperseg": 8, "channels": [0, 1, 2]})
        response, code = execute_request(args, parse_json)
        self.assertEqual(code, 0)
        stored = json.loads(Path(response["result"]).read_text())
        expected = [str((args.out/name).resolve()) for name in stored["analysis"]["artifacts"]
                    if name.endswith(".png")]
        self.assertEqual(len(expected), 5)
        self.assertEqual(response["figure_paths"], expected)
        self.assertTrue(all(Path(p).is_file() and Path(p).is_absolute() for p in expected))
        stored["analysis"]["artifacts"] += ["missing.png", "../outside.png", "psd.png"]
        (self.root/"outside.png").write_bytes(b"outside this result directory")
        self.assertEqual(existing_figure_paths(args.out.resolve(), stored), expected)

    def test_directory_inventory_does_not_choose_data_or_use_configuration(self):
        np.save(self.root/"another.npy", np.ones((16, 3)))
        (self.root/"test.config.json").write_text('{"sample_rate_hz":9876}')
        args = self.request(file=self.root)
        response, code = execute_request(args, parse_json)
        self.assertEqual((response["status"], code), ("needs_input", 2))
        self.assertEqual(response["candidate_count"], 2)
        self.assertEqual(response["configuration_files"], ["test.config.json"])
        self.assertFalse(response["sample_checks_performed"])
        self.assertTrue(all(x["status"] == "structure_probed" for x in response["candidates"]))
        self.assertNotIn("quality", response)
        self.assertNotIn("9876", json.dumps(response))
        self.assertFalse(args.out.exists())

    def test_explicit_directory_file_and_configuration(self):
        config = self.root/"chosen.config.json"
        config.write_text('{"sample_axis":0,"stop_sample":8,"mode":"check"}')
        args = self.request(file=self.root, selected_file=self.data.name, config=Path(config.name))
        response, code = execute_request(args, parse_json)
        self.assertEqual(code, 0)
        r = json.loads(Path(response["result"]).read_text())
        self.assertEqual(r["dataset"]["sample_range"], [0, 8])
        self.assertEqual(r["config"]["source"], str(config))

    def test_directory_file_cannot_escape_through_absolute_traversal_or_link(self):
        folder = self.root/"selected"
        folder.mkdir()
        (folder/"link.npy").symlink_to(self.data)
        for value in (str(self.data), "../"+self.data.name, "link.npy"):
            with self.subTest(value=value), self.assertRaises(InputRequired) as caught:
                select_file(folder, value)
            self.assertEqual(caught.exception.code, "invalid_file_selection")

    def test_volume_alias_is_unique_and_real_path_takes_priority(self):
        volumes = self.root/"Volumes"
        destination = volumes/"T7 Shield"/"Data"
        destination.mkdir(parents=True)
        selected, evidence = resolve_input("/t7-shield/Data", volumes)
        self.assertEqual(selected, destination)
        self.assertEqual(evidence["method"], "unique_volume_alias")
        selected, evidence = resolve_input(self.data, volumes)
        self.assertEqual(selected, self.data)
        self.assertEqual(evidence["method"], "existing_path")
        other = volumes/"t7-shield"/"Data"
        other.mkdir(parents=True)
        with self.assertRaises(InputRequired) as caught:
            resolve_input("/t7-shield/Data", volumes)
        self.assertEqual(caught.exception.code, "ambiguous_input_path")
        with self.assertRaises(InputRequired) as caught:
            resolve_input("/missing-drive/Data", volumes)
        self.assertEqual(caught.exception.code, "input_path_not_found")

    def test_missing_or_invalid_config_does_not_start_analysis(self):
        for config, code in ((None, "config_required"), ({"unknown_parameter": 1}, "unknown_config")):
            args = self.request(config)
            response, exit_status = execute_request(args, parse_json)
            self.assertEqual((response["status"], exit_status), ("needs_input", 2))
            self.assertEqual(response["issues"][0]["code"], code)
            self.assertFalse(args.out.exists())

    def test_unknown_axis_stops_and_missing_fs_only_blocks_frequency(self):
        response, code = execute_request(self.request({"mode": "analyze"}), parse_json)
        self.assertEqual(code, 2)
        self.assertEqual(response["issues"][0]["code"], "sample_axis_required")
        self.assertNotIn("quality", json.loads(Path(response["result"]).read_text()))
        response, code = execute_request(self.request({"mode": "analyze", "sample_axis": 0}), parse_json)
        self.assertEqual((response["status"], code), ("partial", 2))
        r = json.loads(Path(response["result"]).read_text())
        self.assertIn("quality", r)
        self.assertNotIn("analysis", r)
        self.assertEqual(r["dataset"]["sample_rate_hz"]["state"], "missing")

    def test_wav_native_rate_conflict_is_not_silently_overridden(self):
        p = self.root/"wave.wav"
        with wave.open(str(p), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(1000)
            w.writeframes(np.arange(32, dtype="<i2").tobytes())
        response, code = execute_request(self.request({"mode": "analyze", "sample_rate_hz": 2000}, file=p), parse_json)
        self.assertEqual(code, 2)
        r = json.loads(Path(response["result"]).read_text())
        self.assertEqual(r["dataset"]["sample_rate_hz"]["state"], "conflict")
        self.assertNotIn("analysis", r)

    def test_legacy_probe_run_and_execute_stdout_are_valid_json(self):
        script = ROOT/"scripts/inspect_data.py"
        config = self.root/"legacy.json"
        config.write_text('{"sample_axis":0,"mode":"check"}')
        for action in ("probe", "run", "execute"):
            out = self.root/action
            command = [sys.executable, "-B", str(script), action, str(self.data), "--out", str(out)]
            if action == "run": command += ["--config", str(config)]
            if action == "execute": command += ["--config-json", config.read_text()]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            response = json.loads(result.stdout)
            self.assertEqual(response["status"], "completed")
            if action != "execute": self.assertEqual(set(response), {"status", "result", "issues"})
            else: self.assertIn("summary", response)

    def test_existing_outputs_and_malformed_inline_json_are_rejected(self):
        args = self.request({"sample_axis": 0})
        args.out.mkdir()
        (args.out/"kept.txt").write_text("keep")
        response, code = execute_request(args, parse_json)
        self.assertEqual((response["status"], code), ("failed", 1))
        self.assertEqual((args.out/"kept.txt").read_text(), "keep")
        for text in ('{"sample_axis":0,"sample_axis":1}', '{"sample_rate_hz":NaN}'):
            args = self.request(config_json=text)
            response, code = execute_request(args, parse_json)
            self.assertEqual((response["status"], code), ("failed", 1))
            self.assertFalse(args.out.exists())


if __name__ == "__main__":
    unittest.main()
