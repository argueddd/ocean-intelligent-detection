#!/usr/bin/env python3
"""Lightweight metrics for underwater line-spectrum detection.

The script intentionally supports simple CSV/NPY inputs and JSON output so it
can be adapted to project-specific data formats.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np


EPS = 1e-12


def read_vector(path: str) -> np.ndarray:
    p = Path(path)
    if p.suffix.lower() == ".npy":
        arr = np.load(p)
        return np.asarray(arr, dtype=float).reshape(-1)
    rows: List[float] = []
    with p.open("r", newline="") as f:
        sample = f.read(2048)
        f.seek(0)
        if sample.strip():
            try:
                has_header = csv.Sniffer().has_header(sample)
            except csv.Error:
                first = sample.strip().splitlines()[0].split(",")[0].strip()
                try:
                    float(first)
                    has_header = False
                except ValueError:
                    has_header = True
        else:
            has_header = False
        reader = csv.reader(f)
        if has_header:
            header = next(reader, None)
            _ = header
        for row in reader:
            vals = [x.strip() for x in row if x.strip()]
            if not vals:
                continue
            rows.append(float(vals[0]))
    return np.asarray(rows, dtype=float)


def read_matrix(path: str) -> np.ndarray:
    p = Path(path)
    if p.suffix.lower() == ".npy":
        return np.asarray(np.load(p), dtype=float)
    return np.loadtxt(p, delimiter=",")


def read_records(path: str) -> List[Dict[str, Any]]:
    p = Path(path)
    with p.open("r", newline="") as f:
        reader = csv.DictReader(f)
        return [dict(row) for row in reader]


def read_truth_freqs(path: Optional[str]) -> List[float]:
    if not path:
        return []
    p = Path(path)
    if p.suffix.lower() == ".npy":
        return [float(x) for x in np.asarray(np.load(p)).reshape(-1)]
    rows = read_records(path)
    if rows:
        keys = rows[0].keys()
        freq_key = "freq_hz" if "freq_hz" in keys else next(iter(keys))
        return [float(r[freq_key]) for r in rows if str(r.get(freq_key, "")).strip()]
    return [float(x) for x in read_vector(path)]


def to_db(level: np.ndarray, scale: str) -> np.ndarray:
    if scale == "db":
        return np.asarray(level, dtype=float)
    return 10.0 * np.log10(np.maximum(np.asarray(level, dtype=float), EPS))


def rolling_noise_floor_db(
    spectrum_db: np.ndarray,
    idx: int,
    guard_bins: int,
    train_bins: int,
) -> float:
    n = spectrum_db.size
    left0 = max(0, idx - guard_bins - train_bins)
    left1 = max(0, idx - guard_bins)
    right0 = min(n, idx + guard_bins + 1)
    right1 = min(n, idx + guard_bins + train_bins + 1)
    vals = np.concatenate([spectrum_db[left0:left1], spectrum_db[right0:right1]])
    if vals.size == 0:
        vals = np.delete(spectrum_db, idx) if n > 1 else spectrum_db
    return float(np.median(vals))


def detect_peaks(
    freqs: np.ndarray,
    spectrum_db: np.ndarray,
    threshold_db: float,
    guard_bins: int,
    train_bins: int,
    min_distance_bins: int,
    max_peaks: Optional[int],
) -> List[Dict[str, float]]:
    candidates: List[Dict[str, float]] = []
    n = spectrum_db.size
    for i in range(1, n - 1):
        if spectrum_db[i] < spectrum_db[i - 1] or spectrum_db[i] < spectrum_db[i + 1]:
            continue
        noise = rolling_noise_floor_db(spectrum_db, i, guard_bins, train_bins)
        line_snr = float(spectrum_db[i] - noise)
        if line_snr >= threshold_db:
            candidates.append(
                {
                    "freq_hz": float(freqs[i]),
                    "level_db": float(spectrum_db[i]),
                    "noise_floor_db": noise,
                    "line_snr_db": line_snr,
                    "bin": int(i),
                }
            )
    candidates.sort(key=lambda x: x["line_snr_db"], reverse=True)

    selected: List[Dict[str, float]] = []
    used_bins: List[int] = []
    for cand in candidates:
        b = int(cand["bin"])
        if any(abs(b - ub) < min_distance_bins for ub in used_bins):
            continue
        selected.append(cand)
        used_bins.append(b)
        if max_peaks is not None and len(selected) >= max_peaks:
            break
    selected.sort(key=lambda x: x["freq_hz"])
    return selected


def associate_freqs(
    detections: Sequence[Dict[str, Any]],
    truth_freqs: Sequence[float],
    gate_hz: float,
) -> Tuple[List[Dict[str, float]], List[float], List[Dict[str, Any]]]:
    unmatched = set(range(len(detections)))
    matches: List[Dict[str, float]] = []
    missed: List[float] = []
    for truth in truth_freqs:
        best_idx = None
        best_err = None
        for i in unmatched:
            err = float(detections[i]["freq_hz"]) - float(truth)
            if abs(err) <= gate_hz and (best_err is None or abs(err) < abs(best_err)):
                best_idx = i
                best_err = err
        if best_idx is None or best_err is None:
            missed.append(float(truth))
            continue
        unmatched.remove(best_idx)
        matches.append(
            {
                "truth_freq_hz": float(truth),
                "detected_freq_hz": float(detections[best_idx]["freq_hz"]),
                "error_hz": float(best_err),
            }
        )
    false_alarms = [detections[i] for i in sorted(unmatched)]
    return matches, missed, false_alarms


def error_summary(errors: Sequence[float]) -> Dict[str, Optional[float]]:
    if not errors:
        return {"mae_hz": None, "rmse_hz": None, "bias_hz": None, "max_abs_error_hz": None}
    arr = np.asarray(errors, dtype=float)
    return {
        "mae_hz": float(np.mean(np.abs(arr))),
        "rmse_hz": float(np.sqrt(np.mean(arr * arr))),
        "bias_hz": float(np.mean(arr)),
        "max_abs_error_hz": float(np.max(np.abs(arr))),
    }


def arg_settings(args: argparse.Namespace) -> Dict[str, Any]:
    return {k: v for k, v in vars(args).items() if k != "func"}


def classification_metrics(
    matched_count: int,
    truth_count: int,
    detection_count: int,
    false_alarm_count: int,
) -> Dict[str, Optional[float]]:
    recall = (matched_count / truth_count) if truth_count else None
    miss_rate = (truth_count - matched_count) / truth_count if truth_count else None
    precision = (matched_count / detection_count) if detection_count else (0.0 if truth_count else None)
    if precision is None or recall is None or (precision + recall) <= 0:
        f1 = None
    else:
        f1 = 2.0 * precision * recall / (precision + recall)
    return {
        "pd": recall,
        "recall": recall,
        "miss_rate": miss_rate,
        "precision": precision,
        "f1": f1,
        "false_alarm_fraction": (false_alarm_count / detection_count) if detection_count else None,
    }


def observation_span_s_from_times(times: Sequence[float]) -> Optional[float]:
    vals = sorted(float(t) for t in times if math.isfinite(float(t)))
    if len(vals) < 2:
        return None
    span = vals[-1] - vals[0]
    return span if span > 0 else None


def false_alarm_time_rates(false_alarm_count: int, span_s: Optional[float]) -> Dict[str, Optional[float]]:
    if not span_s:
        return {"observation_span_s": span_s, "false_alarms_per_second": None, "false_alarms_per_hour": None}
    per_second = false_alarm_count / span_s
    return {
        "observation_span_s": span_s,
        "false_alarms_per_second": per_second,
        "false_alarms_per_hour": per_second * 3600.0,
    }


def continuity_summary(flags: Sequence[bool]) -> Dict[str, Optional[float]]:
    if not flags:
        return {
            "track_continuity": None,
            "fragment_count": None,
            "gap_count": None,
            "longest_segment_ratio": None,
        }
    detected = sum(1 for f in flags if f)
    active = len(flags)
    fragments = 0
    gaps = 0
    longest = 0
    current_true = 0
    in_true = False
    in_gap_after_detection = False
    for flag in flags:
        if flag:
            current_true += 1
            longest = max(longest, current_true)
            if not in_true:
                fragments += 1
                in_true = True
            in_gap_after_detection = False
        else:
            current_true = 0
            if in_true and not in_gap_after_detection:
                gaps += 1
                in_gap_after_detection = True
            in_true = False
    return {
        "track_continuity": detected / active,
        "fragment_count": fragments,
        "gap_count": gaps,
        "longest_segment_ratio": longest / active,
    }


def cmd_psd(args: argparse.Namespace) -> Dict[str, Any]:
    freqs = read_vector(args.freqs)
    spectrum = read_vector(args.spectrum)
    if freqs.size != spectrum.size:
        raise ValueError(f"freqs length {freqs.size} != spectrum length {spectrum.size}")
    spectrum_db = to_db(spectrum, args.scale)
    mask = np.ones(freqs.shape, dtype=bool)
    if args.band:
        lo, hi = parse_range(args.band)
        mask = (freqs >= lo) & (freqs <= hi)
    sub_freqs = freqs[mask]
    sub_spec_db = spectrum_db[mask]
    peaks = detect_peaks(
        sub_freqs,
        sub_spec_db,
        args.threshold_db,
        args.guard_bins,
        args.train_bins,
        args.min_distance_bins,
        args.max_peaks,
    )
    truth = read_truth_freqs(args.truth_lines)
    if args.band and truth:
        lo, hi = parse_range(args.band)
        truth = [f for f in truth if lo <= f <= hi]
    matches, missed, false_alarms = associate_freqs(peaks, truth, args.gate_hz) if truth else ([], [], peaks)
    errors = [m["error_hz"] for m in matches]
    search_bw = float(sub_freqs[-1] - sub_freqs[0]) if sub_freqs.size > 1 else None
    reliability = classification_metrics(len(matches), len(truth), len(peaks), len(false_alarms)) if truth else {}
    return {
        "mode": "psd",
        "settings": arg_settings(args),
        "detected_count": len(peaks),
        "detection_count": len(peaks),
        "truth_count": len(truth),
        "matched_count": len(matches),
        "missed_count": len(missed),
        "false_alarm_count": len(false_alarms),
        **reliability,
        "false_alarms_per_hz": (len(false_alarms) / search_bw) if search_bw else None,
        "error_summary": error_summary(errors),
        "mean_line_snr_db": float(np.mean([p["line_snr_db"] for p in peaks])) if peaks else None,
        "detections": peaks,
        "matches": matches,
        "missed_truth_freqs_hz": missed,
        "false_alarms": false_alarms,
    }


def parse_range(text: str) -> Tuple[float, float]:
    parts = text.replace(":", ",").split(",")
    if len(parts) != 2:
        raise ValueError(f"Expected range as lo:hi, got {text!r}")
    lo, hi = float(parts[0]), float(parts[1])
    return (lo, hi) if lo <= hi else (hi, lo)


def nearest_index(values: np.ndarray, value: float) -> int:
    return int(np.argmin(np.abs(values - value)))


def read_track(path: str) -> List[Dict[str, Any]]:
    rows = read_records(path)
    out: List[Dict[str, Any]] = []
    for i, row in enumerate(rows):
        freq = row.get("freq_hz")
        if freq is None or str(freq).strip() == "":
            continue
        time_val = row.get("time_s", i)
        out.append(
            {
                "time_s": float(time_val),
                "freq_hz": float(freq),
                "label": row.get("label", "truth"),
            }
        )
    return out


def frame_peaks(
    freqs: np.ndarray,
    frame_db: np.ndarray,
    threshold_db: float,
    guard_bins: int,
    train_bins: int,
    min_distance_bins: int,
    max_peaks: Optional[int],
) -> List[Dict[str, float]]:
    return detect_peaks(
        freqs,
        frame_db,
        threshold_db,
        guard_bins,
        train_bins,
        min_distance_bins,
        max_peaks,
    )


def cmd_lofar(args: argparse.Namespace) -> Dict[str, Any]:
    matrix = read_matrix(args.matrix)
    times = read_vector(args.times)
    freqs = read_vector(args.freqs)
    if matrix.shape != (times.size, freqs.size):
        if matrix.shape == (freqs.size, times.size):
            matrix = matrix.T
        else:
            raise ValueError(
                f"matrix shape {matrix.shape} does not match times x freqs "
                f"({times.size}, {freqs.size})"
            )
    mat_db = to_db(matrix, args.scale)
    all_detections: List[Dict[str, Any]] = []
    for ti, t in enumerate(times):
        peaks = frame_peaks(
            freqs,
            mat_db[ti],
            args.threshold_db,
            args.guard_bins,
            args.train_bins,
            args.min_distance_bins,
            args.max_peaks_per_frame,
        )
        for p in peaks:
            item = dict(p)
            item["time_s"] = float(t)
            item["frame"] = int(ti)
            all_detections.append(item)

    truth = read_track(args.truth_track) if args.truth_track else []
    matches: List[Dict[str, float]] = []
    missed: List[Dict[str, Any]] = []
    truth_match_flags: List[bool] = []
    matched_detection_ids = set()
    for tr in truth:
        ti = nearest_index(times, float(tr["time_s"]))
        if abs(float(times[ti]) - float(tr["time_s"])) > args.time_gate_s:
            missed.append(tr)
            truth_match_flags.append(False)
            continue
        frame_dets = [
            (i, d)
            for i, d in enumerate(all_detections)
            if int(d["frame"]) == ti and i not in matched_detection_ids
        ]
        best = None
        best_err = None
        for i, d in frame_dets:
            err = float(d["freq_hz"]) - float(tr["freq_hz"])
            if abs(err) <= args.gate_hz and (best_err is None or abs(err) < abs(best_err)):
                best = (i, d)
                best_err = err
        if best is None or best_err is None:
            missed.append(tr)
            truth_match_flags.append(False)
            continue
        matched_detection_ids.add(best[0])
        truth_match_flags.append(True)
        matches.append(
            {
                "time_s": float(times[ti]),
                "truth_freq_hz": float(tr["freq_hz"]),
                "detected_freq_hz": float(best[1]["freq_hz"]),
                "error_hz": float(best_err),
            }
        )

    false_alarms = [
        d for i, d in enumerate(all_detections) if truth and i not in matched_detection_ids
    ]
    errors = [m["error_hz"] for m in matches]
    reliability = classification_metrics(len(matches), len(truth), len(all_detections), len(false_alarms)) if truth else {}
    continuity = continuity_summary(truth_match_flags) if truth else {}
    time_rates = false_alarm_time_rates(len(false_alarms), observation_span_s_from_times(times)) if truth else {}
    return {
        "mode": "lofar",
        "settings": arg_settings(args),
        "frame_count": int(times.size),
        "frequency_bin_count": int(freqs.size),
        "detection_count": len(all_detections),
        "truth_count": len(truth),
        "matched_count": len(matches),
        "missed_count": len(missed),
        "false_alarm_count": len(false_alarms) if truth else None,
        **reliability,
        **continuity,
        "false_alarms_per_frame": (len(false_alarms) / max(times.size, 1)) if truth else None,
        **time_rates,
        "error_summary": error_summary(errors),
        "matches": matches,
        "missed_truth": missed,
        "sample_detections": all_detections[: min(50, len(all_detections))],
    }


def read_detection_rows(path: str) -> List[Dict[str, Any]]:
    rows = read_records(path)
    out: List[Dict[str, Any]] = []
    for row in rows:
        if not str(row.get("freq_hz", "")).strip():
            continue
        item = dict(row)
        item["freq_hz"] = float(row["freq_hz"])
        if str(row.get("time_s", "")).strip():
            item["time_s"] = float(row["time_s"])
        if str(row.get("score", "")).strip():
            item["score"] = float(row["score"])
        out.append(item)
    return out


def cmd_detections(args: argparse.Namespace) -> Dict[str, Any]:
    detections = read_detection_rows(args.detections)
    truth = read_detection_rows(args.truth)
    time_aware = any("time_s" in r for r in truth) or any("time_s" in r for r in detections)
    matches: List[Dict[str, float]] = []
    missed: List[Dict[str, Any]] = []
    truth_match_flags: List[bool] = []
    used = set()
    for tr in truth:
        best_i = None
        best_err = None
        for i, det in enumerate(detections):
            if i in used:
                continue
            if time_aware:
                if "time_s" not in tr or "time_s" not in det:
                    continue
                if abs(float(det["time_s"]) - float(tr["time_s"])) > args.time_gate_s:
                    continue
            err = float(det["freq_hz"]) - float(tr["freq_hz"])
            if abs(err) <= args.gate_hz and (best_err is None or abs(err) < abs(best_err)):
                best_i = i
                best_err = err
        if best_i is None or best_err is None:
            missed.append(tr)
            truth_match_flags.append(False)
            continue
        used.add(best_i)
        truth_match_flags.append(True)
        entry = {
            "truth_freq_hz": float(tr["freq_hz"]),
            "detected_freq_hz": float(detections[best_i]["freq_hz"]),
            "error_hz": float(best_err),
        }
        if time_aware:
            entry["time_s"] = float(tr.get("time_s", detections[best_i].get("time_s", 0.0)))
        matches.append(entry)
    false_alarms = [d for i, d in enumerate(detections) if i not in used]
    errors = [m["error_hz"] for m in matches]
    frame_count = None
    if time_aware:
        times = sorted({float(r["time_s"]) for r in truth if "time_s" in r})
        frame_count = len(times)
    reliability = classification_metrics(len(matches), len(truth), len(detections), len(false_alarms))
    continuity = continuity_summary(truth_match_flags) if time_aware else {}
    time_vals = [float(r["time_s"]) for r in truth + detections if "time_s" in r] if time_aware else []
    time_rates = false_alarm_time_rates(len(false_alarms), observation_span_s_from_times(time_vals)) if time_aware else {}
    return {
        "mode": "detections",
        "settings": arg_settings(args),
        "time_aware": time_aware,
        "detection_count": len(detections),
        "truth_count": len(truth),
        "matched_count": len(matches),
        "missed_count": len(missed),
        "false_alarm_count": len(false_alarms),
        **reliability,
        **continuity,
        "false_alarms_per_frame": (
            len(false_alarms) / frame_count if frame_count else None
        ),
        **time_rates,
        "error_summary": error_summary(errors),
        "matches": matches,
        "missed_truth": missed,
        "false_alarms": false_alarms,
    }


def read_metrics_table(path: str) -> List[Dict[str, Any]]:
    rows = read_records(path)
    for row in rows:
        for k, v in list(row.items()):
            if k == "algorithm" or k == "scenario":
                continue
            try:
                row[k] = float(v)
            except (TypeError, ValueError):
                pass
    return rows


def read_spec(path: str) -> List[Dict[str, Any]]:
    rows = read_records(path)
    spec: List[Dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["metric"] = row["metric"]
        item["direction"] = row.get("direction", "higher")
        item["weight"] = float(row.get("weight") or 1.0)
        item["critical"] = str(row.get("critical", "")).strip().lower() in {"1", "true", "yes"}
        if str(row.get("threshold", "")).strip():
            item["threshold"] = float(row["threshold"])
        spec.append(item)
    return spec


def normalize_metric(values: List[Optional[float]], direction: str) -> List[Optional[float]]:
    numeric = [v for v in values if v is not None and math.isfinite(v)]
    if not numeric:
        return [None for _ in values]
    lo, hi = min(numeric), max(numeric)
    if abs(hi - lo) < EPS:
        return [1.0 if v is not None else None for v in values]
    scores: List[Optional[float]] = []
    for v in values:
        if v is None or not math.isfinite(v):
            scores.append(None)
            continue
        raw = (v - lo) / (hi - lo)
        if direction == "lower":
            raw = 1.0 - raw
        scores.append(float(raw))
    return scores


def cmd_compare(args: argparse.Namespace) -> Dict[str, Any]:
    rows = read_metrics_table(args.metrics)
    spec = read_spec(args.spec)
    if not rows:
        raise ValueError("metrics table is empty")
    scores = {i: {"weighted": 0.0, "weight": 0.0, "missing": [], "failures": []} for i in range(len(rows))}
    for item in spec:
        metric = item["metric"]
        values: List[Optional[float]] = []
        for row in rows:
            val = row.get(metric)
            values.append(float(val) if isinstance(val, (int, float)) else None)
        norm = normalize_metric(values, item["direction"])
        for i, score in enumerate(norm):
            if score is None:
                scores[i]["missing"].append(metric)
                continue
            scores[i]["weighted"] += score * item["weight"]
            scores[i]["weight"] += item["weight"]
            threshold = item.get("threshold")
            if threshold is not None:
                raw = values[i]
                passed = raw >= threshold if item["direction"] == "higher" else raw <= threshold
                if not passed:
                    scores[i]["failures"].append(
                        {"metric": metric, "value": raw, "threshold": threshold, "critical": item["critical"]}
                    )
    results = []
    for i, row in enumerate(rows):
        weighted = scores[i]["weighted"]
        weight = scores[i]["weight"]
        failures = scores[i]["failures"]
        critical_fail = any(f["critical"] for f in failures)
        results.append(
            {
                "algorithm": row.get("algorithm", f"row_{i}"),
                "scenario": row.get("scenario"),
                "score": (weighted / weight) if weight else None,
                "critical_fail": critical_fail,
                "failures": failures,
                "missing_metrics": scores[i]["missing"],
                "raw": row,
            }
        )
    results.sort(key=lambda x: (-1 if x["critical_fail"] else 0, -(x["score"] or -1)))
    return {"mode": "compare", "settings": arg_settings(args), "results": results}


def emit(result: Dict[str, Any], output: Optional[str]) -> None:
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if output:
        Path(output).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    psd = sub.add_parser("psd", help="Detect and evaluate line peaks in one spectrum")
    psd.add_argument("--spectrum", required=True)
    psd.add_argument("--freqs", required=True)
    psd.add_argument("--scale", choices=["db", "linear"], default="db")
    psd.add_argument("--truth-lines")
    psd.add_argument("--band", help="Search band as lo:hi in Hz")
    psd.add_argument("--gate-hz", type=float, default=1.0)
    psd.add_argument("--threshold-db", type=float, default=6.0)
    psd.add_argument("--guard-bins", type=int, default=2)
    psd.add_argument("--train-bins", type=int, default=20)
    psd.add_argument("--min-distance-bins", type=int, default=2)
    psd.add_argument("--max-peaks", type=int)
    psd.add_argument("--output")
    psd.set_defaults(func=cmd_psd)

    lofar = sub.add_parser("lofar", help="Evaluate line detections in a LOFAR/time-frequency matrix")
    lofar.add_argument("--matrix", required=True)
    lofar.add_argument("--times", required=True)
    lofar.add_argument("--freqs", required=True)
    lofar.add_argument("--scale", choices=["db", "linear"], default="db")
    lofar.add_argument("--truth-track")
    lofar.add_argument("--gate-hz", type=float, default=1.0)
    lofar.add_argument("--time-gate-s", type=float, default=0.5)
    lofar.add_argument("--threshold-db", type=float, default=6.0)
    lofar.add_argument("--guard-bins", type=int, default=2)
    lofar.add_argument("--train-bins", type=int, default=20)
    lofar.add_argument("--min-distance-bins", type=int, default=2)
    lofar.add_argument("--max-peaks-per-frame", type=int, default=10)
    lofar.add_argument("--output")
    lofar.set_defaults(func=cmd_lofar)

    det = sub.add_parser("detections", help="Evaluate a detection table against truth")
    det.add_argument("--detections", required=True)
    det.add_argument("--truth", required=True)
    det.add_argument("--gate-hz", type=float, default=1.0)
    det.add_argument("--time-gate-s", type=float, default=0.5)
    det.add_argument("--output")
    det.set_defaults(func=cmd_detections)

    cmp_parser = sub.add_parser("compare", help="Compare algorithms from metrics and spec CSV files")
    cmp_parser.add_argument("--metrics", required=True)
    cmp_parser.add_argument("--spec", required=True)
    cmp_parser.add_argument("--mode", choices=["paper", "engineering", "dual"], default="dual")
    cmp_parser.add_argument("--output")
    cmp_parser.set_defaults(func=cmd_compare)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    result = args.func(args)
    emit(result, args.output)


if __name__ == "__main__":
    main()
