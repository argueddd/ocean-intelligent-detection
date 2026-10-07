"""Synthetic fixtures/MOCK approvals only. Not authorization for real data."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from scipy.signal import get_window, periodogram, welch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import execute as runner
import result_products as products
import analyze_results as post
from test_numerical import numerical_fixture, mock_confirm


def settings(length=128, hop=32, nfft=128, band=(0, 1000)):
    return {"profile": "reconstructed_waveform_psd_v1", "window": "hann",
            "window_periodic": True, "window_samples": length, "hop_samples": hop,
            "nfft": nfft, "band_hz": list(band), "detrend": "none",
            "frame_origin": "output_sample_zero",
            "validity": "complete_frames_all_samples_valid",
            "scaling": "onesided_density", "time_average": "arithmetic_mean_linear",
            "frequency_integration": "bin_sum_df",
            "display": {"scale": "shared_peak_db_per_quantity",
                        "limits": "shared_finite_range", "zero_power": "mask"}}


def approve_post(cfg):
    cfg["approval"] = {"status": "confirmed", "scope_sha256": post.fingerprint(cfg),
        "evidence": "SYNTHETIC TEST ONLY",
        "confirmation": {"method": "user", "reference": "MOCK TEST ONLY"}}
    return cfg


class ProductMathTests(unittest.TestCase):
    def setUp(self):
        self.x = np.random.default_rng(17).normal(size=(2048, 3))
        self.valid = np.ones(len(self.x), bool)

    def test_periodogram_oracle_even_odd_padding(self):
        for nfft in (128, 129, 256):
            a = settings(nfft=nfft)
            actual = products.compute(self.x, self.valid, 2000, a, 5.0)
            for row in (0, 1, len(actual["frame_start_sample"]) - 1):
                start = actual["frame_start_sample"][row]
                f, expected = periodogram(self.x[start:start+128], fs=2000,
                    window=get_window("hann", 128, fftbins=True), nfft=nfft,
                    detrend=False, return_onesided=True, scaling="density", axis=0)
                np.testing.assert_allclose(actual["time_frequency_psd"][row], expected, rtol=2e-13, atol=1e-16)
                np.testing.assert_allclose(actual["frequency_hz"], f)

    def test_psd_matches_welch(self):
        a = settings()
        result = products.compute(self.x, self.valid, 2000, a, 0)
        _, expected = welch(self.x, fs=2000, window=get_window("hann", 128),
                            nperseg=128, noverlap=96, nfft=128,
                            detrend=False, scaling="density", axis=0, average="mean")
        np.testing.assert_allclose(result["psd"], expected, rtol=1e-13, atol=1e-17)

    def test_band_integration_parseval_and_reductions(self):
        a = settings()
        r = products.compute(self.x, self.valid, 2000, a, 0)
        win = get_window("hann", 128)
        for i, start in enumerate(r["frame_start_sample"]):
            expected = np.sum((self.x[start:start+128]*win[:,None])**2, axis=0) / np.sum(win**2)
            np.testing.assert_allclose(r["btr_power"][i], expected, rtol=1e-13)
        np.testing.assert_allclose(r["scan_power"], r["psd"].sum(axis=0)*2000/128)
        np.testing.assert_allclose(r["psd"], r["time_frequency_psd"].mean(axis=0))

    def test_dc_nyquist_are_not_doubled(self):
        x = np.column_stack((np.ones(2048), (-1.)**np.arange(2048)))
        a = settings(); a["window"] = "boxcar"
        r = products.compute(x, self.valid, 2000, a, 0)
        np.testing.assert_allclose(r["btr_power"], 1.0, atol=1e-14)

    def test_mask_excludes_edges_and_gap_without_compressing_time(self):
        valid = self.valid.copy(); valid[:200] = False; valid[800:901] = False; valid[-200:] = False
        r = products.compute(self.x, valid, 2000, settings(), 17)
        for start in r["frame_start_sample"]:
            self.assertTrue(valid[start:start+128].all())
        self.assertTrue(np.any(np.diff(r["frame_start_sample"]) > 32))
        np.testing.assert_allclose(r["time_seconds"], 17+(r["frame_start_sample"]+63.5)/2000)

    def test_no_valid_full_frame_fails(self):
        with self.assertRaises(ValueError):
            products.compute(self.x, np.zeros(len(self.x),bool), 2000, settings(), 0)

    def test_nonfinite_rejected(self):
        self.x[300,1] = np.nan
        with self.assertRaises(ValueError):
            products.compute(self.x, self.valid, 2000, settings(), 0)

    def test_band_selection_exact_centers(self):
        r = products.compute(self.x,self.valid,2000,settings(band=(40,450)),0)
        self.assertTrue(np.all((r["frequency_hz"]>=40)&(r["frequency_hz"]<=450)))
        np.testing.assert_allclose(r["btr_power"],r["time_frequency_psd"].sum(axis=1)*2000/128)

    def test_common_db_reference_preserves_algorithm_level_difference(self):
        scale = products.shared_scale([np.array([1.,10.]),np.array([.1,1.])])
        self.assertEqual(scale["reference_linear"],10)
        np.testing.assert_allclose(products.display_db(np.array([1.,.1]),scale),[-10,-20])

    def test_zero_db_is_masked_without_log_warning(self):
        scale = products.shared_scale([np.zeros((2,3))])
        self.assertTrue(scale["all_zero"])
        self.assertTrue(products.display_db(np.zeros((2,3)),scale).mask.all())

    def test_cell_edges_keep_singleton_visible_and_nonuniform_coordinates(self):
        np.testing.assert_allclose(products.cell_edges([12.0], .25), [11.875,12.125])
        np.testing.assert_allclose(products.cell_edges([0., 5., 20.], 1), [-2.5,2.5,12.5,27.5])

    def test_render_single_frame_and_single_beam(self):
        x = self.x[:128,:1]
        a = settings()
        values = products.compute(x, np.ones(128,bool), 2000, a, 0)
        arrays={}; products.attach(arrays,"cbf",values)
        with tempfile.TemporaryDirectory() as td:
            output=products.render(Path(td),arrays,["cbf"],np.array([[0.]]),
                                   {"parameterization":"array_angle"},"SYNTHETIC SINGLETON",a,2000)
            self.assertEqual(len(output["figures"]),4)
            self.assertTrue(all((Path(td)/p).stat().st_size>1000 for p in output["figures"]))

    def test_frequency_angle_alias_and_shared_coordinates(self):
        r = products.compute(self.x,self.valid,2000,settings(),0)
        arrays={}; products.attach(arrays,"cbf",r)
        md=products.metadata(settings(),arrays,["cbf"],"unknown")
        self.assertEqual(md["per_algorithm"]["cbf"]["psd"]["path"],md["per_algorithm"]["cbf"]["frequency_angle"]["path"])
        other=copy.deepcopy(r); other["time_seconds"]+=1
        with self.assertRaises(ValueError): products.attach(arrays,"mvdr",other)


class OutputIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.folder=Path(self.tmp.name)
        self.cfg=numerical_fixture(self.folder); self.p=self.cfg["plan"]
        self.cfg["numerics"].update(max_working_bytes=1000000000,max_artifact_bytes=300000000)
        self.dest=Path(self.p["output"]["directory"])

    def tearDown(self):
        self.tmp.cleanup()

    def with_products(self,indices):
        self.p["output"].update(auxiliary_products=products.PRODUCTS.copy(),
            time_domain_beam_indices=indices,save_time_domain=bool(indices))
        self.cfg["analysis"]=settings(band=self.p["processing"]["band_hz"])
        return mock_confirm(self.cfg)

    def test_missing_retention_stops_before_read_or_calculation(self):
        del self.p["output"]["time_domain_beam_indices"]; mock_confirm(self.cfg)
        with patch.object(runner.np,"load",side_effect=AssertionError("must not read")), patch.object(runner.core,"analyze",side_effect=AssertionError("must not calculate")):
            with self.assertRaises(runner.ExecutionBlocked): runner.execute(self.cfg)
        self.assertFalse(self.dest.exists())

    def test_invalid_retention(self):
        for indices in ([2], [0,0], [True]):
            with self.subTest(indices=indices):
                self.p["output"]["time_domain_beam_indices"]=indices; mock_confirm(self.cfg)
                self.assertFalse(runner.check(self.cfg)["can_attempt_execution"])

    def test_retention_order_is_explicit(self):
        self.p["output"]["time_domain_beam_indices"]=[1,0]; mock_confirm(self.cfg)
        r=runner.execute(self.cfg)
        self.assertEqual([b["scan_column"] for b in r["beams"]],[1,0])
        self.assertEqual([b["direction_deg"] for b in r["beams"]],[[20],[0]])

    def test_single_saved_beam_keeps_second_axis(self):
        self.p["output"]["time_domain_beam_indices"]=[1]; mock_confirm(self.cfg)
        r=runner.execute(self.cfg)
        self.assertEqual(np.load(self.dest/"cbf_time.npy").shape,(4096,1))
        self.assertEqual(r["shape_per_algorithm"],[4096,1])

    def test_old_executor_config_cannot_silently_save_all(self):
        self.cfg["execution_version"]="0.3"; self.p["schema_version"]="0.2"
        self.p["output"]["beam_selection"]="all_requested"
        del self.p["output"]["time_domain_beam_indices"]; mock_confirm(self.cfg)
        self.assertFalse(runner.check(self.cfg)["can_attempt_execution"])

    def test_unconfirmed_analysis_stops(self):
        self.with_products([])
        self.cfg["analysis"]["window_samples"]=64
        self.assertFalse(runner.check(self.cfg)["can_attempt_execution"])

    def test_missing_analysis_stops(self):
        self.with_products([]); del self.cfg["analysis"]; mock_confirm(self.cfg)
        self.assertFalse(runner.check(self.cfg)["can_attempt_execution"])

    def test_analysis_budget_checked_before_waveform(self):
        self.with_products([])
        self.cfg["numerics"]["max_artifact_bytes"]=1; mock_confirm(self.cfg)
        with patch.object(runner.np,"load",side_effect=AssertionError("must not read")):
            with self.assertRaises(runner.ExecutionBlocked): runner.execute(self.cfg)

    def test_products_no_time_files_and_hashes(self):
        self.with_products([])
        result=runner.execute(self.cfg)
        self.assertFalse(list(self.dest.glob("*_time.npy")))
        self.assertIsNone(result["shape_per_algorithm"]); self.assertEqual(result["beams"],[])
        for algo in self.p["algorithms"]:
            tf=np.load(self.dest/(algo+"_time_frequency_psd.npy"))
            psd=np.load(self.dest/(algo+"_psd.npy"))
            np.testing.assert_allclose(psd,tf.mean(axis=0))
        self.assertEqual(len(result["presentation"]["figures"]),7)
        for artifact in result["artifacts"]:
            self.assertEqual(runner.file_digest(self.dest/artifact["path"]),artifact["sha256"])
        self.assertTrue((self.dest/"index.html").is_file())

    def test_plot_failure_does_not_publish_completion(self):
        self.with_products([])
        with patch.object(products,"render",side_effect=OSError("MOCK plot fail")):
            with self.assertRaises(OSError): runner.execute(self.cfg)
        self.assertFalse((self.dest/"result.json").exists())
        self.assertTrue((self.dest/"failure.json").exists())

    def post_config(self):
        mock_confirm(self.cfg); runner.execute(self.cfg)
        path=self.dest/"result.json"
        return approve_post({"product_version":"0.4",
            "source_result":{"path":str(path),"sha256":runner.file_digest(path)},
            "output_directory":str(self.folder/"post"),"time_domain_beam_indices":[],
            "analysis":settings(band=self.p["processing"]["band_hz"]),
            "max_working_bytes":1000000000,"max_artifact_bytes":300000000,
            "title":"SYNTHETIC TEST ONLY"})

    def test_postprocess_preserves_original_and_writes_no_time(self):
        cfg=self.post_config()
        before={p.name:runner.file_digest(p) for p in self.dest.iterdir() if p.is_file()}
        r=post.execute(cfg); dest=Path(cfg["output_directory"])
        self.assertFalse(list(dest.glob("*_time.npy")))
        self.assertFalse(r["beamforming_recomputed"])
        self.assertEqual(before,{p.name:runner.file_digest(p) for p in self.dest.iterdir() if p.is_file()})
        for a in r["artifacts"]: self.assertEqual(runner.file_digest(dest/a["path"]),a["sha256"])

    def test_post_missing_retention_stops(self):
        cfg=self.post_config(); del cfg["time_domain_beam_indices"]; approve_post(cfg)
        with patch.object(post.np,"load",side_effect=AssertionError("must not read")):
            with self.assertRaises(runner.ExecutionBlocked): post.execute(cfg)

    def test_post_tamper_rejected(self):
        cfg=self.post_config()
        arr=np.load(self.dest/"cbf_time.npy"); arr[0,0]+=1; np.save(self.dest/"cbf_time.npy",arr)
        with self.assertRaises(ValueError): post.execute(cfg)
        self.assertFalse(Path(cfg["output_directory"]).exists())


if __name__=="__main__": unittest.main()
