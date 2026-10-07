#!/usr/bin/env python3
"""Evidence-gated batch runtime for existing beamforming result products.

The runtime verifies immutable file references, calls the numeric metric
functions in ``beamforming_metrics.py``, and publishes a new evaluation package.
It never forms beams, changes an upstream result, chooses a target, or tunes a
beamformer.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import sys
import tempfile
import uuid

from validate_contract import read_json, validate_document


VERSION = "1.0.0"
ROOT = Path(__file__).resolve().parents[1]


class EvaluationError(RuntimeError):
    """Controlled contract, evidence, or execution failure."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value) -> None:
    text = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    path.write_text(text, encoding="utf-8")


def _load_metrics_module():
    spec = importlib.util.spec_from_file_location("beamforming_metrics_runtime", ROOT / "scripts" / "beamforming_metrics.py")
    module = importlib.util.module_from_spec(spec)
    if spec.loader is None:
        raise EvaluationError("Could not load beamforming_metrics.py.")
    spec.loader.exec_module(module)
    return module


METRICS = _load_metrics_module()

COMMANDS = {
    "spectrum": {
        "func": "spectrum_metrics",
        "defaults": {"angles": None, "scale": "db", "reduce": "max", "mainlobe_exclusion_deg": 5.0,
                     "false_peak_threshold_db": 12.0, "truth_deg": None, "top_k": 5},
    },
    "doa": {
        "func": "doa_metrics",
        "defaults": {"truth": None, "gate_deg": 5.0, "max_frame_output": 20},
    },
    "freq-bearing": {
        "func": "freq_bearing_metrics",
        "defaults": {"freqs": None, "angles": None, "scale": "db", "freq_band": None,
                     "fuse": "power-sum", "truth_deg": None, "mainlobe_exclusion_deg": 5.0,
                     "false_peak_threshold_db": 12.0, "top_k": 5, "max_frequency_output": 20},
    },
    "btr": {
        "func": "btr_metrics",
        "defaults": {"times": None, "angles": None, "scale": "db", "truth_track": None,
                     "gate_deg": 5.0, "top_k": 3, "relative_threshold_db": 12.0,
                     "max_jump_deg": 5.0, "background_exclusion_deg": 5.0,
                     "secondary_peak_threshold_db": 6.0, "max_frame_output": 20},
    },
    "signal": {
        "func": "signal_metrics",
        "defaults": {"fs": None, "column": 0, "target_segment": None, "noise_segment": None,
                     "interference_segment": None, "baseline": None, "reference": None,
                     "detrend": "mean", "eps": 1e-12},
    },
    "spectrum-output": {
        "func": "spectrum_output_metrics",
        "defaults": {"freqs": None, "column": 0, "scale": "db", "target_band": None,
                     "noise_band": None, "interference_band": None, "baseline": None,
                     "floor_percentile": 50.0, "eps": 1e-12},
    },
    "time-frequency": {
        "func": "time_frequency_metrics",
        "defaults": {"times": None, "freqs": None, "scale": "db", "target_band": None,
                     "noise_band": None, "interference_band": None, "baseline": None,
                     "presence_threshold_db": 6.0, "floor_percentile": 50.0,
                     "max_frame_output": 20, "eps": 1e-12},
    },
    "compare": {
        "func": "compare_metrics",
        "defaults": {"mode": "dual"},
    },
}


def _resolve_file(ref: dict, request_dir: Path) -> dict:
    path = Path(ref["path"]).expanduser()
    if not path.is_absolute():
        path = request_dir / path
    path = path.resolve()
    if not path.is_file():
        raise EvaluationError(f"Referenced input is unavailable: {path}")
    actual = sha256_file(path)
    if actual != ref["sha256"]:
        raise EvaluationError(f"SHA-256 mismatch for {path}: declared {ref['sha256']}, actual {actual}")
    return {"path": path, "sha256": actual, "size_bytes": path.stat().st_size,
            "object_id": ref.get("object_id")}


def _evidence_class(job: dict) -> str:
    evidence = job["evidence"]
    if job["command"] == "compare":
        return "comparison"
    if evidence["truth_status"] == "provided":
        return "truth_referenced"
    if evidence["baseline_status"] == "provided":
        return "baseline_relative"
    return "descriptive"


def _limitations(job: dict) -> list[str]:
    result = list(job["limitations"])
    evidence = job["evidence"]
    if evidence["truth_status"] != "provided":
        result.append("未提供可用真值；不将峰值、最强脊线或稳定性解释为方位精度或目标真实性。")
    if evidence["baseline_status"] != "provided" and job["command"] in {"signal", "spectrum-output", "time-frequency"}:
        result.append("未提供可比基线；不报告算法改善量。")
    if job["command"] == "btr" and evidence["truth_status"] != "provided":
        result.append("无真值 BTR 结果仅是最强连续脊线的描述，不是目标跟踪或身份关联。")
    for note in evidence["notes"]:
        if note not in result:
            result.append(note)
    return list(dict.fromkeys(result))


def preflight(request_path: Path, output_override: str | None = None) -> dict:
    request_path = request_path.expanduser().resolve()
    request = read_json(request_path)
    validation = validate_document(request, "EvaluationRequest")
    if not validation["valid"]:
        raise EvaluationError("EvaluationRequest is invalid: " + json.dumps(validation["errors"], ensure_ascii=False))
    if not validation["can_execute"]:
        raise EvaluationError("EvaluationRequest is valid but not executable; recorded confirmation is required.")

    payload = request["payload"]
    destination = Path(payload["output_plan"]["save_destination"]).expanduser().resolve()
    if output_override is not None and Path(output_override).expanduser().resolve() != destination:
        raise EvaluationError("--output-dir must exactly match output_plan.save_destination.")
    if destination.exists():
        raise EvaluationError(f"Refusing to overwrite existing output destination: {destination}")
    if destination == Path(destination.anchor):
        raise EvaluationError("Output destination cannot be a filesystem root.")

    resolved_jobs = []
    for job in payload["jobs"]:
        resolved_inputs = {name: _resolve_file(ref, request_path.parent) for name, ref in job["inputs"].items()}
        resolved_provenance = [_resolve_file(ref, request_path.parent) for ref in job["provenance_refs"]]
        resolved_jobs.append({
            "job": job,
            "inputs": {name: {**item, "path": str(item["path"])} for name, item in resolved_inputs.items()},
            "provenance": [{**item, "path": str(item["path"])} for item in resolved_provenance],
        })
    return {
        "runtime_version": VERSION,
        "request_path": str(request_path),
        "request_sha256": sha256_file(request_path),
        "request": request,
        "destination": str(destination),
        "resolved_jobs": resolved_jobs,
    }


def _namespace_for_job(job: dict, resolved_inputs: dict):
    command = job["command"]
    spec = COMMANDS[command]
    values = dict(spec["defaults"])
    unknown = set(job["parameters"]) - set(values)
    if unknown:
        raise EvaluationError(f"Job {job['job_id']} has unsupported parameters for {command}: {sorted(unknown)}")
    values.update(job["parameters"])
    values.update({name: item["path"] for name, item in resolved_inputs.items()})
    if command == "compare":
        request_mode = job.get("_request_mode")
        if request_mode in {"paper", "engineering", "dual"}:
            values["mode"] = request_mode
        elif request_mode == "descriptive":
            raise EvaluationError("compare jobs require request mode paper, engineering, or dual.")
    if command == "signal" and values["fs"] is None:
        raise EvaluationError(f"Job {job['job_id']} signal command requires parameters.fs.")
    if command == "time-frequency" and values["target_band"] is None:
        raise EvaluationError(f"Job {job['job_id']} time-frequency command requires parameters.target_band.")
    return argparse.Namespace(**values)


def _validate_finite_json(value, path="metrics"):
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise EvaluationError(f"Non-finite output at {path}.")
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _validate_finite_json(child, f"{path}/{index}")
        return
    if isinstance(value, dict):
        for key, child in value.items():
            _validate_finite_json(child, f"{path}/{key}")
        return
    raise EvaluationError(f"Non-JSON output type at {path}: {type(value).__name__}")


def _flatten_scalars(value, prefix=""):
    rows = []
    if value is None or type(value) in (str, bool, int, float):
        rows.append((prefix or "value", value))
    elif isinstance(value, dict):
        for key, child in value.items():
            child_prefix = f"{prefix}.{key}" if prefix else key
            rows.extend(_flatten_scalars(child, child_prefix))
    return rows


def _artifact(path: Path, role: str, root: Path) -> dict:
    return {"role": role, "path": str(path.relative_to(root)), "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size}


def _write_report(path: Path, request: dict, results: list[dict], acceptance: dict) -> None:
    lines = ["# 波束形成评价报告", "", f"- 请求：{request['payload']['question']}",
             f"- 模式：{request['payload']['mode']}", f"- 任务数：{len(results)}", "",
             "## 结果摘要", ""]
    for item in results:
        lines.extend([f"### {item['job_id']} — {item['subject']}", "",
                      f"- 命令：`{item['command']}`",
                      f"- 算法：{item['algorithm'] or '未指定'}",
                      f"- 证据等级：{item['evidence_class']}",
                      f"- 状态：{item['status']}"])
        if item["limitations"]:
            lines.append("- 限制：" + "；".join(item["limitations"]))
        scalars = [(name, value) for name, value in _flatten_scalars(item["metrics"]) if value is not None]
        if scalars:
            lines.extend(["", "| 指标路径 | 值 |", "|---|---:|"])
            for name, value in scalars[:30]:
                lines.append(f"| `{name}` | {value} |")
        lines.append("")
    lines.extend(["## 验收边界", "", acceptance["basis"], "",
                  "本包只评价已有波束形成结果；没有重算波束、自动选目标、跟踪或识别目标。", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def execute(preflight_data: dict) -> Path:
    request = preflight_data["request"]
    payload = request["payload"]
    destination = Path(preflight_data["destination"])
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(prefix=f".{destination.name}.tmp-", dir=destination.parent))
    try:
        job_results = []
        decisions = []
        for resolved in preflight_data["resolved_jobs"]:
            job = dict(resolved["job"])
            job["_request_mode"] = payload["mode"]
            namespace = _namespace_for_job(job, resolved["inputs"])
            function = getattr(METRICS, COMMANDS[job["command"]]["func"])
            metrics = function(namespace)
            _validate_finite_json(metrics)
            result = {
                "job_id": job["job_id"], "command": job["command"], "subject": job["subject"],
                "algorithm": job["algorithm"], "scenario": job["scenario"], "status": "computed",
                "evidence_class": _evidence_class(job), "metrics": metrics, "reason": None,
                "limitations": _limitations(job),
            }
            job_results.append(result)
            engineering = metrics.get("engineering_acceptance") if isinstance(metrics, dict) else None
            if isinstance(engineering, dict):
                decisions.extend(engineering.get("decisions", []))

        acceptance = {
            "status": "reported" if decisions else "not_requested",
            "basis": ("仅报告 comparison 任务中显式 metric_spec 阈值的判定；critical 失败不可被综合分抵消。"
                      if decisions else "未提供可执行的独立验收标准，不自动判定通过或不通过。"),
            "decisions": decisions,
        }

        resolved_config = {
            "runtime_version": VERSION,
            "request_path": preflight_data["request_path"],
            "request_sha256": preflight_data["request_sha256"],
            "destination": preflight_data["destination"],
            "jobs": [{"job_id": item["job"]["job_id"], "command": item["job"]["command"],
                      "inputs": item["inputs"], "provenance": item["provenance"],
                      "parameters": item["job"]["parameters"],
                      "evidence": item["job"]["evidence"]} for item in preflight_data["resolved_jobs"]],
        }
        resolved_path = temp_dir / "resolved-evaluation-config.json"
        jobs_path = temp_dir / "job-results.json"
        write_json(resolved_path, resolved_config)
        write_json(jobs_path, {"runtime_version": VERSION, "jobs": job_results})

        generated = [(resolved_path, "resolved_configuration"), (jobs_path, "job_results")]
        if payload["output_plan"]["save_metrics_csv"]:
            metrics_path = temp_dir / "metrics.csv"
            with metrics_path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.writer(stream)
                writer.writerow(["job_id", "command", "algorithm", "metric_path", "value"])
                for item in job_results:
                    for metric_path, value in _flatten_scalars(item["metrics"]):
                        if value is not None:
                            writer.writerow([item["job_id"], item["command"], item["algorithm"] or "", metric_path, value])
            generated.append((metrics_path, "metrics_table"))
        if payload["output_plan"]["save_report"]:
            report_path = temp_dir / "report.md"
            _write_report(report_path, request, job_results, acceptance)
            generated.append((report_path, "report"))

        artifacts = [_artifact(path, role, temp_dir) for path, role in generated]
        result_document = {
            "schema_version": "1.0.0", "record_type": "EvaluationResult", "document_status": "specified",
            "payload": {
                "evaluation_id": f"eval-{payload['request_id']}-{preflight_data['request_sha256'][:12]}",
                "runtime_version": VERSION,
                "request_ref": {"kind": "file", "path": preflight_data["request_path"],
                                "sha256": preflight_data["request_sha256"], "object_id": payload["request_id"]},
                "mode": payload["mode"], "execution_status": "completed", "job_results": job_results,
                "acceptance": acceptance, "artifacts": artifacts,
                "limitations": list(dict.fromkeys(payload["accepted_limitations"] + [
                    "评价运行时只读取已保存结果，不重算波束形成。",
                    "图像型证据应由人工定性评价；本数值运行时不从图片反演精确指标。",
                ])),
            },
            "unresolved_items": [],
        }
        result_validation = validate_document(result_document, "EvaluationResult")
        if not result_validation["valid"]:
            raise EvaluationError("Generated EvaluationResult is invalid: " + json.dumps(result_validation["errors"], ensure_ascii=False))
        result_path = temp_dir / "evaluation-result.json"
        write_json(result_path, result_document)
        generated.append((result_path, "evaluation_result"))

        manifest = {
            "schema_version": "1.0.0", "package_type": "underwater_beamforming_evaluation",
            "evaluation_id": result_document["payload"]["evaluation_id"],
            "files": [_artifact(path, role, temp_dir) for path, role in generated],
        }
        write_json(temp_dir / "package-manifest.json", manifest)
        os.replace(temp_dir, destination)
        return destination
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request")
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--output-dir")
    args = parser.parse_args()
    try:
        checked = preflight(Path(args.request), args.output_dir)
        if args.preflight_only:
            summary = {key: value for key, value in checked.items() if key not in {"request", "resolved_jobs"}}
            summary["jobs"] = [{"job_id": item["job"]["job_id"], "command": item["job"]["command"],
                                "inputs": item["inputs"], "provenance": item["provenance"]}
                               for item in checked["resolved_jobs"]]
            print(json.dumps({"valid": True, "can_execute": True, **summary}, ensure_ascii=False, indent=2))
            return
        destination = execute(checked)
        print(json.dumps({"status": "completed", "output_directory": str(destination)}, ensure_ascii=False, indent=2))
    except (EvaluationError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
