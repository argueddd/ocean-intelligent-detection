"""Synthetic-only end-to-end/negative acceptance. MOCK approvals never authorize real data."""
import copy
import itertools
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from scipy.signal import periodogram, get_window

ROOT = Path(__file__).resolve().parents[1]
for dependency in ("underwater-data-inspection/scripts/acoustic_inspection", "underwater-line-spectrum-detection/scripts/beamformed_input.py"):
    if not (ROOT.parent/dependency).exists():
        raise unittest.SkipTest("v0.4.3 integration suite requires sibling inspection and handoff skills; not a full acceptance run")
sys.path.insert(0, str(ROOT/"scripts"))
sys.path.insert(0, str(ROOT.parent/"underwater-data-inspection"/"scripts"))
sys.path.insert(0, str(ROOT.parent/"underwater-line-spectrum-detection"/"scripts"))
import execute as runner
import preflight as pf
import result_products as products
import analyze_results as post
import inspection_handoff as intake
import bypass_handoff as bypass
import beamformed_input as receiver
from acoustic_inspection.pipeline import execute as inspect
from test_numerical import numerical_fixture, mock_confirm
from test_output_products import settings, approve_post

MOCK = "SYNTHETIC FIXTURE / MOCK TEST ONLY / NEVER REAL USER AUTHORIZATION"


def approve(value, module):
    value["approval"] = {"status":"confirmed", "scope_sha256":module.fingerprint(value),
                        "evidence":MOCK, "confirmation":{"method":"user","reference":MOCK}}
    return value


def upstream(folder, role="sensor_array", dtype="float32", export=True, suffix=""):
    n, c = 4096, 3 if role != "single_sensor" else 1
    x = (np.arange(n*c).reshape(n,c)%103-51).astype(dtype)
    source = folder/("synthetic"+suffix+".npy")
    np.save(source,x,allow_pickle=False)
    report_dir = folder/("inspection"+suffix)
    report = inspect(source, report_dir, {"mode":"check", "field":"data", "sample_axis":0,
        "sample_rate_hz":2000, "channel_ids":["c"+str(i) for i in range(c)],
        "start_sample":0, "stop_sample":n, "block_samples":113})
    chosen = [0] if c == 1 else [0,2]
    request = {"handoff_version":"0.1",
        "inspection_result":{"path":str(report_dir/"result.json"),
                             "sha256":intake.digest_file(report_dir/"result.json")},
        "sample_range":[7,n-11], "channel_indices":chosen,
        "identity":{"data_role":role,"channel_ids":["c"+str(i) for i in chosen],
                    "role_evidence":MOCK,"mapping_evidence":MOCK},
        "processing_history":{"values":["synthetic fixture generation"],"evidence":MOCK},
        "time_reference":{"kind":"relative","origin":"synthetic source sample zero"},
        "units_policy":"preserve_report_value_or_unknown",
        "inspection_linkage":"accept_size_mtime_link_not_historical_content_hash",
        "limitations_acknowledgement":MOCK,
        "output":{"directory":str(folder/("export"+suffix)),"dtype":"float64",
                  "conversion":"exact_numeric_no_scaling","block_samples":101,
                  "max_read_mib":64,"max_artifact_bytes":64*1024**2}}
    approve(request,intake)
    result = intake.prepare(request) if export else None
    return x, report, request, result


def bypass_request(folder, source, role, known=True):
    manifest = json.loads(Path(source["handoff"]).read_text())
    ids = list(reversed(manifest["input"]["channels"]))
    n = manifest["input"]["shape"][0]
    request = {"bypass_version":"0.1",
        "source_handoff":{"path":source["handoff"],"sha256":intake.digest_file(source["handoff"])},
        "selected_channel_ids":ids,
        "signal_metadata":[{"channel_id":i,"algorithm":None,"direction":None,"evidence":MOCK} for i in ids],
        "frequency_coverage":{"status":"unknown","band_hz":None,"evidence":MOCK},
        "validity":{"status":"known" if known else "unknown",
                    "sample_intervals":[[13,900],[1003,n-9]] if known else None,"evidence":MOCK},
        "unknown_metadata_policy":"preserve_unknown_for_transfer_only",
        "limitations_acknowledgement":MOCK,
        "output":{"directory":str(folder/"bypass"),"block_samples":97,
                  "max_working_bytes":64*1024**2,"max_artifact_bytes":64*1024**2}}
    return approve(request,intake)


def handoff_request(folder,result_dir,selections):
    request={"handoff_version":"0.1",
        "source_result":{"path":str(result_dir/"result.json"),
                         "sha256":runner.file_digest(result_dir/"result.json")},
        "selection":selections,"sample_policy":"preserve_full_output_and_mask",
        "units_policy":"preserve_no_scaling","limitations_acknowledgement":MOCK,
        "output":{"directory":str(folder/"line-input"),"block_samples":137,
                  "max_working_bytes":64*1024**2,"max_artifact_bytes":64*1024**2}}
    return approve(request,receiver)


class Isolated(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="bf-acceptance-synthetic-")
        self.folder=Path(self.temp.name)
    def tearDown(self):
        self.temp.cleanup()

    def cli(self, module, *args, expected=0):
        result=subprocess.run([sys.executable,"-B","-W","error::RuntimeWarning",str(Path(module.__file__)),
                               *map(str,args)],capture_output=True,text=True,timeout=60)
        self.assertEqual(result.returncode,expected,result.stdout+result.stderr)
        return json.loads(result.stdout if result.stdout.strip() else result.stderr)

    def request_file(self, value, name="cli-request.json"):
        path=self.folder/name
        path.write_text(json.dumps(value))
        return path


class IntakeTests(Isolated):
    def test_cli_review_digest_check_prepare(self):
        _,_,req,_=upstream(self.folder,export=False)
        path=self.request_file(req)
        self.cli(intake,"review",req["inspection_result"]["path"])
        self.assertFalse(self.cli(intake,"digest",path)["authorizes_export"])
        self.assertTrue(self.cli(intake,"check",path)["can_attempt_export"])
        receipt=self.cli(intake,"prepare",path)
        self.assertTrue(Path(receipt["handoff"]).is_file())
        self.cli(intake,"prepare",path,expected=2)

    def test_export_exact_subset_and_unconfirmed_draft(self):
        x, report, req, out=upstream(self.folder)
        dest=Path(req["output"]["directory"])
        np.testing.assert_array_equal(np.load(dest/"waveforms.npy"),x[7:-11][:,[0,2]].astype("float64"))
        manifest=json.loads((dest/"handoff.json").read_text())
        self.assertEqual(manifest["checks"],report["checks"])
        self.assertEqual(manifest["not_checked"],report["not_checked"])
        self.assertEqual(manifest["source_channel_indices"],[0,2])
        self.assertEqual(manifest["input"]["units"],"unknown")
        draft=json.loads(Path(out["draft"]).read_text())
        self.assertIsNone(draft["approval"])
        self.assertIsNone(draft["plan"]["direction_plan"])
        self.assertEqual(draft["inspection_handoff"]["sha256"],intake.digest_file(dest/"handoff.json"))

    def test_import_nonzero_origin_to_beam_and_receiver(self):
        _, report, req, out=upstream(self.folder)
        manifest=json.loads(Path(out["handoff"]).read_text())
        cfg=numerical_fixture(self.folder)
        cfg["plan"]["input"]=copy.deepcopy(manifest["input"])
        cfg["plan"]["input"]["source"]["path"]=str(Path(out["handoff"]).parent/"waveforms.npy")
        cfg["plan"]["input"]["sample_range"]=[5,manifest["input"]["shape"][0]-5]
        ids=manifest["input"]["channels"]
        cfg["plan"]["geometry"].update(channel_ids=ids,coordinates_m=[[0,0,0],[0,.1,0]])
        cfg["plan"]["processing"]["channels"]=ids
        cfg["plan"]["cbf"]["element_weights"]=[1,1]
        cfg["plan"]["output"]["time_domain_beam_indices"]=[1]
        cfg["inspection_handoff"]={"path":out["handoff"],"sha256":intake.digest_file(out["handoff"])}
        cfg["numerics"]["source_sha256"]=manifest["waveform"]["sha256"]
        mock_confirm(cfg)
        result=runner.execute(cfg)
        self.assertEqual(result["original_source_sample_range"],[12,4080])
        self.assertEqual(result["first_sample_offset_seconds"],12/2000)
        result_dir=Path(cfg["plan"]["output"]["directory"])
        request=handoff_request(self.folder,result_dir,[{"algorithm":"cbf","beam_id":"beam_000001"}])
        receipt=receiver.prepare(request,self.folder)
        accepted=receiver.receive(receipt["handoff"],receipt["sha256"])
        self.assertEqual(accepted["provenance"]["first_sample_offset_seconds"],12/2000)
        np.testing.assert_array_equal(np.load(Path(receipt["handoff"]).parent/"signal_000000.npy"),
                                      np.load(result_dir/"cbf_time.npy"))

    def test_intake_guards_without_reader(self):
        _,_,req,_=upstream(self.folder,export=False)
        variations=[]
        c=copy.deepcopy(req); c["approval"]=None; variations.append(c)
        c=copy.deepcopy(req); c["sample_range"]=[-1,10]; variations.append(approve(c,intake))
        c=copy.deepcopy(req); c["channel_indices"]=[2,0]; variations.append(approve(c,intake))
        c=copy.deepcopy(req); c["identity"]["channel_ids"]=["wrong","wrong2"]; variations.append(approve(c,intake))
        c=copy.deepcopy(req); c["output"]["max_artifact_bytes"]=1; variations.append(approve(c,intake))
        c=copy.deepcopy(req); c["identity"]["data_role"]="unknown"; variations.append(approve(c,intake))
        with patch.object(intake,"reader_module",side_effect=AssertionError("must not load samples")):
            for c in variations:
                with self.subTest(c=c):
                    self.assertFalse(intake.check(c)["can_attempt_export"])
                    with self.assertRaises(ValueError): intake.prepare(c)
        self.assertFalse(Path(req["output"]["directory"]).exists())

    def test_missing_sample_rate_blocks_export(self):
        _,_,req,_=upstream(self.folder,export=False)
        path=Path(req["inspection_result"]["path"])
        r=json.loads(path.read_text())
        r["dataset"]["sample_rate_hz"].update(state="missing",value=None,sources=[])
        path.write_bytes(intake.json_bytes(r))
        req["inspection_result"]["sha256"]=intake.digest_file(path); approve(req,intake)
        self.assertFalse(intake.check(req)["can_attempt_export"])

    def test_source_change_blocks_export(self):
        _,_,req,_=upstream(self.folder,export=False)
        with (self.folder/"synthetic.npy").open("ab") as f: f.write(b"changed")
        self.assertFalse(intake.check(req)["can_attempt_export"])

    def test_nonfinite_is_not_repaired(self):
        _,_,req,_=upstream(self.folder,export=False)
        source=self.folder/"synthetic.npy"
        a=np.load(source); a[15,0]=np.nan; np.save(source,a)
        report_dir=self.folder/"inspection-nan"
        inspect(source,report_dir,{"mode":"check","field":"data","sample_axis":0,"sample_rate_hz":2000,
                                  "channel_ids":["c0","c1","c2"]})
        req["inspection_result"]={"path":str(report_dir/"result.json"),"sha256":intake.digest_file(report_dir/"result.json")}
        approve(req,intake)
        with self.assertRaises(ValueError): intake.prepare(req)
        self.assertFalse((Path(req["output"]["directory"])/"handoff.json").exists())


class BypassTests(Isolated):
    def test_cli_prepare_and_both_receivers(self):
        req=self.make("single_sensor",False); path=self.request_file(req)
        self.cli(bypass,"review",req["source_handoff"]["path"],"--sha256",req["source_handoff"]["sha256"])
        self.assertFalse(self.cli(bypass,"digest",path)["is_approval"])
        self.assertFalse(self.cli(bypass,"check",path)["can_detect"])
        receipt=self.cli(bypass,"prepare",path)
        for module,command in ((bypass,"receive"),(receiver,"receive-bypass")):
            self.assertEqual(self.cli(module,command,receipt["handoff"],"--sha256",receipt["sha256"])["input_status"],"accepted")
            self.cli(module,command,receipt["handoff"],expected=2)

    def make(self,role="beamformed",known=True):
        self.x,self.report,self.up_req,out=upstream(self.folder,role)
        self.req=bypass_request(self.folder,out,role,known)
        return self.req

    def test_known_mask_reordered_beams_portable_receiver(self):
        request=self.make()
        receipt=bypass.prepare(request,self.folder)
        base=Path(receipt["handoff"]).parent
        accepted=receiver.receive_bypass(receipt["handoff"],receipt["sha256"])
        self.assertEqual(accepted["data_role"],"beamformed")
        self.assertFalse(accepted["can_detect"])
        for j,c in enumerate([2,0]):
            view=receiver.load_bypass_signal(receipt["handoff"],receipt["sha256"],f"signal_{j:06d}")
            np.testing.assert_array_equal(view["waveform"][:,0],self.x[7:-11,c])
            self.assertFalse(view["waveform"].flags.writeable)
            self.assertEqual(view["signal"]["algorithm_status"],"unknown")
            self.assertEqual(view["signal"]["direction_status"],"unknown")
            view["waveform"]._mmap.close(); view["valid_sample_mask"]._mmap.close()
        mask=np.load(base/"valid_sample_mask.npy")
        self.assertFalse(mask[:13].any()); self.assertFalse(mask[900:1003].any())
        self.assertEqual(len(mask),4078)
        moved=self.folder/"portable"
        shutil.copytree(base,moved)
        Path(request["source_handoff"]["path"]).parent.rename(self.folder/"source-hidden")
        self.assertEqual(receiver.receive_bypass(moved/"handoff.json",receipt["sha256"])["input_status"],"accepted")

    def test_single_sensor_unknown_validity_no_fake_mask(self):
        request=self.make("single_sensor",False)
        receipt=bypass.prepare(request,self.folder)
        view=receiver.load_bypass_signal(receipt["handoff"],receipt["sha256"],"signal_000000")
        self.assertIsNone(view["valid_sample_mask"])
        self.assertEqual(view["data_role"],"single_sensor")
        self.assertEqual(view["signal"]["direction_status"],"not_applicable")
        self.assertEqual(view["signal"]["algorithm_status"],"not_applicable")
        self.assertFalse((Path(receipt["handoff"]).parent/"valid_sample_mask.npy").exists())
        self.assertFalse((Path(receipt["handoff"]).parent/"detection-draft.json").exists())
        view["waveform"]._mmap.close()

    def test_known_beam_direction_and_algorithm_preserved(self):
        request=self.make()
        for entry in request["signal_metadata"]:
            entry.update(algorithm="external-fixed-beam",direction={
                "parameterization":"azimuth_elevation","angles_deg":[20,10],"angle_unit":"deg",
                "coordinate_frame":"synthetic ENU","zero_direction":"east","positive_direction":"towards north",
                "fixed_direction":True})
        approve(request,intake)
        receipt=bypass.prepare(request,self.folder)
        accepted=bypass.receive(receipt["handoff"],receipt["sha256"])
        self.assertEqual(accepted["signals"][0]["direction"]["angles_deg"],[20,10])
        self.assertEqual(accepted["signals"][0]["algorithm"],"external-fixed-beam")

    def test_bypass_guards_without_waveform_or_beamforming(self):
        request=self.make()
        variations=[]
        for field in ("selected_channel_ids","signal_metadata","validity","frequency_coverage","approval"):
            c=copy.deepcopy(request); c[field]=None; variations.append(c)
        c=copy.deepcopy(request); c["selected_channel_ids"]=["not_saved"]; variations.append(approve(c,intake))
        c=copy.deepcopy(request); c["validity"]["sample_intervals"]=[[8,100],[90,101]]; variations.append(approve(c,intake))
        c=copy.deepcopy(request); c["frequency_coverage"]["band_hz"]=[0,1000]; variations.append(approve(c,intake))
        c=copy.deepcopy(request); c["output"]["max_working_bytes"]=1; variations.append(approve(c,intake))
        with patch.object(bypass,"load_npy",side_effect=AssertionError("no array read")), \
             patch.object(runner.core,"analyze",side_effect=AssertionError("no beamforming")):
            for c in variations:
                with self.subTest(c=c):
                    with self.assertRaises((ValueError,TypeError)): bypass.prepare(c,self.folder)
        self.assertFalse(Path(request["output"]["directory"]).exists())

    def test_raw_array_cannot_bypass(self):
        request=self.make("sensor_array")
        with self.assertRaises(ValueError): bypass.prepare(request,self.folder)

    def test_bypass_check_does_not_load_arrays(self):
        request=self.make()
        with patch.object(np,"load",side_effect=AssertionError("must not load waveform")):
            result=bypass.check(request,self.folder)
        self.assertGreater(result["artifact_bytes_estimate"],0)

    def test_tamper_signal_rejected(self):
        request=self.make()
        receipt=bypass.prepare(request,self.folder)
        p=Path(receipt["handoff"]).parent/"signal_000000.npy"
        a=np.load(p); a[0,0]+=1; np.save(p,a)
        with self.assertRaises(ValueError): bypass.receive(receipt["handoff"],receipt["sha256"])

    def test_tamper_metadata_even_rehashed_manifest_rejected(self):
        request=self.make()
        receipt=bypass.prepare(request,self.folder)
        p=Path(receipt["handoff"]); m=json.loads(p.read_text())
        m["signals"][0]["source_column"]=0
        p.write_bytes(intake.json_bytes(m))
        with self.assertRaises(ValueError): bypass.receive(p,intake.digest_file(p))

    def test_no_overwrite_existing_output(self):
        request=self.make()
        dest=Path(request["output"]["directory"]); dest.mkdir()
        with self.assertRaises(ValueError): bypass.prepare(request,self.folder)

    def test_transfer_calls_no_fft(self):
        request=self.make()
        with patch.object(np.fft,"rfft",side_effect=AssertionError("no FFT")), \
             patch.object(runner.core,"analyze",side_effect=AssertionError("no beamforming")):
            receipt=bypass.prepare(request,self.folder)
            receiver.receive_bypass(receipt["handoff"],receipt["sha256"])


class SavedBeamTests(Isolated):
    def test_cli_subset_digest_check_run(self):
        self.make(); req=self.request(requested=("psd",)); path=self.request_file(req)
        self.assertEqual(self.cli(post,"digest",path)["scope_sha256"],post.fingerprint(req))
        self.assertTrue(self.cli(post,"check",path)["can_attempt_execution"])
        result=self.cli(post,"run",path)
        self.assertEqual(result["coverage"]["spectral_beams"],1)
        self.assertFalse(list(Path(req["output_directory"]).glob("*_time.npy")))

    def test_cli_main_handoff_and_receive_only(self):
        self.make(); req=handoff_request(self.folder,self.result_dir,[{"algorithm":"cbf","beam_id":"beam_000001"}])
        path=self.request_file(req)
        self.cli(receiver,"review",self.result_dir/"result.json")
        self.assertFalse(self.cli(receiver,"digest",path)["is_approval"])
        self.assertTrue(self.cli(receiver,"check",path)["can_attempt_preparation"])
        receipt=self.cli(receiver,"prepare",path)
        accepted=self.cli(receiver,"receive",receipt["handoff"],"--sha256",receipt["sha256"])
        self.assertFalse(accepted["can_detect"]); self.assertEqual(accepted["detection_status"],"not_run")
        self.cli(receiver,"receive",receipt["handoff"],expected=2)

    def make(self,indices=(1,),spectra=()):
        self.cfg=numerical_fixture(self.folder)
        self.cfg["plan"]["direction_plan"]["directions_deg"]=[[-20],[0],[20]]
        self.cfg["plan"]["output"].update(time_domain_beam_indices=list(indices),save_time_domain=bool(indices),
                                         auxiliary_products=list(spectra))
        if spectra: self.cfg["analysis"]=settings(band=self.cfg["plan"]["processing"]["band_hz"])
        mock_confirm(self.cfg)
        self.result=runner.execute(self.cfg)
        self.result_dir=Path(self.cfg["plan"]["output"]["directory"])
        return self.result

    def request(self,ids=("beam_000001",),retain=(),algs=("cbf",),requested=("psd","time_frequency")):
        return approve_post({"product_version":"0.4.2",
            "source_result":{"path":str(self.result_dir/"result.json"),
                             "sha256":runner.file_digest(self.result_dir/"result.json")},
            "output_directory":str(self.folder/"post"),"algorithms":list(algs),
            "analysis_beam_ids":list(ids),"time_domain_beam_ids":list(retain),
            "auxiliary_products":list(requested),
            "analysis":settings(band=self.cfg["plan"]["processing"]["band_hz"]),
            "max_working_bytes":1000000000,"max_artifact_bytes":300000000,"title":MOCK})

    def test_one_saved_beam_psd_oracle_no_new_time(self):
        self.make()
        cfg=self.request(); r=post.execute(cfg); dest=Path(cfg["output_directory"])
        self.assertEqual(r["spectral_beams"][0]["scan_column"],1)
        self.assertEqual(r["spectral_beams"][0]["source_column"],0)
        self.assertEqual(r["spectral_beams"][0]["spectral_column"],0)
        self.assertEqual(r["coverage"]["source_scan_beams"],3)
        self.assertEqual(r["coverage"]["spectral_beams"],1)
        self.assertFalse(list(dest.glob("*_time.npy")))
        x=np.load(self.result_dir/"cbf_time.npy")
        starts=np.load(dest/"analysis_frame_start_sample.npy")
        freqs=np.load(dest/"analysis_frequency_hz.npy")
        expected=[]
        for start in starts:
            f,p=periodogram(x[start:start+128],fs=2000,window=get_window("hann",128),
                            detrend=False,nfft=128,axis=0,scaling="density")
            expected.append(p[np.isin(f,freqs)])
        np.testing.assert_allclose(np.load(dest/"cbf_time_frequency_psd.npy"),expected,rtol=2e-13,atol=1e-16)
        np.testing.assert_allclose(np.load(dest/"cbf_psd.npy"),np.mean(expected,axis=0),rtol=2e-13,atol=1e-16)
        self.assertEqual(r["presentation"]["beam_ids"],["beam_000001"])

    def test_reordered_partial_columns_and_repeated_postprocessing(self):
        self.make((2,0))
        cfg=self.request(("beam_000000","beam_000002"),("beam_000002",),("mvdr",),("btr","frequency_angle"))
        r=post.execute(cfg); dest=Path(cfg["output_directory"])
        self.assertEqual([b["source_column"] for b in r["spectral_beams"]],[1,0])
        self.assertEqual([b["scan_column"] for b in r["spectral_beams"]],[0,2])
        self.assertEqual(r["beams"][0]["scan_column"],2)
        np.testing.assert_array_equal(np.load(dest/"mvdr_time.npy"),np.load(self.result_dir/"mvdr_time.npy")[:,[0]])
        cfg["source_result"]={"path":str(dest/"result.json"),"sha256":runner.file_digest(dest/"result.json")}
        cfg["output_directory"]=str(self.folder/"post-again")
        cfg["analysis_beam_ids"]=["beam_000002"]; cfg["time_domain_beam_ids"]=[]; approve_post(cfg)
        again=post.execute(cfg)
        self.assertEqual(again["spectral_beams"][0]["scan_column"],2)
        self.assertEqual(again["spectral_beams"][0]["source_column"],0)

    def test_selection_guards_stop_before_arrays(self):
        self.make()
        configs=[]
        for field in ("analysis_beam_ids","time_domain_beam_ids","algorithms"):
            c=self.request(); c[field]=None; configs.append(approve_post(c))
        c=self.request(("beam_000000",)); configs.append(c)
        c=self.request(("beam_000001","beam_000001")); configs.append(c)
        c=self.request(retain=("beam_000002",)); configs.append(c)
        c=self.request(algs=("not_an_algorithm",)); configs.append(c)
        c=self.request(); c["max_working_bytes"]=1; configs.append(approve_post(c))
        with patch.object(post.np,"load",side_effect=AssertionError("must not read arrays")):
            for c in configs:
                with self.subTest(c=c):
                    self.assertFalse(post.check(c)["can_attempt_execution"])
                    with self.assertRaises(runner.ExecutionBlocked): post.execute(c)

    def test_pure_spectra_cannot_be_used_to_invent_waveform(self):
        self.make((),("psd",))
        c=self.request()
        self.assertFalse(post.check(c)["can_attempt_execution"])
        req=handoff_request(self.folder,self.result_dir,[{"algorithm":"cbf","beam_id":"beam_000001"}])
        with self.assertRaises(ValueError): receiver.prepare(req,self.folder)

    def test_post_plot_failure_no_completion(self):
        self.make()
        c=self.request()
        with patch.object(products,"render",side_effect=OSError("synthetic plotting failure")):
            with self.assertRaises(OSError): post.execute(c)
        self.assertFalse((Path(c["output_directory"])/"result.json").exists())

    def test_handoff_exact_order_mask_provenance_no_detector(self):
        self.make((2,0))
        selections=[{"algorithm":"mvdr","beam_id":"beam_000000"},{"algorithm":"cbf","beam_id":"beam_000002"}]
        req=handoff_request(self.folder,self.result_dir,selections)
        with patch.object(np.fft,"rfft",side_effect=AssertionError("no FFT in handoff")):
            receipt=receiver.prepare(req,self.folder)
            accepted=receiver.receive(receipt["handoff"],receipt["sha256"])
        base=Path(receipt["handoff"]).parent
        for j,(algo,col) in enumerate([("mvdr",1),("cbf",0)]):
            np.testing.assert_array_equal(np.load(base/f"signal_{j:06d}.npy"),
                                          np.load(self.result_dir/(algo+"_time.npy"))[:,[col]])
        np.testing.assert_array_equal(np.load(base/"valid_sample_mask.npy"),np.load(self.result_dir/"valid_sample_mask.npy"))
        self.assertEqual(accepted["detection_status"],"not_run")
        self.assertFalse((base/"detection-draft.json").exists())
        self.assertFalse((base/"questions.json").exists())
        self.assertTrue((base/"handoff-report.json").exists())

    def test_handoff_portable_without_original_source(self):
        self.make()
        req=handoff_request(self.folder,self.result_dir,[{"algorithm":"cbf","beam_id":"beam_000001"}])
        receipt=receiver.prepare(req,self.folder)
        self.result_dir.rename(self.folder/"source-hidden")
        view=receiver.load_beam(receipt["handoff"],receipt["sha256"],"signal_000000")
        self.assertEqual(view["waveform"].shape,(4096,1)); self.assertFalse(view["waveform"].flags.writeable)
        view["waveform"]._mmap.close(); view["valid_sample_mask"]._mmap.close()

    def test_handoff_missing_selection_and_stale_approval_block(self):
        self.make()
        r=handoff_request(self.folder,self.result_dir,[{"algorithm":"cbf","beam_id":"beam_000001"}])
        r["selection"]=[]
        with self.assertRaises(ValueError): receiver.prepare(r,self.folder)
        r["selection"]=[{"algorithm":"cbf","beam_id":"beam_000002"}]; approve(r,receiver)
        with self.assertRaises(ValueError): receiver.prepare(r,self.folder)

    def test_receiver_tampering_blocked(self):
        self.make()
        r=handoff_request(self.folder,self.result_dir,[{"algorithm":"cbf","beam_id":"beam_000001"}])
        receipt=receiver.prepare(r,self.folder)
        p=Path(receipt["handoff"]).parent/"valid_sample_mask.npy"
        a=np.load(p); a[0]=~a[0]; np.save(p,a)
        with self.assertRaises(ValueError): receiver.receive(receipt["handoff"],receipt["sha256"])

    def test_product_source_mask_conflict_rejected(self):
        self.make()
        p=self.result_dir/"result.json"; m=json.loads(p.read_text())
        m["valid_sample_intervals"]=[[0,4096]]; p.write_bytes(intake.json_bytes(m))
        c=self.request()
        with self.assertRaises(ValueError): post.execute(c)


class ProductChoicesTests(Isolated):
    def test_all_nonempty_product_combinations_match_full_oracle(self):
        x=np.random.default_rng(221).normal(size=(1024,2)); valid=np.ones(1024,bool)
        a=settings(); expected=products.compute(x,valid,2000,a,0)
        for n in range(1,6):
            for subset in itertools.combinations(products.PRODUCTS,n):
                with self.subTest(products=subset):
                    values=products.compute(x,valid,2000,a,0,list(subset))
                    arrays={}; products.attach(arrays,"cbf",values,list(subset))
                    md=products.metadata(a,arrays,["cbf"],"unknown",list(subset))
                    self.assertEqual(set(md["delivered_products"]),set(subset))
                    wanted={suffix for suffix,_ in products.product_layout(list(subset)).values()}
                    self.assertEqual({k for k in arrays if k.startswith("cbf_")},
                                     {"cbf_"+s+".npy" for s in wanted})
                    for suffix in wanted:
                        np.testing.assert_array_equal(arrays["cbf_"+suffix+".npy"],expected["psd" if suffix=="frequency_angle" else suffix])

    def test_each_product_alone_renders_only_requested_figures(self):
        from PIL import Image
        x=np.random.default_rng(222).normal(size=(512,1)); a=settings()
        for i,product in enumerate(products.PRODUCTS):
            with self.subTest(product=product):
                chosen=[product]; arrays={}
                values=products.compute(x,np.ones(512,bool),2000,a,0,chosen)
                products.attach(arrays,"cbf",values,chosen)
                folder=self.folder/str(i); folder.mkdir()
                shown=products.render(folder,arrays,["cbf"],np.array([[20.]]),
                    {"parameterization":"array_angle"},MOCK,a,2000,chosen,beam_ids=["beam_000042"])
                self.assertEqual(len(shown["figures"]),1)
                self.assertEqual(shown["beam_ids"],["beam_000042"])
                for name in shown["figures"]:
                    with Image.open(folder/name) as image: image.verify()
                self.assertFalse(shown["angular_axis_used"])


if __name__=="__main__":
    unittest.main()
