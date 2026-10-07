"""Synthetic producer fixture, subprocess-only to isolate sibling module names."""
import json
from pathlib import Path
import sys

LINE = Path(__file__).resolve().parents[1]
BEAM = LINE.parent / "underwater-beamforming"
sys.path.insert(0, str(BEAM / "scripts"))
import preflight  # Pin the beam module before the legacy fixture prepends line scripts.
sys.path.insert(0, str(BEAM / "tests"))
import test_v043_acceptance as f

base = Path(sys.argv[1])
main = base / "main"
main.mkdir()
cfg = f.numerical_fixture(main)
cfg["plan"]["direction_plan"]["directions_deg"] = [[-20], [0], [20]]
cfg["plan"]["output"].update(time_domain_beam_indices=[2, 0], save_time_domain=True, auxiliary_products=[])
f.mock_confirm(cfg)
f.runner.execute(cfg)
req = f.handoff_request(main, Path(cfg["plan"]["output"]["directory"]), [
    {"algorithm": "mvdr", "beam_id": "beam_000000"},
    {"algorithm": "cbf", "beam_id": "beam_000002"}])
main_packet = f.receiver.prepare(req, main)

packets = {"main": main_packet["handoff"]}
for role, known in (("single_sensor", True), ("beamformed", False), ("beamformed", True)):
    name = role + ("_known" if known else "_unknown")
    folder = base / name
    folder.mkdir()
    _, _, _, source = f.upstream(folder, role)
    req = f.bypass_request(folder, source, role, known=known)
    if role == "beamformed" and known:
        req["frequency_coverage"] = {"status": "known", "band_hz": [40, 450], "evidence": f.MOCK}
        for signal in req["signal_metadata"]:
            signal["algorithm"] = "external_algorithm_not_inferred"
            signal["direction"] = {"parameterization": "azimuth_elevation", "angles_deg": [12, 3],
                                  "angle_unit": "deg", "coordinate_frame": "synthetic ENU",
                                  "zero_direction": "east", "positive_direction": "towards north",
                                  "fixed_direction": True}
        f.approve(req, f.intake)
    result = f.bypass.prepare(req, folder)
    packets[name] = result["handoff"]
print(json.dumps(packets))
