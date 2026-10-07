"""Synthetic fixtures only. Mock confirmations are NOT user execution authorization."""
import json
from pathlib import Path
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
BEAM = ROOT.parent / "underwater-beamforming"
sys.path.insert(0, str(BEAM / "scripts"))
import preflight
sys.path.insert(0, str(BEAM / "tests"))
import test_v043_acceptance as f

base = Path(sys.argv[1]).resolve()
main = base / "main"; main.mkdir()
cfg = f.numerical_fixture(main)
cfg["plan"]["direction_plan"]["directions_deg"] = [[-20], [0], [20]]
cfg["plan"]["output"].update(time_domain_beam_indices=[2, 0], save_time_domain=True,
    auxiliary_products=["psd", "time_frequency", "frequency_angle", "btr", "spatial_spectrum"])
cfg["analysis"] = f.settings(band=cfg["plan"]["processing"]["band_hz"])
f.mock_confirm(cfg); f.runner.execute(cfg)
req = f.handoff_request(main, Path(cfg["plan"]["output"]["directory"]), [
    {"algorithm": "mvdr", "beam_id": "beam_000000"}, {"algorithm": "cbf", "beam_id": "beam_000002"}])
packet = f.receiver.prepare(req, main)

noise = base / "noise"; noise.mkdir()
n = 32768
x = np.random.default_rng(20261005).normal(size=(n, 1)).astype("float64")
source = noise / "synthetic-white-noise.npy"; np.save(source, x, allow_pickle=False)
report_dir = noise / "inspection"
f.inspect(source, report_dir, {"mode": "check", "field": "data", "sample_axis": 0, "sample_rate_hz": 1024,
    "channel_ids": ["c0"], "start_sample": 0, "stop_sample": n, "block_samples": 256})
export = {"handoff_version": "0.1", "inspection_result": {"path": str(report_dir / "result.json"),
    "sha256": f.intake.digest_file(report_dir / "result.json")}, "sample_range": [0, n], "channel_indices": [0],
    "identity": {"data_role": "single_sensor", "channel_ids": ["c0"], "role_evidence": f.MOCK, "mapping_evidence": f.MOCK},
    "processing_history": {"values": ["synthetic IID Gaussian test fixture; no sea-trial data"], "evidence": f.MOCK},
    "time_reference": {"kind": "relative", "origin": "synthetic sample zero"},
    "units_policy": "preserve_report_value_or_unknown", "inspection_linkage": "accept_size_mtime_link_not_historical_content_hash",
    "limitations_acknowledgement": f.MOCK,
    "output": {"directory": str(noise / "export"), "dtype": "float64", "conversion": "exact_numeric_no_scaling",
        "block_samples": 256, "max_read_mib": 64, "max_artifact_bytes": 64*1024**2}}
f.approve(export, f.intake); handoff = f.intake.prepare(export)
bypass = f.bypass_request(noise, handoff, "single_sensor", True)
bypass["validity"]["sample_intervals"] = [[0, n]]
bypass["frequency_coverage"] = {"status": "known", "band_hz": [0, 512], "evidence": f.MOCK}
f.approve(bypass, f.intake); received = f.bypass.prepare(bypass, noise)
print(json.dumps({"main": packet["handoff"], "noise": received["handoff"],
    "beam_result": str(Path(cfg["plan"]["output"]["directory"]) / "result.json"),
    "beam_config": str(Path(cfg["plan"]["output"]["directory"]) / "confirmed_config.json")}))
