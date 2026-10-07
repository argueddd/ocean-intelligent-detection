"""Synthetic declaration tests only: no signal processing or real truth is used."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("evaluation_contract", ROOT / "scripts/validate_contract.py")
contract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(contract)


def ref(name="evidence"):
    return {"kind":"file","locator":"/nonexistent-contract-test/" + name + ".json",
            "sha256":"a"*64,"object_id":name,"reason":None}


def scope(start=0, stop=10, low=40, high=450):
    return {"time":{"status":"known","reference":"original_signal_relative_seconds",
                    "intervals_s":[[start,stop]],"reason":None},"frequency_band_hz":[low,high]}


def target():
    return {"target_id":"t1","result_ref":ref("detection"),"run_id":"run1","task_id":"task1",
            "task_kind":"framewise",
            "source":{"status":"known","input_package_sha256":"b"*64,"signal_id":"s1",
                      "beam":{"status":"known","result_sha256":"c"*64,"beamformer":"CBF",
                              "beam_id":"b0","metadata_ref":ref("beam"),"reason":None},"reason":None},
            "configuration_ref":ref("detector_configuration"),"scope":scope(),"limitations":[]}


def document(kind, payload):
    return {"schema_version":"0.1.0","record_type":kind,"document_status":"specified",
            "payload":payload,"unresolved_items":[]}


def coverage():
    region = {"region_id":"r1","scope":scope(),"label_status":"complete",
              "label_grain":"candidate_peak","positive_definition":"Any annotated tonal peak",
              "negative_definition":"All other eligible candidates in this fully reviewed region",
              "h0_definition":None,"unmarked_policy":"negative","labels_ref":ref("labels"),
              "evidence_refs":[ref("annotation_protocol")],"reason":None}
    return document("TruthCoverage", {
        "coverage_id":"truth1","target":target(),"availability":"available",
        "evidence_origin":"measurement_annotation","provenance_refs":[ref("annotator_record")],
        "label_semantics":"Synthetic declaration for contract testing, not measured truth.",
        "regions":[region],"outside_regions_policy":"unknown",
        "independence":{"status":"unknown","relative_to_refs":[],
                        "basis":"No independence assertion in this fixture."},"limitations":[]})


def request():
    return document("EvaluationRequest",{
        "request_id":"req1","question":"Describe existing candidate count only.","targets":[target()],
        "truth_bindings":[{"target_id":"t1","status":"none","coverage_ref":None,
                           "reason":"No truth supplied."}],
        "metric_requests":[{"metric_id":"m1","target_id":"t1","metric_kind":"candidate_count",
                            "compute":True,"definition_version":"0.1.0","matching_rule_id":None,
                            "count_stage":"final_candidate","denominator_rule":"Not applicable to count",
                            "aggregation_rule":"Count full candidate list in selected scope",
                            "coverage_rule":"Completed scope only, report exclusions"}],
        "matching_rules":[],
        "output_plan":{"display_metric_ids":["m1"],"save_metric_ids":[],"save_destination":None,
                       "artifact_requests":[]},
        "confirmation":{"status":"pending","evidence_ref":None,"statement":None},
        "accepted_limitations":["Pending confirmation; never authorized by this fixture."]})


def metric():
    return {"metric_id":"m1","target_id":"t1","metric_kind":"candidate_count",
            "definition_version":"0.1.0","definition":"Final candidates in actual scope",
            "status":"computed","value":3,"unit":"candidate","numerator":None,"denominator":None,
            "actual_scope":scope(),"matching_rule_ref":None,"count_stage":"final_candidate",
            "basis":{"kind":"empirical_descriptive","truth_status":"none","coverage_ref":None,
                     "region_ids":[],"evidence_refs":[ref("candidate_list")],"limitations":[]},
            "accounting":{"status":"complete","trial_unit":"candidate",
                          "zero_detection_units_included":None,"candidates_complete":True,
                          "requested_units":None,"processed_units":None,"excluded_units":None,
                          "exclusion_reasons":[],"evidence_refs":[ref("coverage")]},
            "reason":None}


def result():
    return document("EvaluationResult",{
        "evaluation_id":"eval1","request_ref":ref("request"),"configuration_ref":ref("evaluation_plan"),
        "targets":[target()],"execution_status":"completed","metrics":[metric()],"findings":[],
        "artifacts":[],"acceptance":{"status":"not_requested","criteria_ref":None,
                                    "evidence_refs":[],"reason":"No acceptance requested.","metric_ids":[]},
        "limitations":["Synthetic declarations, never an actual evaluation run."]})


def quantity(value, unit):
    return {"value":value,"unit":unit,"definition":"Fixture quantity only","evidence_refs":[ref()]}


def frame_result():
    d = result()
    m = d["payload"]["metrics"][0]
    m.update(metric_kind="mean_candidates_per_frame", value=1.5, unit="candidate/frame",
             numerator=quantity(3,"candidate"),denominator=quantity(2,"frame"))
    m["accounting"].update(trial_unit="frame",zero_detection_units_included=True,
                           requested_units=3,processed_units=2,excluded_units=1,
                           exclusion_reasons=["One explicitly excluded fixture frame"])
    return d


def truth_result(kind="false_count", truth="complete"):
    d = result()
    m = d["payload"]["metrics"][0]
    m.update(metric_kind=kind, matching_rule_ref=ref("matching"))
    m["basis"].update(kind="label_matched",truth_status=truth,
                      coverage_ref=ref("truth"),region_ids=["r1"])
    if kind in ("recall","precision","f1"):
        m.update(value=0.5,unit="1",numerator=quantity(1,"candidate"),
                 denominator=quantity(2,"candidate"))
    if kind.startswith("frequency_"):
        m.update(value=1.0,unit="Hz")
        m["accounting"]["trial_unit"]="matched_candidate"
    return d


class ContractTests(unittest.TestCase):
    def good(self, d, expected=None):
        before = copy.deepcopy(d)
        report = contract.validate_document(d, expected)
        self.assertTrue(report["valid"], report)
        self.assertFalse(report["can_execute"])
        self.assertEqual(d,before)
        return report

    def bad(self, d):
        report = contract.validate_document(d)
        self.assertFalse(report["valid"], report)
        self.assertFalse(report["can_execute"])
        self.assertTrue(report["errors"])
        return report

    def test_all_templates_are_drafts_not_permission(self):
        for kind in contract.KINDS:
            with self.subTest(kind=kind):
                d = contract.read_json(ROOT/"assets/templates"/(kind+".draft.json"))
                self.good(d,kind)
                self.assertTrue(d["unresolved_items"])
                self.assertTrue(all(x is None for x in d["payload"].values()))

    def test_all_specified_fixture_types(self):
        for d in (request(),coverage(),result()):
            with self.subTest(kind=d["record_type"]):
                self.good(d)

    def test_no_source_files_or_network_opened(self):
        contract._validators()
        with patch.object(Path,"read_text",side_effect=AssertionError("unexpected read")), \
             patch("socket.socket",side_effect=AssertionError("unexpected network")):
            self.good(result())

    def test_schema_rejects_unexpected_fields(self):
        for location in ("root","payload","metric"):
            d=result()
            obj=d if location=="root" else d["payload"] if location=="payload" else d["payload"]["metrics"][0]
            obj["unannounced_extension"]=True
            with self.subTest(location=location): self.bad(d)

    def test_version_mismatch(self):
        d=request(); d["schema_version"]="0.2.0"; self.bad(d)

    def test_type_expectation_mismatch(self):
        self.assertFalse(contract.validate_document(request(),"EvaluationResult")["valid"])

    def test_draft_needs_unresolved_items(self):
        d=contract.read_json(ROOT/"assets/templates/EvaluationRequest.draft.json")
        d["unresolved_items"]=[]; self.bad(d)

    def test_draft_not_promoted_by_status_only(self):
        d=contract.read_json(ROOT/"assets/templates/EvaluationRequest.draft.json")
        d["document_status"]="specified"; d["unresolved_items"]=[]; self.bad(d)

    def test_duplicate_target_ids(self):
        d=request(); d["payload"]["targets"].append(target()); self.bad(d)

    def test_truth_binding_required_for_each_target(self):
        d=request(); d["payload"]["truth_bindings"]=[]; self.bad(d)

    def test_unknown_truth_is_allowed_explicitly(self):
        d=request(); d["payload"]["truth_bindings"][0]["status"]="unknown"; self.good(d)

    def test_provided_truth_needs_reference(self):
        d=request(); d["payload"]["truth_bindings"][0]["status"]="provided"; self.bad(d)

    def test_output_unknown_metric(self):
        d=request(); d["payload"]["output_plan"]["display_metric_ids"]=["absent"]; self.bad(d)

    def test_save_requires_destination(self):
        d=request(); d["payload"]["output_plan"]["save_metric_ids"]=["m1"]; self.bad(d)
        d["payload"]["output_plan"]["save_destination"]="/selected-output"; self.good(d)

    def test_unselected_destination_not_permission(self):
        d=request(); d["payload"]["output_plan"]["save_destination"]="/extra"; self.bad(d)

    def test_confirmation_does_not_authorize(self):
        d=request(); d["payload"]["confirmation"].update(status="recorded",
                         evidence_ref=ref("user_statement"),statement="Synthetic test statement")
        self.good(d)

    def test_pending_confirmation_has_no_fake_evidence(self):
        d=request(); d["payload"]["confirmation"]["statement"]="imagined"; self.bad(d)

    def test_matching_required_when_requested(self):
        d=request(); d["payload"]["metric_requests"][0]["metric_kind"]="precision"; self.bad(d)

    def test_pending_matching_is_explicit_and_non_executable(self):
        d=request(); d["payload"]["metric_requests"][0].update(metric_kind="precision",matching_rule_id="rule1")
        rule={"rule_id":"rule1","status":"pending","frequency_gate_hz":None,"time_rule":None,
              "time_gate_s":None,"assignment_method":None,"tie_break":None,"duplicate_policy":None,
              "reason":"User has not selected matching tolerances."}
        d["payload"]["matching_rules"]=[rule]; self.good(d)
        rule["frequency_gate_hz"]=1; self.bad(d)

    def test_specified_matching_time_semantics(self):
        d=request()
        r={"rule_id":"rule1","status":"specified","frequency_gate_hz":1,"time_rule":"frame_identity",
           "time_gate_s":None,"assignment_method":"Explicit fixture assignment","tie_break":"Explicit order",
           "duplicate_policy":"count_as_false","reason":None}
        d["payload"]["matching_rules"]=[r]; self.good(d)
        r["time_gate_s"]=0.5; self.bad(d)
        r["time_rule"]="tolerance"; self.good(d)

    def test_duplicate_metric_ids(self):
        d=request(); d["payload"]["metric_requests"].append(copy.deepcopy(d["payload"]["metric_requests"][0]))
        self.bad(d)

    def test_request_average_spectrum_not_frame_trials(self):
        d=request(); d["payload"]["targets"][0]["task_kind"]="averaged_spectrum"
        d["payload"]["metric_requests"][0]["metric_kind"]="mean_candidates_per_frame"; self.bad(d)

    def test_time_intervals_order_nonoverlap_and_band(self):
        for field,value in (("intervals_s",[[2,1]]),("intervals_s",[[0,6],[5,8]]),
                            ("intervals_s",[[5,8],[0,2]])):
            d=request(); d["payload"]["targets"][0]["scope"]["time"][field]=value; self.bad(d)
        d=request(); d["payload"]["targets"][0]["scope"]["frequency_band_hz"]=[450,40]; self.bad(d)

    def test_unknown_time_retains_known_origin_without_inventing_interval(self):
        d=request(); t=d["payload"]["targets"][0]["scope"]["time"]
        t.update(status="unknown",intervals_s=None,reason="Extent not provided"); self.good(d)
        t["intervals_s"]=[[0,10]]; self.bad(d)

    def test_signal_unknown_can_retain_partial_known_fact(self):
        d=request(); s=d["payload"]["targets"][0]["source"]
        s.update(status="unknown",signal_id=None,reason="Mapping incomplete"); self.good(d)

    def test_single_sensor_has_no_fake_beam(self):
        d=request(); b=d["payload"]["targets"][0]["source"]["beam"]
        b.update(status="not_applicable",result_sha256=None,beamformer=None,beam_id=None,
                 metadata_ref=None,reason="Single sensor"); self.good(d)
        b["beam_id"]="fabricated"; self.bad(d)

    def test_file_reference_needs_digest(self):
        d=request(); d["payload"]["targets"][0]["result_ref"]["sha256"]=None; self.bad(d)

    def test_session_reference_supported(self):
        d=request(); r=d["payload"]["targets"][0]["result_ref"]
        r.update(kind="session",locator="session:object1",sha256=None); self.good(d)

    def test_unavailable_reference_needs_reason(self):
        d=request(); r=d["payload"]["targets"][0]["result_ref"]
        r.update(kind="unavailable"); self.bad(d)
        r["reason"]="Not retained"; self.good(d)

    def test_partial_labels_do_not_become_negative(self):
        d=coverage(); r=d["payload"]["regions"][0]
        r["label_status"]="partial_positive"; self.bad(d)
        r["unmarked_policy"]="unknown"; self.good(d)

    def test_complete_labels_need_actual_label_reference(self):
        d=coverage(); d["payload"]["regions"][0]["labels_ref"]=None; self.bad(d)

    def test_background_needs_h0_and_evidence(self):
        d=coverage(); r=d["payload"]["regions"][0]
        r.update(label_status="verified_background",labels_ref=None,h0_definition="No tonal in this region")
        self.good(d)
        r["evidence_refs"]=[]; self.bad(d)

    def test_absent_truth_not_empty_negative_table(self):
        d=coverage(); p=d["payload"]
        p.update(availability="none",evidence_origin="none",regions=[],provenance_refs=[])
        self.good(d)
        p["regions"]=coverage()["payload"]["regions"]; self.bad(d)

    def test_unknown_truth_origin_must_agree(self):
        d=coverage(); p=d["payload"]
        p.update(availability="unknown",regions=[],provenance_refs=[]); self.bad(d)
        p["evidence_origin"]="unknown"; self.good(d)

    def test_expected_frequency_not_complete_truth(self):
        d=coverage(); d["payload"]["evidence_origin"]="expected_reference"; self.bad(d)

    def test_region_outside_target(self):
        d=coverage(); d["payload"]["regions"][0]["scope"]=scope(stop=11); self.bad(d)

    def test_region_time_reference_mismatch(self):
        d=coverage(); d["payload"]["regions"][0]["scope"]["time"]["reference"]="other_clock"; self.bad(d)

    def test_overlap_regions_rejected(self):
        d=coverage(); second=copy.deepcopy(d["payload"]["regions"][0]); second["region_id"]="r2"
        d["payload"]["regions"].append(second); self.bad(d)

    def test_mixed_truth_regions_keep_unlabeled_unknown(self):
        d=coverage(); d["payload"]["regions"][0]["scope"]=scope(stop=5)
        r=copy.deepcopy(d["payload"]["regions"][0])
        r.update(region_id="r2",scope=scope(start=5),label_status="unlabeled",labels_ref=None,
                 unmarked_policy="unknown",reason="Not annotated",label_grain="none",
                 positive_definition=None,negative_definition=None,evidence_refs=[])
        d["payload"]["regions"].append(r); self.good(d)

    def test_uncovered_regions_remain_unknown(self):
        d=coverage(); d["payload"]["outside_regions_policy"]="negative"; self.bad(d)

    def test_independence_must_identify_relative_sources(self):
        d=coverage(); d["payload"]["independence"]["status"]="independent"; self.bad(d)
        d["payload"]["independence"]["relative_to_refs"]=[ref("calibration_data")]; self.good(d)

    def test_noncomputed_metric_never_zero_filled(self):
        for status in ("not_run","pending_confirmation","insufficient_evidence","not_applicable",
                       "undefined","not_implemented","failed","not_requested"):
            with self.subTest(status=status):
                d=result(); d["payload"]["execution_status"]="partial"
                m=d["payload"]["metrics"][0]; m.update(status=status,value=None,reason="Explicit test reason")
                self.good(d); m["value"]=0; self.bad(d)

    def test_null_reason_not_enough_for_unavailable(self):
        d=result(); m=d["payload"]["metrics"][0]; m.update(status="insufficient_evidence",value=None)
        self.bad(d)

    def test_successful_zero_candidates_allowed(self):
        d=result(); d["payload"]["metrics"][0]["value"]=0; self.good(d)

    def test_count_must_not_be_negative_fractional_or_bool(self):
        for value in (-1,1.5,True):
            with self.subTest(value=value):
                d=result(); d["payload"]["metrics"][0]["value"]=value; self.bad(d)

    def test_units_not_silently_reinterpreted(self):
        d=result(); d["payload"]["metrics"][0]["unit"]="Hz"; self.bad(d)

    def test_frame_denominator_includes_zero_detection_frames(self):
        d=frame_result(); self.good(d)
        d["payload"]["metrics"][0]["accounting"]["zero_detection_units_included"]=False; self.bad(d)

    def test_frame_denominator_not_candidate_count(self):
        d=frame_result(); d["payload"]["metrics"][0]["denominator"]["value"]=3; self.bad(d)

    def test_average_spectrum_result_not_frame_trials(self):
        d=frame_result(); d["payload"]["targets"][0]["task_kind"]="averaged_spectrum"; self.bad(d)

    def test_zero_or_missing_denominator_not_computed(self):
        for den in (None,quantity(0,"frame")):
            d=frame_result(); d["payload"]["metrics"][0]["denominator"]=den; self.bad(d)

    def test_incomplete_candidates_not_complete_statistic(self):
        d=result(); d["payload"]["metrics"][0]["accounting"]["candidates_complete"]=False; self.bad(d)

    def test_accounting_count_mismatch(self):
        d=frame_result(); d["payload"]["metrics"][0]["accounting"]["requested_units"]=2; self.bad(d)

    def test_excluded_units_need_reason(self):
        d=frame_result(); d["payload"]["metrics"][0]["accounting"]["exclusion_reasons"]=[]; self.bad(d)

    def test_no_truth_cannot_report_false_alarm_even_zero(self):
        d=result(); m=d["payload"]["metrics"][0]; m.update(metric_kind="false_count",value=0); self.bad(d)

    def test_truth_based_false_count_declaration(self):
        self.good(truth_result())

    def test_partial_truth_not_general_precision(self):
        self.bad(truth_result("precision","partial"))

    def test_partial_truth_can_support_matched_frequency_error(self):
        self.good(truth_result("frequency_rmse_hz","partial"))

    def test_matched_result_requires_matching_rule(self):
        d=truth_result("precision"); d["payload"]["metrics"][0]["matching_rule_ref"]=None; self.bad(d)

    def test_background_false_count_without_truth_matching(self):
        d=truth_result(truth="verified_background"); m=d["payload"]["metrics"][0]
        m["matching_rule_ref"]=None; m["basis"]["kind"]="verified_background"; self.good(d)

    def test_background_does_not_define_recall(self):
        self.bad(truth_result("recall","verified_background"))

    def test_probabilities_and_fractions_range(self):
        d=truth_result("precision"); d["payload"]["metrics"][0]["value"]=1.2; self.bad(d)

    def test_fraction_numerator_not_larger_than_denominator(self):
        d=truth_result("precision"); d["payload"]["metrics"][0]["numerator"]["value"]=3; self.bad(d)

    def test_model_probability_not_measured_false_alarm(self):
        d=truth_result(); d["payload"]["metrics"][0]["basis"]["kind"]="theoretical"; self.bad(d)

    def test_image_evidence_not_numeric_metric(self):
        d=result(); d["payload"]["metrics"][0]["basis"]["kind"]="image_only"; self.bad(d)

    def test_cell_false_alarm_requires_cell_decisions(self):
        d=truth_result("cell_false_fraction","verified_background"); m=d["payload"]["metrics"][0]
        m.update(value=0.1,unit="1",numerator=quantity(1,"cfar_cell"),denominator=quantity(10,"cfar_cell"))
        self.bad(d)
        m["count_stage"]="cell_threshold_crossing"; m["accounting"]["trial_unit"]="cfar_cell"
        m["basis"]["kind"]="verified_background"; self.good(d)

    def test_actual_scope_not_outside_requested(self):
        d=result(); d["payload"]["metrics"][0]["actual_scope"]=scope(low=20); self.bad(d)

    def test_result_unknown_target_rejected(self):
        d=result(); d["payload"]["metrics"][0]["target_id"]="other"; self.bad(d)

    def test_blocked_result_not_computed(self):
        d=result(); d["payload"]["execution_status"]="blocked"; self.bad(d)

    def test_completed_review_can_report_insufficient_evidence(self):
        d=result(); m=d["payload"]["metrics"][0]
        m.update(metric_kind="false_count",status="insufficient_evidence",value=None,reason="No truth")
        self.good(d)

    def test_completed_does_not_hide_failed_computation(self):
        d=result(); d["payload"]["metrics"][0].update(status="failed",value=None,reason="Failed"); self.bad(d)

    def test_saved_artifact_needs_real_reference_declaration(self):
        d=result(); artifact={"artifact_id":"a1","kind":"metric_table","target_ids":["t1"],
                             "status":"saved","reference":None,"reason":None}
        d["payload"]["artifacts"]=[artifact]; self.bad(d)
        artifact["reference"]=ref("saved_table"); self.good(d)

    def test_artifact_unknown_target(self):
        d=result(); d["payload"]["artifacts"]=[{"artifact_id":"a1","kind":"plot","target_ids":["other"],
                       "status":"not_requested","reference":None,"reason":None}]; self.bad(d)

    def test_acceptance_needs_criteria_and_performance(self):
        d=result(); a=d["payload"]["acceptance"]
        a.update(status="pass",criteria_ref=ref("criteria"),evidence_refs=[ref("report")],metric_ids=["m1"])
        self.bad(d)
        d=truth_result("precision"); d["payload"]["acceptance"]=a; self.good(d)

    def test_nonfinite_and_python_nonjson_values_rejected(self):
        for value in (float("nan"),float("inf"),float("-inf"),(1,2),{1:"nonstring key"}):
            with self.subTest(value=repr(value)):
                d=result(); d["payload"]["metrics"][0]["value"]=value; self.bad(d)

    def test_cli_is_read_only_and_reports_parse_errors(self):
        with tempfile.TemporaryDirectory(prefix="evaluation-contract-test-") as tmp:
            path=Path(tmp)/"document.json"
            text=json.dumps(request()); path.write_text(text)
            command=[sys.executable,"-B",str(ROOT/"scripts/validate_contract.py"),str(path)]
            before=set(Path(tmp).iterdir())
            run=subprocess.run(command,capture_output=True,text=True,check=False)
            self.assertEqual(run.returncode,0,run.stderr)
            self.assertFalse(json.loads(run.stdout)["can_execute"])
            self.assertEqual(path.read_text(),text)
            self.assertEqual(set(Path(tmp).iterdir()),before)
            for invalid in ('{"a":1,"a":2}', '{"x":NaN}', '{"x":1e999}', '{'):
                path.write_text(invalid)
                run=subprocess.run(command,capture_output=True,text=True,check=False)
                self.assertEqual(run.returncode,2,run.stdout)
                self.assertFalse(json.loads(run.stdout)["can_execute"])

    def test_cli_invalid_structure_exit_one(self):
        with tempfile.TemporaryDirectory(prefix="evaluation-contract-test-") as tmp:
            path=Path(tmp)/"document.json"; path.write_text('{"record_type":"EvaluationResult"}')
            run=subprocess.run([sys.executable,"-B",str(ROOT/"scripts/validate_contract.py"),str(path)],
                               capture_output=True,text=True,check=False)
            self.assertEqual(run.returncode,1)
            self.assertFalse(json.loads(run.stdout)["valid"])


    def test_acceptance_does_not_hide_uncomputed_critical_metric(self):
        d=truth_result("precision")
        second=copy.deepcopy(d["payload"]["metrics"][0])
        second.update(metric_id="m2",status="insufficient_evidence",value=None,reason="Missing truth")
        d["payload"]["metrics"].append(second)
        d["payload"]["acceptance"].update(status="pass",criteria_ref=ref("criteria"),
                                          evidence_refs=[ref("report")],metric_ids=["m1","m2"])
        self.bad(d)

    def test_unknown_acceptance_metric(self):
        d=result(); d["payload"]["acceptance"].update(status="inconclusive",metric_ids=["other"])
        self.bad(d)

    def test_background_frame_fraction_valid_declaration(self):
        d=frame_result(); m=d["payload"]["metrics"][0]
        m.update(metric_kind="background_frame_false_fraction",value=0.5,unit="1",
                 numerator=quantity(1,"frame"))
        m["basis"].update(kind="verified_background",truth_status="verified_background",
                          coverage_ref=ref("background"),region_ids=["r1"])
        self.good(d)

    def test_background_segment_fraction_valid_declaration(self):
        d=truth_result("background_segment_false_fraction","verified_background")
        m=d["payload"]["metrics"][0]
        m.update(value=0.25,unit="1",numerator=quantity(1,"segment"),
                 denominator=quantity(4,"segment"))
        m["basis"]["kind"]="verified_background"
        m["accounting"]["trial_unit"]="segment"; self.good(d)
        m["accounting"]["trial_unit"]="frame"; self.bad(d)

    def test_hourly_false_count_requires_hour_denominator(self):
        d=truth_result("false_per_hour","verified_background"); m=d["payload"]["metrics"][0]
        m.update(value=2,unit="candidate/hour",numerator=quantity(2,"candidate"),
                 denominator=quantity(1,"hour"))
        m["basis"]["kind"]="verified_background"; m["accounting"]["trial_unit"]="hour"
        self.good(d)
        m["denominator"]["unit"]="second"; self.bad(d)

    def test_known_beam_needs_complete_identity(self):
        d=request(); d["payload"]["targets"][0]["source"]["beam"]["beam_id"]=None; self.bad(d)

    def test_false_count_cannot_use_descriptive_basis(self):
        d=truth_result(); d["payload"]["metrics"][0]["basis"]["kind"]="empirical_descriptive"; self.bad(d)

    def test_scope_may_span_adjacent_declared_time_intervals(self):
        d=result(); d["payload"]["targets"][0]["scope"]["time"]["intervals_s"]=[[0,5],[5,10]]
        self.good(d)
        d["payload"]["targets"][0]["scope"]["time"]["intervals_s"]=[[0,4],[5,10]]; self.bad(d)

    def test_duplicate_region_id_and_metric_result_id(self):
        d=coverage(); r=copy.deepcopy(d["payload"]["regions"][0])
        d["payload"]["regions"][0]["scope"]=scope(stop=5); r["scope"]=scope(start=5)
        d["payload"]["regions"].append(r); self.bad(d)
        d=result(); d["payload"]["metrics"].append(copy.deepcopy(d["payload"]["metrics"][0])); self.bad(d)

    def test_third_party_schema_injection_not_followed(self):
        d=request(); d["payload"]["$ref"]="https://example.invalid/remote-schema"; self.bad(d)


if __name__ == "__main__":
    unittest.main()
