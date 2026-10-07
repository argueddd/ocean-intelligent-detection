"""Synthetic contraction compatibility regressions; no real-data approvals."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import warnings
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import beamforming_core as core
import execute as runner
from test_numerical import numerical_fixture, mock_confirm


class ContractionCompatibilityTests(unittest.TestCase):
    def test_steering_large_noncontiguous_vectors_scalar_truth(self):
        # Large synthetic shape exercises the former Accelerate transposed-GEMM path.
        rng = np.random.default_rng(17)
        coordinates = rng.normal(size=(28,3))*90
        reference = np.array([2.,3.,4.])
        vectors = rng.normal(size=(72,6))[:,::2]
        vectors /= np.linalg.norm(vectors,axis=1,keepdims=True)
        frequencies = np.array([0.,64.,400.])
        expected = np.array([[-sum(float(coordinates[m,k]-reference[k])*float(vectors[b,k])
                                for k in range(3))/1490
                              for b in range(72)] for m in range(28)])
        with warnings.catch_warnings():
            warnings.simplefilter("error",RuntimeWarning)
            response, delays = core.steering(frequencies,coordinates,reference,vectors,1490)
        np.testing.assert_allclose(delays,expected,rtol=1e-14,atol=1e-15)
        np.testing.assert_allclose(response,np.exp(-2j*np.pi*frequencies[:,None,None]*expected),
                                   rtol=1e-12,atol=1e-12)

    def test_vertical_scale_37_directions_without_runtime_warning(self):
        # Nominal synthetic vertical line, not S59 data or real-data authorization.
        z = np.linspace(0,-120,21)
        coordinates = np.column_stack((np.zeros(21),np.zeros(21),z))
        theta = np.deg2rad(np.arange(-90,91,5))
        vectors = np.column_stack((np.cos(theta),np.zeros(37),np.sin(theta)))
        with warnings.catch_warnings():
            warnings.simplefilter("error",RuntimeWarning)
            _, delays = core.steering(np.array([100.]),coordinates,[0,0,0],vectors,1500)
        np.testing.assert_allclose(delays,-z[:,None]*np.sin(theta)[None,:]/1500,atol=1e-16)

    def test_saved_cbf_and_mvdr_match_scalar_channel_sum(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = numerical_fixture(Path(td))
            cfg["plan"]["direction_plan"]["directions_deg"] = [[float(a)] for a in range(-90,91,5)]
            cfg["plan"]["output"]["time_domain_beam_indices"] = list(range(37))
            cfg["numerics"]["max_working_bytes"] = 1000000000
            cfg["numerics"]["max_artifact_bytes"] = 300000000
            mock_confirm(cfg)
            with warnings.catch_warnings():
                warnings.simplefilter("error",RuntimeWarning)
                result = runner.execute(cfg)
            out = Path(cfg["plan"]["output"]["directory"])
            x = np.load(cfg["plan"]["input"]["source"]["path"])
            x = runner.preprocess(x,cfg["plan"]["processing"]["preprocessing"])
            spectra, starts = core.analyze(x,cfg["plan"]["transform"])
            for algo in ("cbf","mvdr"):
                w = np.load(out/(algo+"_weights.npy"))
                y = np.zeros((len(starts),spectra.shape[1],37),complex)
                if algo == "cbf":
                    for ch in range(x.shape[1]):
                        y += spectra[:,:,ch,None]*w[:,ch,:].conj()[None,:,:]
                else:
                    updates = np.load(out/"mvdr_update_frame.npy")
                    for j,first in enumerate(updates):
                        end = int(updates[j+1]) if j+1<len(updates) else len(starts)
                        for ch in range(x.shape[1]):
                            y[first:end] += spectra[first:end,:,ch,None]*w[j,:,ch,:].conj()[None,:,:]
                expected = core.synthesize(y,starts,len(x),cfg["plan"]["transform"],1e-12)
                saved = np.load(out/(algo+"_time.npy"))
                np.testing.assert_allclose(saved,expected,rtol=1e-12,atol=1e-13)
            self.assertEqual(result["execution_status"],"completed")

    def test_cli_runtime_warning_is_structured_failure(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/"mock.json"
            path.write_text("{}")
            stream = io.StringIO()
            with patch.object(runner,"execute",side_effect=RuntimeWarning("synthetic failure")), contextlib.redirect_stderr(stream):
                status = runner.main(["run",str(path)])
            self.assertEqual(status,1)
            result=json.loads(stream.getvalue())
            self.assertFalse(result["usable"])
            self.assertEqual(result["execution_status"],"failed")


if __name__ == "__main__":
    unittest.main()
