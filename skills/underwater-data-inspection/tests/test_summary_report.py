"""Delivery summaries retain numeric evidence and the limits of small generated fixtures."""
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"scripts"))
from acoustic_inspection.pipeline import execute, _write_summary


class SummaryReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="acoustic-summary-")
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def assert_concise_evidence(self, out):
        text = (out/"summary.md").read_text(encoding="utf-8")
        self.assertLess(len(text), 2200)
        self.assertLess(len(text.splitlines()), 60)
        self.assertNotRegex(text, r"dtype|byteorder|padding|数据类型|大端|小端|尾部填充")
        self.assertNotRegex(text, r"数据合格|检测成功|工程验收通过")
        for target in re.findall(r"\]\(([^)]+)\)", text):
            self.assertTrue((out/target).is_file(), target)
        self.assertTrue((out/"report.md").is_file(), "technical evidence must remain available")
        return text

    def test_probe_and_ambiguous_read_deliver_structure_without_invented_quality(self):
        source = self.root/"ambiguous.npz"
        np.savez(source, hydrophones=np.ones((3, 200)), candidate=np.ones((200, 3)))
        with patch("acoustic_inspection.pipeline.Source", side_effect=AssertionError("must not decode ambiguous arrays")):
            probed = execute(source, self.root/"probe", probe_only=True)
            blocked = execute(source, self.root/"blocked", {"sample_axis": 0})
        probe_text = self.assert_concise_evidence(self.root/"probe")
        blocked_text = self.assert_concise_evidence(self.root/"blocked")
        self.assertEqual(probed["status"], "completed")
        self.assertEqual(blocked["status"], "needs_input")
        self.assertIn("hydrophones", probe_text)
        self.assertIn("[3, 200]", probe_text)
        self.assertIn("尚未执行样本质量检查", probe_text)
        self.assertIn("请确认要处理的字段", blocked_text)
        self.assertNotIn("NaN 0", blocked_text, "unread data cannot be declared free of nonfinite samples")
        missing = execute(self.root/"missing.npy", self.root/"missing", probe_only=True)
        self.assertEqual(missing["status"], "failed")
        self.assertIn("执行失败", self.assert_concise_evidence(self.root/"missing"))

    def test_nonfinite_channel_is_counted_and_excluded_from_peak_claims(self):
        fs = 128
        t = np.arange(128)/fs
        x = np.column_stack([np.sin(2*np.pi*16*t), np.sin(2*np.pi*32*t)])
        x[20, 1] = np.nan
        source = self.root/"nonfinite.npy"
        np.save(source, x)
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        out = self.root/"analysis"
        result = execute(source, out, {"mode": "analyze", "sample_axis": 0, "sample_rate_hz": fs, "nperseg": 64})
        text = self.assert_concise_evidence(out)
        self.assertEqual(result["status"], "partial")
        self.assertIn("NaN 1，Inf 0", text)
        self.assertIn("未获得频谱的通道：1", text)
        peak_rows = re.findall(r"^\| (\d+) \| ([\d.]+) \|$", text, flags=re.M)
        self.assertEqual(peak_rows, [("0", "16")], "a skipped channel must not acquire a guessed peak")
        self.assertIn("未插值或拼接", text)
        self.assertEqual(before, hashlib.sha256(source.read_bytes()).hexdigest())

    def test_valid_partial_spectra_keep_request_coverage_and_exact_peak_evidence(self):
        fs = 256
        t = np.arange(1027)/fs
        source = self.root/"array.npy"
        np.save(source, np.column_stack([np.sin(2*np.pi*f*t) for f in (16, 32, 48)]))
        out = self.root/"analysis"
        result = execute(source, out, {"mode": "analyze", "sample_axis": 0, "sample_rate_hz": fs,
            "start_sample": 10, "stop_sample": 900, "analysis_max_samples": 257,
            "analysis_max_channels": 2, "nperseg": 128})
        text = self.assert_concise_evidence(out)
        self.assertIn("每通道 1,027 个样本，3 路", text)
        self.assertIn("请求样本 [10, 900)", text)
        self.assertIn("实际检查：样本 [10, 900)", text)
        self.assertIn("实际读取样本 [10, 267)", text)
        self.assertIn("完整谱窗口覆盖 [10, 266)", text)
        self.assertIn("有 1 个已读取样本未进入完整谱窗口", text)
        self.assertIn("局部结果不能推广", text)
        self.assertEqual(re.findall(r"^\| (\d+) \| ([\d.]+) \|$", text, flags=re.M), [("0", "16"), ("1", "32")])
        psd = next(item for item in result["checks"] if item["id"] == "analysis.psd")
        self.assertEqual(psd["status"], "partial")
        stored = json.loads((out/"result.json").read_text())
        self.assertEqual(stored["schema_version"], "0.2")
        self.assertEqual(len(stored["checks"]), 21)
        report_before = (out/"report.md").read_bytes()
        # Re-export is based solely on existing evidence, even if the source is unavailable.
        source.unlink()
        _write_summary(out, result)
        self.assertEqual((out/"summary.md").read_text(), text)
        self.assertEqual((out/"report.md").read_bytes(), report_before)
        _write_summary(out, {**result, "status": "failed", "results_valid": False})
        invalid = self.assert_concise_evidence(out)
        self.assertIn("本次证据失效", invalid)
        self.assertNotRegex(invalid, re.compile(r"^\| \d+ \|", re.M), "invalidated spectra must not become delivery evidence")


if __name__ == "__main__":
    unittest.main()
