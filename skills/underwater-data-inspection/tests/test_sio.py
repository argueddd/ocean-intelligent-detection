"""Synthetic SIO fixtures independent of reader indexing, including record edges."""
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"scripts"))
from acoustic_inspection.readers import InputRequired, Source, probe, select_field
from acoustic_inspection.pipeline import execute, validate_config


class SioTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="sio-test-")
        self.root = Path(self.temp.name)
        self.serial = 0

    def tearDown(self):
        self.temp.cleanup()

    def fixture(self, order=">", code="f4", updates=None):
        self.serial += 1
        p = self.root/f"fixture{self.serial}.sio"
        dt = np.dtype(order+code)
        points, nc, groups = 128//dt.itemsize, 3, 3
        n = points*groups-7
        expected = (np.arange(n*nc).reshape(n, nc)-37).astype(dt)
        header = [10, nc*groups, 128, nc, dt.itemsize, 1 if code == "f4" else 0, n, 32677]
        for k, v in (updates or {}).items():
            header[k] = v
        raw = struct.pack(order+"8i", *header)+b"fixture".ljust(24, b"\0")+b"test only".ljust(72, b"\0")
        with p.open("wb") as f:
            f.write(raw)
            # Construct each record individually from known sample/channel values.
            for group in range(groups):
                for ch in range(nc):
                    values = np.full(points, 9999, dtype=dt)
                    chunk = expected[group*points:(group+1)*points, ch]
                    values[:len(chunk)] = chunk
                    f.write(values.tobytes())
        return p, expected, points

    def source(self, p):
        info = probe(p)
        cfg = validate_config({})
        return Source(p, info, select_field(info, cfg), cfg)

    def assert_code(self, p, code):
        with self.assertRaises(InputRequired) as caught:
            probe(p)
        self.assertEqual(caught.exception.code, code)

    def test_endian_numeric_types_and_all_record_edges(self):
        for order in (">", "<"):
            for code in ("f4", "i2"):
                with self.subTest(order=order, code=code):
                    p, expected, q = self.fixture(order, code)
                    s = self.source(p)
                    try:
                        for start, stop in [(0, len(expected)), (0, 1), (q-1, q+2),
                                            (q, q+1), (2*q-1, 2*q+3),
                                            (len(expected)-1, len(expected))]:
                            got = s.read(start, stop, [0, 2])
                            np.testing.assert_array_equal(got, expected[start:stop, [0, 2]])
                            self.assertEqual(got.dtype, expected.dtype)
                    finally:
                        s.close()

    def test_padding_excluded_and_no_source_change(self):
        p, expected, _ = self.fixture()
        before = hashlib.sha256(p.read_bytes()).hexdigest()
        r = execute(p, self.root/"out", {"block_samples": 17})
        self.assertEqual(r["status"], "completed")
        self.assertEqual(r["probe"]["sio_header"]["padding_samples_per_channel"], 7)
        self.assertEqual(r["dataset"]["view_shape"], list(expected.shape))
        for ch, row in enumerate(r["quality"]["channels"]):
            self.assertEqual(row["sample_count"], len(expected))
            self.assertAlmostEqual(row["mean"], float(expected[:, ch].astype(float).mean()))
        self.assertEqual(before, hashlib.sha256(p.read_bytes()).hexdigest())
        self.assertEqual(r["dataset"]["sample_axis_source"], "SIO format")
        self.assertIn("decode SIO channel records; exclude header-declared padding", r["dataset"]["transformations"])

    def test_missing_fs_blocks_frequency_not_quality(self):
        p, _, _ = self.fixture()
        r = execute(p, self.root/"out", {"mode": "analyze"})
        self.assertEqual(r["status"], "partial")
        self.assertIn("quality", r)
        self.assertNotIn("analysis", r)
        self.assertEqual(r["dataset"]["sample_rate_hz"]["state"], "missing")
        self.assertEqual(r["dataset"]["units"]["state"], "missing")
        self.assertEqual(r["dataset"]["channel_identity"]["state"], "missing")

    def test_conflicting_axis_rejected(self):
        p, _, _ = self.fixture()
        r = execute(p, self.root/"out", {"sample_axis": 1})
        self.assertEqual(r["status"], "needs_input")
        self.assertEqual(r["issues"][-1]["code"], "axis_conflict")

    def test_probe_does_not_infer_experiment_identity(self):
        p, _, _ = self.fixture()
        r = probe(p)
        self.assertNotIn("header_sample_rate_hz", r)
        self.assertEqual(r["fields"][0]["field"], "data")
        self.assertNotIn("channel_ids", r)

    def test_bad_magic_stops(self):
        p, _, _ = self.fixture(updates={7: 99})
        self.assert_code(p, "invalid_sio_magic")

    def test_short_header_stops(self):
        p = self.root/"short.sio"
        p.write_bytes(b"short")
        self.assert_code(p, "truncated_sio_header")

    def test_unknown_id_stops(self):
        p, _, _ = self.fixture(updates={0: 9})
        self.assert_code(p, "unsupported_sio_variant")

    def test_unknown_dtype_pair_stops(self):
        p, _, _ = self.fixture(updates={5: 0})
        self.assert_code(p, "unsupported_sio_dtype")

    def test_incomplete_channel_record_group_stops(self):
        p, _, _ = self.fixture(updates={1: 8})
        self.assert_code(p, "invalid_sio_structure")

    def test_bad_sample_count_stops(self):
        for n in (0, 1, 1000):
            with self.subTest(n=n):
                p, _, _ = self.fixture(updates={6: n})
                self.assert_code(p, "invalid_sio_structure" if n == 0 else "invalid_sio_sample_count")

    def test_trailing_or_missing_bytes_stop(self):
        for delta in (-1, 1):
            p, _, _ = self.fixture()
            b = p.read_bytes()
            p.write_bytes(b[:-1] if delta == -1 else b+b"!")
            self.assert_code(p, "sio_size_mismatch")

    def test_truncation_after_probe_is_detected(self):
        p, _, _ = self.fixture()
        s = self.source(p)
        p.write_bytes(p.read_bytes()[:128])
        try:
            with self.assertRaises(InputRequired) as caught:
                s.read(0, 1, [0])
            self.assertEqual(caught.exception.code, "truncated_sio_data")
        finally:
            s.close()

    def test_invalid_slice_is_not_truncated(self):
        p, expected, _ = self.fixture()
        s = self.source(p)
        try:
            with self.assertRaises(InputRequired):
                s.read(0, len(expected)+1, [0])
        finally:
            s.close()


if __name__ == "__main__":
    unittest.main()
