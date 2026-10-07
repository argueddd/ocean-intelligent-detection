#!/usr/bin/env python3
"""Compute lightweight underwater beamforming metrics from CSV or NPY data.

This utility covers common first-pass metrics for spatial spectra, DOA
estimates, frequency-bearing matrices, BTR matrices, beamformed time-domain
signals, output spectra, and time-frequency matrices. Adapt it for
project-specific MAT files, binary formats, or metadata conventions.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
from pathlib import Path
from typing import Iterable

import numpy as np


def parse_float_cell(value: str) -> float:
    text = value.strip()
    if text == "" or text.lower() in {"nan", "na", "none", "null"}:
        return float("nan")
    return float(text)


def load_array(path: str) -> np.ndarray:
    p = Path(path).expanduser()
    if p.suffix.lower() == ".npy":
        return np.asarray(np.load(p), dtype=float)
    if p.suffix.lower() == ".csv":
        with p.open("r", newline="") as f:
            rows = [[parse_float_cell(x) for x in row] for row in csv.reader(f) if row]
        if not rows:
            raise ValueError(f"No numeric rows found in {path}.")
        width = max(len(row) for row in rows)
        rows = [row + [float("nan")] * (width - len(row)) for row in rows]
        return np.asarray(rows, dtype=float)
    raise ValueError(f"Unsupported file type: {p.suffix}. Use .npy or .csv.")


def load_table(path: str) -> np.ndarray:
    arr = load_array(path)
    if arr.ndim == 1:
        return arr.reshape(-1, 1)
    if arr.ndim == 2:
        return arr
    raise ValueError("Table inputs must be 1D or 2D arrays.")


def parse_axis(value: str | None, n: int, label: str) -> np.ndarray:
    if value is None:
        return np.arange(n, dtype=float)
    path = Path(value).expanduser()
    if path.exists():
        arr = load_array(str(path)).reshape(-1)
        arr = arr[np.isfinite(arr)]
        if arr.size != n:
            raise ValueError(f"{label} count {arr.size} does not match expected length {n}.")
        return arr
    arr = np.asarray([float(x.strip()) for x in value.split(",") if x.strip()], dtype=float)
    if arr.size != n:
        raise ValueError(f"{label} count {arr.size} does not match expected length {n}.")
    return arr


def parse_angles(value: str | None, n: int) -> np.ndarray:
    return parse_axis(value, n, "Angle")


def to_db(values: np.ndarray, scale: str) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    if scale == "db":
        return values
    if scale == "power":
        return 10.0 * np.log10(np.maximum(values, np.finfo(float).tiny))
    if scale == "amplitude":
        return 20.0 * np.log10(np.maximum(np.abs(values), np.finfo(float).tiny))
    raise ValueError(f"Unsupported scale: {scale}")


def to_power(values: np.ndarray, scale: str) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    if scale == "db":
        return np.power(10.0, values / 10.0)
    if scale == "power":
        return np.maximum(values, 0.0)
    if scale == "amplitude":
        return np.square(np.abs(values))
    raise ValueError(f"Unsupported scale: {scale}")


def reduce_spectrum(values: np.ndarray, method: str, scale: str) -> tuple[np.ndarray, str]:
    """Reduce repeated spectra without averaging or summing logarithmic values.

    ``max`` is invariant under the monotonic dB conversion, so it can preserve
    the caller's scale.  ``mean`` and ``sum`` are energy operations and must be
    performed in linear power; their returned scale is therefore ``power``.
    """
    arr = np.asarray(values, dtype=float)
    if arr.ndim == 1:
        return arr, scale
    if method == "max":
        return np.nanmax(arr, axis=0), scale
    power = to_power(arr, scale)
    if method == "mean":
        return np.nanmean(power, axis=0), "power"
    if method == "sum":
        return np.nansum(power, axis=0), "power"
    raise ValueError(f"Unsupported reduction: {method}")


def circular_signed_error(estimate: float, truth: float) -> float:
    return float((estimate - truth + 180.0) % 360.0 - 180.0)


def circular_error(a: float, b: float) -> float:
    return abs(circular_signed_error(a, b))


def circular_mean_deg(values: Iterable[float]) -> float | None:
    arr = np.asarray([v for v in values if np.isfinite(v)], dtype=float)
    if arr.size == 0:
        return None
    radians = np.deg2rad(arr)
    mean_sin = float(np.mean(np.sin(radians)))
    mean_cos = float(np.mean(np.cos(radians)))
    return float(np.rad2deg(np.arctan2(mean_sin, mean_cos)))


def circular_std_deg(values: Iterable[float]) -> float | None:
    arr = np.asarray([v for v in values if np.isfinite(v)], dtype=float)
    if arr.size == 0:
        return None
    radians = np.deg2rad(arr)
    mean_sin = float(np.mean(np.sin(radians)))
    mean_cos = float(np.mean(np.cos(radians)))
    r = min(1.0, max(0.0, math.hypot(mean_sin, mean_cos)))
    if r <= 0.0:
        return 180.0
    return float(np.rad2deg(math.sqrt(max(0.0, -2.0 * math.log(r)))))


def local_maxima(y: np.ndarray) -> list[int]:
    if y.size < 3:
        return [int(np.argmax(y))]
    peaks: list[int] = []
    for i in range(1, y.size - 1):
        if y[i] >= y[i - 1] and y[i] >= y[i + 1] and (y[i] > y[i - 1] or y[i] > y[i + 1]):
            peaks.append(i)
    if y[0] > y[1]:
        peaks.insert(0, 0)
    if y[-1] > y[-2]:
        peaks.append(y.size - 1)
    return peaks or [int(np.argmax(y))]


def hpbw(angles: np.ndarray, spectrum_db: np.ndarray, peak_idx: int) -> float | None:
    threshold = spectrum_db[peak_idx] - 3.0
    left = peak_idx
    while left > 0 and spectrum_db[left] >= threshold:
        left -= 1
    right = peak_idx
    while right < spectrum_db.size - 1 and spectrum_db[right] >= threshold:
        right += 1
    if left == 0 or right == spectrum_db.size - 1:
        return None
    return float(abs(angles[right] - angles[left]))


def exclude_mainlobe(angles: np.ndarray, peak_angle: float, exclusion_deg: float) -> np.ndarray:
    return np.asarray([circular_error(a, peak_angle) > exclusion_deg for a in angles], dtype=bool)


def parse_truths(text: str | None) -> list[float]:
    if not text:
        return []
    return [float(x.strip()) for x in text.split(",") if x.strip()]


def nearest_errors(estimates: Iterable[float], truths: list[float]) -> list[dict[str, float]]:
    available = list(estimates)
    results: list[dict[str, float]] = []
    for truth in truths:
        if not available:
            break
        best = min(available, key=lambda est: circular_error(est, truth))
        available.remove(best)
        results.append({"truth_deg": truth, "estimate_deg": best, "abs_error_deg": circular_error(best, truth)})
    return results


def finite_row_values(row: np.ndarray) -> list[float]:
    return [float(v) for v in np.asarray(row, dtype=float).reshape(-1) if np.isfinite(v)]


def clean_float(value: float | None, digits: int = 10) -> float | None:
    if value is None or not np.isfinite(value):
        return None
    return float(round(float(value), digits))


def error_summary(errors: list[float], signed_errors: list[float] | None = None) -> dict[str, float | None]:
    if not errors:
        return {
            "mae_deg": None,
            "rmse_deg": None,
            "bias_deg": None,
            "std_deg": None,
            "p50_abs_error_deg": None,
            "p90_abs_error_deg": None,
        }
    err = np.asarray(errors, dtype=float)
    signed = np.asarray(signed_errors if signed_errors is not None else errors, dtype=float)
    return {
        "mae_deg": clean_float(float(np.mean(np.abs(err)))),
        "rmse_deg": clean_float(float(math.sqrt(np.mean(np.square(err))))),
        "bias_deg": clean_float(float(np.mean(signed))),
        "std_deg": clean_float(float(np.std(signed))),
        "p50_abs_error_deg": clean_float(float(np.percentile(np.abs(err), 50))),
        "p90_abs_error_deg": clean_float(float(np.percentile(np.abs(err), 90))),
    }


def summarize_spectrum(
    spectrum: np.ndarray,
    angles: np.ndarray,
    scale: str,
    raw_shape: list[int],
    reduction: str,
    mainlobe_exclusion_deg: float,
    false_peak_threshold_db: float,
    truth_deg: str | None,
    top_k: int,
) -> dict:
    spectrum_db = to_db(spectrum, scale)
    spectrum_db = np.where(np.isfinite(spectrum_db), spectrum_db, -np.inf)
    if not np.any(np.isfinite(spectrum_db)):
        raise ValueError("Spectrum contains no finite values.")

    peak_idx = int(np.argmax(spectrum_db))
    peak_angle = float(angles[peak_idx])
    peak_db = float(spectrum_db[peak_idx])
    peaks = sorted(local_maxima(spectrum_db), key=lambda idx: spectrum_db[idx], reverse=True)
    top_peaks = [
        {"angle_deg": float(angles[idx]), "level_db": float(spectrum_db[idx]), "relative_db": float(spectrum_db[idx] - peak_db)}
        for idx in peaks[:top_k]
    ]

    sidelobe_mask = exclude_mainlobe(angles, peak_angle, mainlobe_exclusion_deg)
    sidelobe_levels = spectrum_db[sidelobe_mask]
    psl_rel = None
    msr = None
    if sidelobe_levels.size:
        psl_abs = float(np.max(sidelobe_levels))
        psl_rel = float(psl_abs - peak_db)
        msr = float(peak_db - psl_abs)

    false_peak_count = 0
    for idx in peaks:
        if circular_error(float(angles[idx]), peak_angle) > mainlobe_exclusion_deg:
            if spectrum_db[idx] >= peak_db - false_peak_threshold_db:
                false_peak_count += 1

    truths = parse_truths(truth_deg)
    matched = nearest_errors((float(angles[idx]) for idx in peaks[: max(top_k, len(truths))]), truths)
    errors = [item["abs_error_deg"] for item in matched]

    return {
        "input_shape": raw_shape,
        "reduction": reduction,
        "scale": scale,
        "peak_angle_deg": peak_angle,
        "peak_level_db": peak_db,
        "hpbw_deg": hpbw(angles, spectrum_db, peak_idx),
        "peak_sidelobe_level_relative_db": psl_rel,
        "main_to_sidelobe_ratio_db": msr,
        "false_peak_count": false_peak_count,
        "top_peaks": top_peaks,
        "truth_matches": matched,
        "mae_deg": float(np.mean(errors)) if errors else None,
        "rmse_deg": float(math.sqrt(np.mean(np.square(errors)))) if errors else None,
    }


def spectrum_metrics(args: argparse.Namespace) -> dict:
    raw = load_array(args.power)
    spectrum, reduced_scale = reduce_spectrum(raw, args.reduce, args.scale)
    angles = parse_angles(args.angles, spectrum.size)
    return summarize_spectrum(
        spectrum=spectrum,
        angles=angles,
        scale=reduced_scale,
        raw_shape=list(raw.shape),
        reduction=args.reduce if raw.ndim > 1 else "none",
        mainlobe_exclusion_deg=args.mainlobe_exclusion_deg,
        false_peak_threshold_db=args.false_peak_threshold_db,
        truth_deg=args.truth_deg,
        top_k=args.top_k,
    )


def match_bearings(truths: list[float], estimates: list[float], gate_deg: float) -> tuple[list[dict], list[float], list[float]]:
    """One-to-one matching with maximum cardinality then minimum total error.

    A nearest-pair greedy matcher can lose valid detections.  This residual
    min-cost flow is dependency-free, deterministic for equal costs, and keeps
    augmenting until no gated truth-estimate path remains; that first maximizes
    match count and then minimizes total angular error for that count.
    """
    if gate_deg < 0 or not math.isfinite(gate_deg):
        raise ValueError("gate_deg must be a finite non-negative number.")

    truth_count = len(truths)
    estimate_count = len(estimates)
    source = 0
    truth_base = 1
    estimate_base = truth_base + truth_count
    sink = estimate_base + estimate_count
    graph: list[list[list[float | int]]] = [[] for _ in range(sink + 1)]

    def add_edge(start: int, stop: int, capacity: int, cost: float) -> list[float | int]:
        forward: list[float | int] = [stop, len(graph[stop]), capacity, cost]
        reverse: list[float | int] = [start, len(graph[start]), 0, -cost]
        graph[start].append(forward)
        graph[stop].append(reverse)
        return forward

    for truth_idx in range(truth_count):
        add_edge(source, truth_base + truth_idx, 1, 0.0)
    for estimate_idx in range(estimate_count):
        add_edge(estimate_base + estimate_idx, sink, 1, 0.0)

    assignment_edges: list[tuple[int, int, list[float | int]]] = []
    for truth_idx, truth in enumerate(truths):
        for estimate_idx, estimate in enumerate(estimates):
            error = circular_error(estimate, truth)
            if error <= gate_deg:
                edge = add_edge(truth_base + truth_idx, estimate_base + estimate_idx, 1, error)
                assignment_edges.append((truth_idx, estimate_idx, edge))

    node_count = len(graph)
    while True:
        distances = [float("inf")] * node_count
        previous: list[tuple[int, int] | None] = [None] * node_count
        distances[source] = 0.0
        for _ in range(node_count - 1):
            changed = False
            for node, edges in enumerate(graph):
                if not math.isfinite(distances[node]):
                    continue
                for edge_idx, edge in enumerate(edges):
                    stop, _, capacity, cost = edge
                    if int(capacity) <= 0:
                        continue
                    candidate = distances[node] + float(cost)
                    if candidate < distances[int(stop)] - 1e-12:
                        distances[int(stop)] = candidate
                        previous[int(stop)] = (node, edge_idx)
                        changed = True
            if not changed:
                break
        if previous[sink] is None:
            break
        node = sink
        while node != source:
            parent, edge_idx = previous[node]  # type: ignore[misc]
            edge = graph[parent][edge_idx]
            edge[2] = int(edge[2]) - 1
            reverse_idx = int(edge[1])
            graph[node][reverse_idx][2] = int(graph[node][reverse_idx][2]) + 1
            node = parent

    selected = sorted(
        (truth_idx, estimate_idx)
        for truth_idx, estimate_idx, edge in assignment_edges
        if int(edge[2]) == 0
    )
    used_truths = {truth_idx for truth_idx, _ in selected}
    used_estimates = {estimate_idx for _, estimate_idx in selected}
    matches: list[dict] = []
    for truth_idx, estimate_idx in selected:
        truth = truths[truth_idx]
        estimate = estimates[estimate_idx]
        signed_error = circular_signed_error(estimate, truth)
        matches.append({
            "truth_deg": clean_float(truth),
            "estimate_deg": clean_float(estimate),
            "signed_error_deg": clean_float(signed_error),
            "abs_error_deg": clean_float(abs(signed_error)),
        })

    unmatched_truths = [truths[i] for i in range(truth_count) if i not in used_truths]
    unmatched_estimates = [estimates[i] for i in range(estimate_count) if i not in used_estimates]
    return matches, unmatched_truths, unmatched_estimates


def doa_metrics(args: argparse.Namespace) -> dict:
    estimates = load_table(args.estimates)
    frame_count = int(estimates.shape[0])
    truth = load_table(args.truth) if args.truth else None
    if truth is not None and truth.shape[0] != frame_count:
        raise ValueError(f"Estimate frame count {frame_count} does not match truth frame count {truth.shape[0]}.")

    estimate_count = 0
    truth_count = 0
    matched_count = 0
    miss_count = 0
    false_alarm_count = 0
    frames_with_detection = 0
    frames_with_truth = 0
    frames_with_match = 0
    all_abs_errors: list[float] = []
    all_signed_errors: list[float] = []
    frame_summaries: list[dict] = []
    match_presence: list[bool] = []
    primary_estimates: list[float] = []

    for frame_idx in range(frame_count):
        frame_estimates = finite_row_values(estimates[frame_idx])
        estimate_count += len(frame_estimates)
        if frame_estimates:
            frames_with_detection += 1
            primary_estimates.append(frame_estimates[0])
        else:
            primary_estimates.append(float("nan"))

        if truth is None:
            if frame_idx < args.max_frame_output:
                frame_summaries.append({"frame": frame_idx, "estimates_deg": frame_estimates})
            continue

        frame_truths = finite_row_values(truth[frame_idx])
        truth_count += len(frame_truths)
        if frame_truths:
            frames_with_truth += 1
        matches, unmatched_truths, unmatched_estimates = match_bearings(frame_truths, frame_estimates, args.gate_deg)
        matched_count += len(matches)
        miss_count += len(unmatched_truths)
        false_alarm_count += len(unmatched_estimates)
        has_match = bool(matches)
        match_presence.append(has_match)
        if has_match:
            frames_with_match += 1
        for item in matches:
            all_abs_errors.append(float(item["abs_error_deg"]))
            all_signed_errors.append(float(item["signed_error_deg"]))
        if frame_idx < args.max_frame_output:
            frame_summaries.append(
                {
                    "frame": frame_idx,
                    "matches": matches,
                    "missed_truths_deg": unmatched_truths,
                    "false_estimates_deg": unmatched_estimates,
                }
            )

    result: dict[str, object] = {
        "frame_count": frame_count,
        "estimate_count": estimate_count,
        "frames_with_detection": frames_with_detection,
        "detection_frame_fraction": float(frames_with_detection / frame_count) if frame_count else None,
        "gate_deg": args.gate_deg,
        "frame_results_preview": frame_summaries,
    }

    if truth is None:
        finite_primary = [v for v in primary_estimates if np.isfinite(v)]
        jumps = [
            circular_error(primary_estimates[i], primary_estimates[i - 1])
            for i in range(1, len(primary_estimates))
            if np.isfinite(primary_estimates[i]) and np.isfinite(primary_estimates[i - 1])
        ]
        result.update(
            {
                "truth_available": False,
                "primary_bearing_mean_deg": circular_mean_deg(finite_primary),
                "primary_bearing_circular_std_deg": circular_std_deg(finite_primary),
                "primary_jump_mean_deg": float(np.mean(jumps)) if jumps else None,
                "primary_jump_max_deg": float(np.max(jumps)) if jumps else None,
            }
        )
        return result

    track_break_count = 0
    for prev, current in zip(match_presence, match_presence[1:]):
        if prev and not current:
            track_break_count += 1

    result.update(
        {
            "truth_available": True,
            "truth_count": truth_count,
            "matched_count": matched_count,
            "miss_count": miss_count,
            "false_alarm_count": false_alarm_count,
            "frames_with_truth": frames_with_truth,
            "frames_with_match": frames_with_match,
        "detection_probability": float(matched_count / truth_count) if truth_count else None,
        "miss_rate": float(miss_count / truth_count) if truth_count else None,
        "false_alarm_rate_per_frame": float(false_alarm_count / frame_count) if frame_count else None,
        "false_alarm_ratio_of_estimates": float(false_alarm_count / estimate_count) if estimate_count else None,
        "track_continuity": float(frames_with_match / frames_with_truth) if frames_with_truth else None,
            "track_break_count": track_break_count,
        }
    )
    result.update(error_summary(all_abs_errors, all_signed_errors))
    return result


def parse_frequency_band(value: str | None, freqs: np.ndarray) -> np.ndarray:
    if value is None:
        return np.ones(freqs.shape, dtype=bool)
    if ":" in value:
        left, right = value.split(":", 1)
    elif "," in value:
        left, right = value.split(",", 1)
    else:
        raise ValueError("Frequency band must be formatted as low:high or low,high.")
    low = float(left)
    high = float(right)
    if low > high:
        low, high = high, low
    mask = (freqs >= low) & (freqs <= high)
    if not np.any(mask):
        raise ValueError(f"Frequency band {low}:{high} selected no rows.")
    return mask


def fuse_frequency_bearing(selected: np.ndarray, scale: str, method: str) -> tuple[np.ndarray, str]:
    if method == "power-sum":
        return np.nansum(to_power(selected, scale), axis=0), "power"
    if method == "power-mean":
        return np.nanmean(to_power(selected, scale), axis=0), "power"
    selected_db = to_db(selected, scale)
    if method == "db-max":
        return np.nanmax(selected_db, axis=0), "db"
    if method == "db-mean":
        return np.nanmean(selected_db, axis=0), "db"
    raise ValueError(f"Unsupported fusion method: {method}")


def freq_bearing_metrics(args: argparse.Namespace) -> dict:
    matrix = load_array(args.matrix)
    if matrix.ndim != 2:
        raise ValueError("Frequency-bearing input must be a 2D matrix with rows=frequency and columns=bearing.")
    freqs = parse_axis(args.freqs, matrix.shape[0], "Frequency")
    angles = parse_angles(args.angles, matrix.shape[1])
    band_mask = parse_frequency_band(args.freq_band, freqs)
    selected = matrix[band_mask, :]
    selected_freqs = freqs[band_mask]
    matrix_db = to_db(selected, args.scale)
    matrix_db = np.where(np.isfinite(matrix_db), matrix_db, -np.inf)

    peak_angles: list[float] = []
    peak_levels: list[float] = []
    peak_errors: list[float] = []
    truths = parse_truths(args.truth_deg)
    for row in matrix_db:
        if not np.any(np.isfinite(row)):
            peak_angles.append(float("nan"))
            peak_levels.append(float("nan"))
            continue
        idx = int(np.argmax(row))
        peak_angle = float(angles[idx])
        peak_angles.append(peak_angle)
        peak_levels.append(float(row[idx]))
        if truths:
            peak_errors.append(min(circular_error(peak_angle, truth) for truth in truths))

    peak_mean = circular_mean_deg(peak_angles)
    peak_std = circular_std_deg(peak_angles)
    peak_mad = None
    if peak_mean is not None:
        deviations = [circular_error(angle, peak_mean) for angle in peak_angles if np.isfinite(angle)]
        peak_mad = float(np.median(deviations)) if deviations else None

    fused, fused_scale = fuse_frequency_bearing(selected, args.scale, args.fuse)
    fused_summary = summarize_spectrum(
        spectrum=fused,
        angles=angles,
        scale=fused_scale,
        raw_shape=list(matrix.shape),
        reduction=f"freq-bearing:{args.fuse}",
        mainlobe_exclusion_deg=args.mainlobe_exclusion_deg,
        false_peak_threshold_db=args.false_peak_threshold_db,
        truth_deg=args.truth_deg,
        top_k=args.top_k,
    )

    preview_count = min(args.max_frequency_output, selected_freqs.size)
    per_frequency_preview = [
        {
            "frequency": float(selected_freqs[i]),
            "peak_angle_deg": None if not np.isfinite(peak_angles[i]) else float(peak_angles[i]),
            "peak_level_db": None if not np.isfinite(peak_levels[i]) else float(peak_levels[i]),
        }
        for i in range(preview_count)
    ]

    consistency_score = None
    if peak_std is not None:
        consistency_score = float(max(0.0, 1.0 - min(90.0, peak_std) / 90.0))

    return {
        "input_shape": list(matrix.shape),
        "scale": args.scale,
        "frequency_band": {
            "requested": args.freq_band,
            "min": float(np.min(selected_freqs)),
            "max": float(np.max(selected_freqs)),
            "selected_freq_count": int(selected_freqs.size),
        },
        "fusion": args.fuse,
        "per_frequency_peak_count": int(sum(np.isfinite(peak_angles))),
        "per_frequency_peaks_preview": per_frequency_preview,
        "peak_bearing_mean_deg": peak_mean,
        "peak_bearing_circular_std_deg": peak_std,
        "peak_bearing_mad_deg": peak_mad,
        "frequency_consistency_score": consistency_score,
        "per_frequency_peak_error_mae_deg": float(np.mean(peak_errors)) if peak_errors else None,
        "per_frequency_peak_error_rmse_deg": float(math.sqrt(np.mean(np.square(peak_errors)))) if peak_errors else None,
        "fused_spectrum": fused_summary,
    }


def frame_candidates(row_db: np.ndarray, angles: np.ndarray, top_k: int, relative_threshold_db: float) -> list[dict]:
    row_db = np.where(np.isfinite(row_db), row_db, -np.inf)
    if not np.any(np.isfinite(row_db)):
        return []
    frame_max = float(np.max(row_db))
    peak_indices = sorted(local_maxima(row_db), key=lambda idx: row_db[idx], reverse=True)
    candidates: list[dict] = []
    for idx in peak_indices:
        level = float(row_db[idx])
        if not np.isfinite(level):
            continue
        if level < frame_max - relative_threshold_db:
            continue
        candidates.append(
            {
                "index": int(idx),
                "angle_deg": float(angles[idx]),
                "level_db": level,
                "relative_db": level - frame_max,
            }
        )
        if len(candidates) >= top_k:
            break
    return candidates


def background_level_db(row_db: np.ndarray, angles: np.ndarray, bearing_deg: float, exclusion_deg: float) -> float | None:
    finite = np.isfinite(row_db)
    if not np.any(finite):
        return None
    outside = np.asarray([circular_error(angle, bearing_deg) > exclusion_deg for angle in angles], dtype=bool)
    usable = finite & outside
    if not np.any(usable):
        usable = finite
    return clean_float(float(np.median(row_db[usable])))


def contrast_for_point(row_db: np.ndarray, angles: np.ndarray, bearing_deg: float, level_db: float, exclusion_deg: float) -> float | None:
    background = background_level_db(row_db, angles, bearing_deg, exclusion_deg)
    if background is None:
        return None
    return clean_float(level_db - background)


def first_truth(row: np.ndarray) -> float | None:
    values = finite_row_values(row)
    return values[0] if values else None


def sequence_jump_stats(track: list[float | None]) -> dict:
    jumps: list[float] = []
    previous: float | None = None
    for value in track:
        if value is None or not np.isfinite(value):
            continue
        if previous is not None:
            jumps.append(circular_error(value, previous))
        previous = value
    if not jumps:
        return {
            "mean_jump_deg": None,
            "median_jump_deg": None,
            "max_frame_jump_deg": None,
            "jump_std_deg": None,
        }
    arr = np.asarray(jumps, dtype=float)
    return {
        "mean_jump_deg": clean_float(float(np.mean(arr))),
        "median_jump_deg": clean_float(float(np.median(arr))),
        "max_frame_jump_deg": clean_float(float(np.max(arr))),
        "jump_std_deg": clean_float(float(np.std(arr))),
    }


def break_stats(presence: list[bool]) -> dict:
    break_count = 0
    current_gap = 0
    max_gap = 0
    seen_detection = False
    for present in presence:
        if present:
            if seen_detection and current_gap > 0:
                break_count += 1
            seen_detection = True
            current_gap = 0
        elif seen_detection:
            current_gap += 1
            max_gap = max(max_gap, current_gap)
    return {"track_break_count": break_count, "max_gap_length": max_gap}


def btr_truth_guided(
    matrix_db: np.ndarray,
    times: np.ndarray,
    angles: np.ndarray,
    truth: np.ndarray,
    args: argparse.Namespace,
) -> dict:
    truth_frame_count = 0
    detected_frame_count = 0
    presence: list[bool] = []
    track: list[float | None] = []
    contrasts: list[float] = []
    abs_errors: list[float] = []
    signed_errors: list[float] = []
    strong_secondary_frames = 0
    frame_preview: list[dict] = []

    for frame_idx, row in enumerate(matrix_db):
        row = np.where(np.isfinite(row), row, -np.inf)
        truth_deg = first_truth(truth[frame_idx])
        candidates = frame_candidates(row, angles, args.top_k, args.relative_threshold_db)
        if len(candidates) > 1 and candidates[1]["level_db"] >= candidates[0]["level_db"] - args.secondary_peak_threshold_db:
            strong_secondary_frames += 1

        detected = False
        estimate_deg: float | None = None
        estimate_level: float | None = None
        contrast: float | None = None
        signed_error: float | None = None
        abs_error: float | None = None

        if truth_deg is not None:
            truth_frame_count += 1
            gate_mask = np.asarray([circular_error(angle, truth_deg) <= args.gate_deg for angle in angles], dtype=bool)
            valid_mask = gate_mask & np.isfinite(row)
            if np.any(valid_mask):
                idx_options = np.where(valid_mask)[0]
                local_idx = int(idx_options[int(np.argmax(row[idx_options]))])
                frame_max = float(np.max(row[np.isfinite(row)]))
                level = float(row[local_idx])
                if level >= frame_max - args.relative_threshold_db:
                    estimate_deg = float(angles[local_idx])
                    estimate_level = level
                    signed_error = circular_signed_error(estimate_deg, truth_deg)
                    abs_error = abs(signed_error)
                    contrast = contrast_for_point(row, angles, estimate_deg, estimate_level, args.background_exclusion_deg)
                    detected = True
                    detected_frame_count += 1
                    abs_errors.append(abs_error)
                    signed_errors.append(signed_error)
                    if contrast is not None:
                        contrasts.append(contrast)

        if truth_deg is not None:
            presence.append(detected)
        track.append(estimate_deg)

        if frame_idx < args.max_frame_output:
            frame_preview.append(
                {
                    "frame": frame_idx,
                    "time": clean_float(float(times[frame_idx])),
                    "truth_deg": clean_float(truth_deg),
                    "estimate_deg": clean_float(estimate_deg),
                    "abs_error_deg": clean_float(abs_error),
                    "ridge_level_db": clean_float(estimate_level),
                    "ridge_contrast_db": clean_float(contrast),
                    "detected": detected,
                }
            )

    result: dict[str, object] = {
        "truth_available": True,
        "mode": "truth-guided",
        "truth_frame_count": truth_frame_count,
        "detected_frame_count": detected_frame_count,
        "track_continuity": clean_float(detected_frame_count / truth_frame_count) if truth_frame_count else None,
        "strong_secondary_peak_frame_fraction": clean_float(strong_secondary_frames / matrix_db.shape[0]) if matrix_db.shape[0] else None,
        "track_preview": frame_preview,
    }
    result.update(error_summary(abs_errors, signed_errors))
    result.update(sequence_jump_stats(track))
    result.update(break_stats(presence))
    if contrasts:
        arr = np.asarray(contrasts, dtype=float)
        result.update(
            {
                "ridge_contrast_mean_db": clean_float(float(np.mean(arr))),
                "ridge_contrast_median_db": clean_float(float(np.median(arr))),
                "ridge_contrast_p10_db": clean_float(float(np.percentile(arr, 10))),
            }
        )
    else:
        result.update({"ridge_contrast_mean_db": None, "ridge_contrast_median_db": None, "ridge_contrast_p10_db": None})
    return result


def btr_ridge_extraction(matrix_db: np.ndarray, times: np.ndarray, angles: np.ndarray, args: argparse.Namespace) -> dict:
    track: list[float | None] = []
    track_levels: list[float | None] = []
    contrasts: list[float] = []
    presence: list[bool] = []
    strong_secondary_frames = 0
    reinitialization_count = 0
    previous_angle: float | None = None
    frame_preview: list[dict] = []

    for frame_idx, row in enumerate(matrix_db):
        row = np.where(np.isfinite(row), row, -np.inf)
        candidates = frame_candidates(row, angles, args.top_k, args.relative_threshold_db)
        if len(candidates) > 1 and candidates[1]["level_db"] >= candidates[0]["level_db"] - args.secondary_peak_threshold_db:
            strong_secondary_frames += 1
        selected: dict | None = None
        reinitialized = False

        if candidates:
            if previous_angle is not None:
                linked = [c for c in candidates if circular_error(c["angle_deg"], previous_angle) <= args.max_jump_deg]
                if linked:
                    selected = max(linked, key=lambda item: item["level_db"])
                else:
                    selected = candidates[0]
                    reinitialized = True
                    reinitialization_count += 1
            else:
                selected = candidates[0]

        if selected is None:
            track.append(None)
            track_levels.append(None)
            presence.append(False)
            previous_angle = None
            contrast = None
        else:
            angle = float(selected["angle_deg"])
            level = float(selected["level_db"])
            contrast = contrast_for_point(row, angles, angle, level, args.background_exclusion_deg)
            track.append(angle)
            track_levels.append(level)
            presence.append(True)
            previous_angle = angle
            if contrast is not None:
                contrasts.append(contrast)

        if frame_idx < args.max_frame_output:
            frame_preview.append(
                {
                    "frame": frame_idx,
                    "time": clean_float(float(times[frame_idx])),
                    "estimate_deg": clean_float(track[-1]),
                    "ridge_level_db": clean_float(track_levels[-1]),
                    "ridge_contrast_db": clean_float(contrast),
                    "candidate_count": len(candidates),
                    "reinitialized": reinitialized,
                }
            )

    finite_track = [value for value in track if value is not None and np.isfinite(value)]
    result: dict[str, object] = {
        "truth_available": False,
        "mode": "ridge-extraction",
        "primary_track_frame_fraction": clean_float(sum(presence) / len(presence)) if presence else None,
        "primary_track_mean_bearing_deg": clean_float(circular_mean_deg(finite_track)),
        "primary_track_circular_std_deg": clean_float(circular_std_deg(finite_track)),
        "strong_secondary_peak_frame_fraction": clean_float(strong_secondary_frames / matrix_db.shape[0]) if matrix_db.shape[0] else None,
        "reinitialization_count": reinitialization_count,
        "warning": "No truth track was provided; accuracy metrics such as MAE/RMSE are not computed.",
        "track_preview": frame_preview,
    }
    result.update(sequence_jump_stats(track))
    result.update(break_stats(presence))
    if contrasts:
        arr = np.asarray(contrasts, dtype=float)
        result.update(
            {
                "ridge_contrast_mean_db": clean_float(float(np.mean(arr))),
                "ridge_contrast_median_db": clean_float(float(np.median(arr))),
                "ridge_contrast_p10_db": clean_float(float(np.percentile(arr, 10))),
            }
        )
    else:
        result.update({"ridge_contrast_mean_db": None, "ridge_contrast_median_db": None, "ridge_contrast_p10_db": None})
    return result


def btr_metrics(args: argparse.Namespace) -> dict:
    matrix = load_array(args.matrix)
    if matrix.ndim != 2:
        raise ValueError("BTR input must be a 2D matrix with rows=time/frame and columns=bearing.")
    times = parse_axis(args.times, matrix.shape[0], "Time")
    angles = parse_angles(args.angles, matrix.shape[1])
    matrix_db = to_db(matrix, args.scale)
    matrix_db = np.where(np.isfinite(matrix_db), matrix_db, -np.inf)

    result: dict[str, object] = {
        "input_shape": list(matrix.shape),
        "scale": args.scale,
        "time_count": int(matrix.shape[0]),
        "angle_count": int(matrix.shape[1]),
        "gate_deg": args.gate_deg,
        "top_k": args.top_k,
        "relative_threshold_db": args.relative_threshold_db,
        "max_allowed_jump_deg": args.max_jump_deg,
        "background_exclusion_deg": args.background_exclusion_deg,
    }

    if args.truth_track:
        truth = load_table(args.truth_track)
        if truth.shape[0] != matrix.shape[0]:
            raise ValueError(f"BTR frame count {matrix.shape[0]} does not match truth-track row count {truth.shape[0]}.")
        result.update(btr_truth_guided(matrix_db, times, angles, truth, args))
    else:
        result.update(btr_ridge_extraction(matrix_db, times, angles, args))
    return result


def select_column(data: np.ndarray, column: int, label: str) -> np.ndarray:
    arr = np.asarray(data, dtype=float)
    if arr.ndim == 1:
        return arr
    if arr.ndim != 2:
        raise ValueError(f"{label} must be a 1D array or a 2D table.")
    if arr.shape[1] == 1:
        return arr[:, 0]
    if arr.shape[0] == 1:
        return arr.reshape(-1)
    if column < 0 or column >= arr.shape[1]:
        raise ValueError(f"{label} column {column} is out of range for shape {arr.shape}.")
    return arr[:, column]


def parse_segment_seconds(value: str | None, fs: float, sample_count: int, label: str) -> tuple[int, int] | None:
    if value is None:
        return None
    if ":" in value:
        left, right = value.split(":", 1)
    elif "," in value:
        left, right = value.split(",", 1)
    else:
        raise ValueError(f"{label} must be formatted as start:end seconds.")
    start_s = float(left)
    end_s = float(right)
    if start_s < 0 or end_s <= start_s:
        raise ValueError(f"{label} must satisfy 0 <= start < end.")
    start = int(math.floor(start_s * fs))
    end = int(math.ceil(end_s * fs))
    if start < 0 or end > sample_count:
        duration = sample_count / fs
        raise ValueError(f"{label} {start_s}:{end_s}s is outside signal duration {duration}s.")
    return start, end


def parse_band(value: str | None, freqs: np.ndarray, label: str) -> tuple[np.ndarray | None, dict | None]:
    if value is None:
        return None, None
    mask = parse_frequency_band(value, freqs)
    selected = freqs[mask]
    return mask, {
        "requested": value,
        "min": clean_float(float(np.min(selected))),
        "max": clean_float(float(np.max(selected))),
        "bin_count": int(selected.size),
    }


def detrend_series(values: np.ndarray, mode: str) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    if mode == "none":
        return arr
    if mode == "mean":
        if not np.any(np.isfinite(arr)):
            return arr
        return arr - float(np.nanmean(arr))
    raise ValueError(f"Unsupported detrend mode: {mode}")


def mean_power(values: np.ndarray) -> float | None:
    arr = np.asarray(values, dtype=float)
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        return None
    return float(np.mean(np.square(finite)))


def db_from_power(power: float | None, eps: float = 1e-12) -> float | None:
    if power is None or not np.isfinite(power):
        return None
    return clean_float(10.0 * math.log10(max(power, eps)))


def db_ratio(numerator: float | None, denominator: float | None, eps: float = 1e-12) -> float | None:
    if numerator is None or denominator is None:
        return None
    return clean_float(10.0 * math.log10(max(numerator, eps) / max(denominator, eps)))


def series_segment_power(series: np.ndarray, segment: tuple[int, int] | None) -> float | None:
    if segment is None:
        return None
    start, end = segment
    return mean_power(series[start:end])


def add_prefixed_segment_metrics(
    result: dict,
    prefix: str,
    series: np.ndarray,
    target_segment: tuple[int, int] | None,
    noise_segment: tuple[int, int] | None,
    interference_segment: tuple[int, int] | None,
    eps: float,
) -> dict[str, float | None]:
    target_power = series_segment_power(series, target_segment)
    noise_power = series_segment_power(series, noise_segment)
    interference_power = series_segment_power(series, interference_segment)

    metrics = {
        "target_power": target_power,
        "noise_power": noise_power,
        "interference_power": interference_power,
        "segment_snr_db": db_ratio(target_power, noise_power, eps),
        "target_to_interference_ratio_db": db_ratio(target_power, interference_power, eps),
    }
    sinr = None
    if target_power is not None and noise_power is not None and interference_power is not None:
        sinr = db_ratio(target_power, noise_power + interference_power, eps)
    metrics["sinr_db"] = sinr

    result[f"{prefix}target_power_db"] = db_from_power(target_power, eps)
    result[f"{prefix}noise_power_db"] = db_from_power(noise_power, eps)
    result[f"{prefix}interference_power_db"] = db_from_power(interference_power, eps)
    result[f"{prefix}segment_snr_db"] = metrics["segment_snr_db"]
    result[f"{prefix}sinr_db"] = metrics["sinr_db"]
    result[f"{prefix}target_to_interference_ratio_db"] = metrics["target_to_interference_ratio_db"]
    return metrics


def signal_metrics(args: argparse.Namespace) -> dict:
    raw = load_array(args.signal)
    original = select_column(raw, args.column, "signal")
    dc_offset = clean_float(float(np.nanmean(original))) if np.any(np.isfinite(original)) else None
    signal = detrend_series(original, args.detrend)
    sample_count = int(signal.size)
    if args.fs <= 0:
        raise ValueError("--fs must be positive.")

    target_segment = parse_segment_seconds(args.target_segment, args.fs, sample_count, "target segment")
    noise_segment = parse_segment_seconds(args.noise_segment, args.fs, sample_count, "noise segment")
    interference_segment = parse_segment_seconds(args.interference_segment, args.fs, sample_count, "interference segment")

    signal_power = mean_power(signal)
    rms = math.sqrt(signal_power) if signal_power is not None else None
    peak = float(np.nanmax(np.abs(signal))) if np.any(np.isfinite(signal)) else None
    crest = None
    if peak is not None and rms is not None and rms > 0:
        crest = clean_float(20.0 * math.log10(max(peak, args.eps) / max(rms, args.eps)))

    result: dict[str, object] = {
        "input_shape": list(raw.shape),
        "column": args.column,
        "fs": clean_float(args.fs),
        "sample_count": sample_count,
        "duration_s": clean_float(sample_count / args.fs),
        "detrend": args.detrend,
        "rms": clean_float(rms),
        "peak": clean_float(peak),
        "crest_factor_db": crest,
        "dc_offset": dc_offset,
        "total_power_db": db_from_power(signal_power, args.eps),
    }
    output_metrics = add_prefixed_segment_metrics(result, "", signal, target_segment, noise_segment, interference_segment, args.eps)

    if args.baseline:
        baseline_raw = load_array(args.baseline)
        baseline = detrend_series(select_column(baseline_raw, args.column, "baseline"), args.detrend)
        if baseline.size != sample_count:
            raise ValueError(f"Baseline sample count {baseline.size} does not match signal sample count {sample_count}.")
        baseline_metrics = add_prefixed_segment_metrics(result, "baseline_", baseline, target_segment, noise_segment, interference_segment, args.eps)
        result["snr_improvement_db"] = clean_float(
            output_metrics["segment_snr_db"] - baseline_metrics["segment_snr_db"]
        ) if output_metrics["segment_snr_db"] is not None and baseline_metrics["segment_snr_db"] is not None else None
        result["target_power_change_db"] = clean_float(
            result["target_power_db"] - result["baseline_target_power_db"]
        ) if result["target_power_db"] is not None and result["baseline_target_power_db"] is not None else None
        result["noise_power_change_db"] = clean_float(
            result["noise_power_db"] - result["baseline_noise_power_db"]
        ) if result["noise_power_db"] is not None and result["baseline_noise_power_db"] is not None else None
        result["noise_power_reduction_db"] = clean_float(
            result["baseline_noise_power_db"] - result["noise_power_db"]
        ) if result["noise_power_db"] is not None and result["baseline_noise_power_db"] is not None else None
        result["interference_suppression_db"] = clean_float(
            result["baseline_interference_power_db"] - result["interference_power_db"]
        ) if result["interference_power_db"] is not None and result["baseline_interference_power_db"] is not None else None

    if args.reference:
        reference_raw = load_array(args.reference)
        reference = detrend_series(select_column(reference_raw, args.column, "reference"), args.detrend)
        if reference.size != sample_count:
            raise ValueError(f"Reference sample count {reference.size} does not match signal sample count {sample_count}.")
        finite = np.isfinite(signal) & np.isfinite(reference)
        if np.any(finite):
            sig = signal[finite]
            ref = reference[finite]
            if sig.size > 1 and float(np.std(sig)) > 0 and float(np.std(ref)) > 0:
                result["correlation_with_reference"] = clean_float(float(np.corrcoef(sig, ref)[0, 1]))
            else:
                result["correlation_with_reference"] = None
            nmse = float(np.mean(np.square(sig - ref)) / max(float(np.mean(np.square(ref))), args.eps))
            result["normalized_mse"] = clean_float(nmse)
            result["waveform_distortion_db"] = clean_float(10.0 * math.log10(max(nmse, args.eps)))
    return result


def band_power(power_values: np.ndarray, mask: np.ndarray | None, eps: float = 1e-12) -> float | None:
    if mask is None:
        return None
    values = np.asarray(power_values, dtype=float)[mask]
    values = values[np.isfinite(values)]
    if values.size == 0:
        return None
    return float(np.sum(values))


def band_power_db(power_values: np.ndarray, mask: np.ndarray | None, eps: float = 1e-12) -> float | None:
    return db_from_power(band_power(power_values, mask, eps), eps)


def band_peak(freqs: np.ndarray, spectrum_db: np.ndarray, mask: np.ndarray | None) -> tuple[float | None, float | None]:
    if mask is None or not np.any(mask):
        return None, None
    values = np.where(np.isfinite(spectrum_db), spectrum_db, -np.inf)
    masked_idx = np.where(mask)[0]
    if masked_idx.size == 0 or not np.any(np.isfinite(values[masked_idx])):
        return None, None
    idx = int(masked_idx[int(np.argmax(values[masked_idx]))])
    return clean_float(float(freqs[idx])), clean_float(float(values[idx]))


def floor_db(spectrum_db: np.ndarray, mask: np.ndarray | None = None, percentile: float = 50.0) -> float | None:
    values = np.asarray(spectrum_db, dtype=float)
    if mask is not None:
        values = values[mask]
    values = values[np.isfinite(values)]
    if values.size == 0:
        return None
    return clean_float(float(np.percentile(values, percentile)))


def exclusion_mask(freqs: np.ndarray, *bands: np.ndarray | None) -> np.ndarray:
    mask = np.ones(freqs.shape, dtype=bool)
    for band in bands:
        if band is not None:
            mask &= ~band
    if not np.any(mask):
        return np.ones(freqs.shape, dtype=bool)
    return mask


def spectrum_output_core(
    spectrum: np.ndarray,
    freqs: np.ndarray,
    scale: str,
    target_mask: np.ndarray | None,
    noise_mask: np.ndarray | None,
    interference_mask: np.ndarray | None,
    floor_percentile: float,
    eps: float,
) -> dict[str, float | None]:
    spectrum_power = to_power(spectrum, scale)
    spectrum_db = to_db(spectrum, scale)
    spectrum_db = np.where(np.isfinite(spectrum_db), spectrum_db, -np.inf)
    global_idx = int(np.argmax(spectrum_db)) if np.any(np.isfinite(spectrum_db)) else 0
    background_mask = exclusion_mask(freqs, target_mask, interference_mask)

    target_power_db = band_power_db(spectrum_power, target_mask, eps)
    noise_power_db = band_power_db(spectrum_power, noise_mask, eps)
    interference_power_db = band_power_db(spectrum_power, interference_mask, eps)
    target_peak_freq, target_peak_level = band_peak(freqs, spectrum_db, target_mask)
    noise_floor_median = floor_db(spectrum_db, noise_mask, 50.0) if noise_mask is not None else None
    background_floor = floor_db(spectrum_db, background_mask, floor_percentile)

    return {
        "global_peak_freq": clean_float(float(freqs[global_idx])) if np.any(np.isfinite(spectrum_db)) else None,
        "global_peak_level_db": clean_float(float(spectrum_db[global_idx])) if np.any(np.isfinite(spectrum_db)) else None,
        "background_floor_median_db": floor_db(spectrum_db, background_mask, 50.0),
        "background_floor_p90_db": floor_db(spectrum_db, background_mask, 90.0),
        "spectral_dynamic_range_db": clean_float(float(spectrum_db[global_idx]) - background_floor)
        if np.any(np.isfinite(spectrum_db)) and background_floor is not None else None,
        "target_band_power_db": target_power_db,
        "target_peak_freq": target_peak_freq,
        "target_peak_level_db": target_peak_level,
        "noise_band_power_db": noise_power_db,
        "noise_floor_median_db": noise_floor_median,
        "band_snr_db": clean_float(target_power_db - noise_power_db)
        if target_power_db is not None and noise_power_db is not None else None,
        "interference_band_power_db": interference_power_db,
        "target_to_interference_ratio_db": clean_float(target_power_db - interference_power_db)
        if target_power_db is not None and interference_power_db is not None else None,
    }


def spectrum_output_metrics(args: argparse.Namespace) -> dict:
    raw = load_array(args.spectrum)
    spectrum = select_column(raw, args.column, "spectrum")
    freqs = parse_axis(args.freqs, spectrum.size, "Frequency")
    target_mask, target_band = parse_band(args.target_band, freqs, "target band")
    noise_mask, noise_band = parse_band(args.noise_band, freqs, "noise band")
    interference_mask, interference_band = parse_band(args.interference_band, freqs, "interference band")

    result: dict[str, object] = {
        "input_shape": list(raw.shape),
        "column": args.column,
        "freq_count": int(spectrum.size),
        "scale": args.scale,
        "target_band": target_band,
        "noise_band": noise_band,
        "interference_band": interference_band,
    }
    result.update(
        spectrum_output_core(
            spectrum, freqs, args.scale, target_mask, noise_mask, interference_mask, args.floor_percentile, args.eps
        )
    )

    if args.baseline:
        baseline_raw = load_array(args.baseline)
        baseline = select_column(baseline_raw, args.column, "baseline")
        if baseline.size != spectrum.size:
            raise ValueError(f"Baseline frequency count {baseline.size} does not match spectrum count {spectrum.size}.")
        baseline_core = spectrum_output_core(
            baseline, freqs, args.scale, target_mask, noise_mask, interference_mask, args.floor_percentile, args.eps
        )
        for key, value in baseline_core.items():
            result[f"baseline_{key}"] = value
        result["band_snr_improvement_db"] = clean_float(result["band_snr_db"] - baseline_core["band_snr_db"]) \
            if result["band_snr_db"] is not None and baseline_core["band_snr_db"] is not None else None
        result["target_band_enhancement_db"] = clean_float(result["target_band_power_db"] - baseline_core["target_band_power_db"]) \
            if result["target_band_power_db"] is not None and baseline_core["target_band_power_db"] is not None else None
        result["noise_floor_reduction_db"] = clean_float(baseline_core["noise_floor_median_db"] - result["noise_floor_median_db"]) \
            if result["noise_floor_median_db"] is not None and baseline_core["noise_floor_median_db"] is not None else None
        result["interference_attenuation_db"] = clean_float(
            baseline_core["interference_band_power_db"] - result["interference_band_power_db"]
        ) if result["interference_band_power_db"] is not None and baseline_core["interference_band_power_db"] is not None else None
    return result


def db_sequence_stats(values: list[float]) -> dict[str, float | None]:
    arr = np.asarray([value for value in values if np.isfinite(value)], dtype=float)
    if arr.size == 0:
        return {"mean_db": None, "median_db": None, "p10_db": None, "std_db": None}
    return {
        "mean_db": clean_float(float(np.mean(arr))),
        "median_db": clean_float(float(np.median(arr))),
        "p10_db": clean_float(float(np.percentile(arr, 10))),
        "std_db": clean_float(float(np.std(arr))),
    }


def time_frequency_frame_metrics(
    matrix: np.ndarray,
    freqs: np.ndarray,
    scale: str,
    target_mask: np.ndarray,
    noise_mask: np.ndarray | None,
    interference_mask: np.ndarray | None,
    presence_threshold_db: float,
    floor_percentile: float,
    eps: float,
) -> dict[str, object]:
    power = to_power(matrix, scale)
    matrix_db = to_db(matrix, scale)
    matrix_db = np.where(np.isfinite(matrix_db), matrix_db, -np.inf)
    background_mask = exclusion_mask(freqs, target_mask, interference_mask)

    target_powers_db: list[float] = []
    noise_powers_db: list[float] = []
    interference_powers_db: list[float] = []
    snr_db: list[float] = []
    target_to_interference_db: list[float] = []
    floors_db: list[float] = []
    dominant_freqs: list[float] = []
    dominant_track: list[float | None] = []
    presence: list[bool] = []
    preview: list[dict] = []

    for frame_idx, row_db in enumerate(matrix_db):
        row_power = power[frame_idx]
        target_power_db = band_power_db(row_power, target_mask, eps)
        noise_power_db = band_power_db(row_power, noise_mask, eps)
        interference_power_db = band_power_db(row_power, interference_mask, eps)
        target_peak_freq, target_peak_level = band_peak(freqs, row_db, target_mask)
        frame_floor = floor_db(row_db, noise_mask if noise_mask is not None else background_mask, floor_percentile)
        present = False
        if target_peak_level is not None and frame_floor is not None:
            present = target_peak_level - frame_floor >= presence_threshold_db

        if target_power_db is not None:
            target_powers_db.append(target_power_db)
        if noise_power_db is not None:
            noise_powers_db.append(noise_power_db)
        if interference_power_db is not None:
            interference_powers_db.append(interference_power_db)
        if target_power_db is not None and noise_power_db is not None:
            snr_db.append(target_power_db - noise_power_db)
        if target_power_db is not None and interference_power_db is not None:
            target_to_interference_db.append(target_power_db - interference_power_db)
        if frame_floor is not None:
            floors_db.append(frame_floor)
        if present and target_peak_freq is not None:
            dominant_freqs.append(target_peak_freq)
            dominant_track.append(target_peak_freq)
        else:
            dominant_track.append(None)
        presence.append(present)

        preview.append(
            {
                "frame": frame_idx,
                "target_power_db": target_power_db,
                "noise_power_db": noise_power_db,
                "tf_snr_db": clean_float(target_power_db - noise_power_db)
                if target_power_db is not None and noise_power_db is not None else None,
                "target_peak_freq": target_peak_freq,
                "target_peak_level_db": target_peak_level,
                "noise_floor_db": frame_floor,
                "present": present,
            }
        )

    drift_range = None
    freq_std = None
    if dominant_freqs:
        freq_arr = np.asarray(dominant_freqs, dtype=float)
        drift_range = clean_float(float(np.max(freq_arr) - np.min(freq_arr)))
        freq_std = clean_float(float(np.std(freq_arr)))
    freq_jumps: list[float] = []
    previous_freq: float | None = None
    for freq in dominant_track:
        if freq is None:
            previous_freq = None
            continue
        if previous_freq is not None:
            freq_jumps.append(abs(freq - previous_freq))
        previous_freq = freq

    return {
        "target_band_power": db_sequence_stats(target_powers_db),
        "noise_band_power": db_sequence_stats(noise_powers_db),
        "interference_band_power": db_sequence_stats(interference_powers_db),
        "noise_floor": db_sequence_stats(floors_db),
        "tf_snr": db_sequence_stats(snr_db),
        "target_to_interference_ratio": db_sequence_stats(target_to_interference_db),
        "line_presence_fraction": clean_float(sum(presence) / len(presence)) if presence else None,
        "dominant_frequency_mean": clean_float(float(np.mean(dominant_freqs))) if dominant_freqs else None,
        "dominant_frequency_std": freq_std,
        "frequency_drift_range": drift_range,
        "mean_frequency_jump": clean_float(float(np.mean(freq_jumps))) if freq_jumps else None,
        "max_frequency_jump": clean_float(float(np.max(freq_jumps))) if freq_jumps else None,
        "presence": presence,
        "frame_preview": preview,
    }


def time_frequency_metrics(args: argparse.Namespace) -> dict:
    matrix = load_array(args.matrix)
    if matrix.ndim != 2:
        raise ValueError("Time-frequency input must be a 2D matrix with rows=time and columns=frequency.")
    times = parse_axis(args.times, matrix.shape[0], "Time")
    freqs = parse_axis(args.freqs, matrix.shape[1], "Frequency")
    target_mask, target_band = parse_band(args.target_band, freqs, "target band")
    if target_mask is None:
        raise ValueError("--target-band is required for time-frequency metrics.")
    noise_mask, noise_band = parse_band(args.noise_band, freqs, "noise band")
    interference_mask, interference_band = parse_band(args.interference_band, freqs, "interference band")

    frame_metrics = time_frequency_frame_metrics(
        matrix,
        freqs,
        args.scale,
        target_mask,
        noise_mask,
        interference_mask,
        args.presence_threshold_db,
        args.floor_percentile,
        args.eps,
    )
    presence = frame_metrics.pop("presence")
    preview = frame_metrics.pop("frame_preview")[: args.max_frame_output]

    result: dict[str, object] = {
        "input_shape": list(matrix.shape),
        "scale": args.scale,
        "time_count": int(matrix.shape[0]),
        "freq_count": int(matrix.shape[1]),
        "time_min": clean_float(float(np.min(times))),
        "time_max": clean_float(float(np.max(times))),
        "target_band": target_band,
        "noise_band": noise_band,
        "interference_band": interference_band,
        "presence_threshold_db": args.presence_threshold_db,
        "line_break_count": break_stats(presence)["track_break_count"],
        "max_line_gap_length": break_stats(presence)["max_gap_length"],
        "frame_preview": preview,
    }
    result.update(frame_metrics)

    if args.baseline:
        baseline = load_array(args.baseline)
        if baseline.shape != matrix.shape:
            raise ValueError(f"Baseline shape {baseline.shape} does not match time-frequency shape {matrix.shape}.")
        baseline_metrics = time_frequency_frame_metrics(
            baseline,
            freqs,
            args.scale,
            target_mask,
            noise_mask,
            interference_mask,
            args.presence_threshold_db,
            args.floor_percentile,
            args.eps,
        )
        result["target_band_enhancement_mean_db"] = clean_float(
            result["target_band_power"]["mean_db"] - baseline_metrics["target_band_power"]["mean_db"]
        ) if result["target_band_power"]["mean_db"] is not None and baseline_metrics["target_band_power"]["mean_db"] is not None else None
        result["noise_floor_reduction_mean_db"] = clean_float(
            baseline_metrics["noise_floor"]["mean_db"] - result["noise_floor"]["mean_db"]
        ) if result["noise_floor"]["mean_db"] is not None and baseline_metrics["noise_floor"]["mean_db"] is not None else None
        result["tf_snr_improvement_mean_db"] = clean_float(
            result["tf_snr"]["mean_db"] - baseline_metrics["tf_snr"]["mean_db"]
        ) if result["tf_snr"]["mean_db"] is not None and baseline_metrics["tf_snr"]["mean_db"] is not None else None
        result["interference_attenuation_mean_db"] = clean_float(
            baseline_metrics["interference_band_power"]["mean_db"] - result["interference_band_power"]["mean_db"]
        ) if result["interference_band_power"]["mean_db"] is not None and baseline_metrics["interference_band_power"]["mean_db"] is not None else None
    return result


def parse_bool(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "y", "是", "关键"}


def parse_optional_float(value: str | None) -> float | None:
    if value is None:
        return None
    text = value.strip()
    if text == "" or text.lower() in {"nan", "na", "none", "null"}:
        return None
    return float(text)


def read_csv_records(path: str) -> list[dict[str, str]]:
    p = Path(path).expanduser()
    with p.open("r", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError(f"{path} has no CSV header.")
        return [dict(row) for row in reader]


def load_metric_specs(path: str) -> list[dict]:
    rows = read_csv_records(path)
    specs: list[dict] = []
    for row_idx, row in enumerate(rows):
        metric = (row.get("metric") or "").strip()
        if not metric:
            raise ValueError(f"metric_spec row {row_idx + 1} is missing metric.")
        direction = (row.get("direction") or "").strip().lower()
        if direction not in {"higher", "lower"}:
            raise ValueError(f"Metric {metric} has unsupported direction {direction!r}; use higher or lower.")
        weight = parse_optional_float(row.get("weight"))
        if weight is not None and (not math.isfinite(weight) or weight < 0):
            raise ValueError(f"Metric {metric} weight must be a finite non-negative number.")
        specs.append(
            {
                "metric": metric,
                "display_name": (row.get("display_name") or metric).strip(),
                "direction": direction,
                "weight": 1.0 if weight is None else float(weight),
                "acceptable_min": parse_optional_float(row.get("acceptable_min")),
                "acceptable_max": parse_optional_float(row.get("acceptable_max")),
                "critical": parse_bool(row.get("critical")),
                "category": (row.get("category") or "").strip() or "uncategorized",
            }
        )
    names = [item["metric"] for item in specs]
    if len(names) != len(set(names)):
        raise ValueError("metric_spec contains duplicate metric names.")
    if not specs:
        raise ValueError("metric_spec contains no metric definitions.")
    return specs


def load_compare_candidates(path: str, specs: list[dict]) -> list[dict]:
    rows = read_csv_records(path)
    candidates: list[dict] = []
    seen_labels: dict[str, int] = {}
    for row_idx, row in enumerate(rows):
        algorithm = (row.get("algorithm") or "").strip()
        if not algorithm:
            raise ValueError(f"metrics row {row_idx + 1} is missing algorithm.")
        scenario = (row.get("scenario") or "").strip()
        base_label = algorithm if not scenario else f"{algorithm} [{scenario}]"
        seen_labels[base_label] = seen_labels.get(base_label, 0) + 1
        label = base_label if seen_labels[base_label] == 1 else f"{base_label} #{seen_labels[base_label]}"
        values = {spec["metric"]: parse_optional_float(row.get(spec["metric"])) for spec in specs}
        candidates.append(
            {
                "candidate_id": label,
                "algorithm": algorithm,
                "scenario": scenario or None,
                "row_index": row_idx,
                "values": values,
            }
        )
    return candidates


def metric_rankings(candidates: list[dict], specs: list[dict]) -> dict:
    rankings: dict[str, dict] = {}
    for spec in specs:
        metric = spec["metric"]
        available = [
            {
                "algorithm": candidate["algorithm"],
                "candidate_id": candidate["candidate_id"],
                "scenario": candidate["scenario"],
                "value": clean_float(candidate["values"].get(metric)),
            }
            for candidate in candidates
            if candidate["values"].get(metric) is not None
        ]
        reverse = spec["direction"] == "higher"
        available.sort(key=lambda item: item["value"], reverse=reverse)
        for idx, item in enumerate(available, start=1):
            item["rank"] = idx
        missing = [
            {"algorithm": candidate["algorithm"], "candidate_id": candidate["candidate_id"], "scenario": candidate["scenario"]}
            for candidate in candidates
            if candidate["values"].get(metric) is None
        ]
        rankings[metric] = {
            "display_name": spec["display_name"],
            "direction": spec["direction"],
            "category": spec["category"],
            "ranking": available,
            "missing": missing,
        }
    return rankings


def normalized_metric_scores(candidates: list[dict], spec: dict) -> dict[str, float | None]:
    metric = spec["metric"]
    values = [candidate["values"].get(metric) for candidate in candidates if candidate["values"].get(metric) is not None]
    if not values:
        return {candidate["candidate_id"]: None for candidate in candidates}
    min_value = min(values)
    max_value = max(values)
    scores: dict[str, float | None] = {}
    for candidate in candidates:
        value = candidate["values"].get(metric)
        if value is None:
            scores[candidate["candidate_id"]] = None
        elif max_value == min_value:
            scores[candidate["candidate_id"]] = 1.0
        elif spec["direction"] == "higher":
            scores[candidate["candidate_id"]] = (value - min_value) / (max_value - min_value)
        else:
            scores[candidate["candidate_id"]] = (max_value - value) / (max_value - min_value)
    return scores


def paper_evaluation(candidates: list[dict], specs: list[dict]) -> dict:
    total_weight = sum(max(0.0, spec["weight"]) for spec in specs)
    per_metric_scores = {spec["metric"]: normalized_metric_scores(candidates, spec) for spec in specs}
    rows: list[dict] = []
    advantages: dict[str, list[str]] = {}
    weaknesses: dict[str, list[str]] = {}

    for candidate in candidates:
        weighted = 0.0
        valid_weight = 0.0
        missing: list[str] = []
        category_scores: dict[str, list[float]] = {}
        for spec in specs:
            score = per_metric_scores[spec["metric"]][candidate["candidate_id"]]
            weight = max(0.0, spec["weight"])
            if score is None:
                missing.append(spec["metric"])
                continue
            weighted += score * weight
            valid_weight += weight
            category_scores.setdefault(spec["category"], []).append(score)
            if score >= 0.85:
                advantages.setdefault(candidate["candidate_id"], []).append(spec["display_name"])
            elif score <= 0.20:
                weaknesses.setdefault(candidate["candidate_id"], []).append(spec["display_name"])

        relative_score = clean_float(weighted / valid_weight) if valid_weight > 0 else None
        evidence_completeness = clean_float(valid_weight / total_weight) if total_weight > 0 else None
        evidence_adjusted_score = (
            clean_float(relative_score * evidence_completeness)
            if relative_score is not None and evidence_completeness is not None
            else None
        )
        rows.append(
            {
                "algorithm": candidate["algorithm"],
                "candidate_id": candidate["candidate_id"],
                "scenario": candidate["scenario"],
                "relative_score": relative_score,
                "evidence_completeness": evidence_completeness,
                "evidence_adjusted_score": evidence_adjusted_score,
                "missing_metrics": missing,
                "category_scores": {
                    category: clean_float(float(np.mean(scores))) for category, scores in category_scores.items()
                },
            }
        )

    rows.sort(key=lambda item: -1.0 if item["evidence_adjusted_score"] is None else item["evidence_adjusted_score"], reverse=True)
    for idx, row in enumerate(rows, start=1):
        row["rank"] = idx
    return {
        "relative_scores": rows,
        "best_candidate": rows[0]["candidate_id"] if rows and rows[0]["relative_score"] is not None else None,
        "main_advantages": advantages,
        "main_weaknesses": weaknesses,
        "note": "Ranking uses evidence_adjusted_score = relative_score * evidence_completeness. Relative scores compare only available metrics in this table and are not absolute engineering pass/fail results.",
    }


def check_threshold(value: float, spec: dict) -> tuple[bool | None, str | None]:
    lower = spec["acceptable_min"]
    upper = spec["acceptable_max"]
    if lower is None and upper is None:
        return None, None
    if value is None:
        return None, "missing_value"
    if lower is not None and value < lower:
        return False, f">= {lower}"
    if upper is not None and value > upper:
        return False, f"<= {upper}"
    parts = []
    if lower is not None:
        parts.append(f">= {lower}")
    if upper is not None:
        parts.append(f"<= {upper}")
    return True, " and ".join(parts)


def engineering_evaluation(candidates: list[dict], specs: list[dict]) -> dict:
    decisions: list[dict] = []
    for candidate in candidates:
        passed_weight = 0.0
        required_weight = 0.0
        pass_metrics: list[dict] = []
        fail_metrics: list[dict] = []
        missing_metrics: list[dict] = []
        critical_failures: list[dict] = []
        critical_missing: list[dict] = []
        no_threshold_metrics: list[str] = []

        for spec in specs:
            value = candidate["values"].get(spec["metric"])
            threshold_result, required = check_threshold(value, spec)
            if required is None:
                no_threshold_metrics.append(spec["metric"])
                if spec["critical"]:
                    critical_missing.append(
                        {
                            "metric": spec["metric"],
                            "display_name": spec["display_name"],
                            "value": clean_float(value),
                            "message": "critical 指标缺少工程阈值，不能判定通过。",
                        }
                    )
                continue

            weight = max(0.0, spec["weight"])
            required_weight += weight
            item = {
                "metric": spec["metric"],
                "display_name": spec["display_name"],
                "value": clean_float(value),
                "required": required,
                "critical": spec["critical"],
            }
            if threshold_result is True:
                passed_weight += weight
                pass_metrics.append(item)
            elif threshold_result is False:
                fail_metrics.append(item)
                if spec["critical"]:
                    critical_failures.append(
                        {
                            **item,
                            "message": f"{spec['display_name']} 为 critical 指标且未达工程阈值，综合分不能抵消。",
                        }
                    )
            else:
                missing_metrics.append(item)
                if spec["critical"]:
                    critical_missing.append(
                        {
                            **item,
                            "message": f"{spec['display_name']} 为 critical 指标但缺少数据，不能判定通过。",
                        }
                    )

        if critical_missing:
            decision = "信息不足"
            reason = "存在 critical 指标缺失或缺少阈值，不能判定通过。"
        elif critical_failures:
            decision = "不通过"
            reason = "存在 critical 指标未达标，触发一票否决；综合分不能抵消关键失败。"
        elif fail_metrics:
            decision = "有条件通过"
            reason = "critical 指标均通过，但存在非关键指标未达标。"
        elif missing_metrics:
            decision = "信息不足"
            reason = "存在已给验收阈值但缺少实测值的指标，不能判定通过。"
        elif required_weight <= 0:
            decision = "信息不足"
            reason = "没有可用于工程验收的阈值指标。"
        else:
            decision = "通过"
            reason = "所有带阈值的指标均通过，且无 critical 缺失或失败。"

        decisions.append(
            {
                "algorithm": candidate["algorithm"],
                "candidate_id": candidate["candidate_id"],
                "scenario": candidate["scenario"],
                "decision": decision,
                "reason": reason,
                "acceptance_score": clean_float(passed_weight / required_weight) if required_weight > 0 else None,
                "passed_metrics": pass_metrics,
                "failed_metrics": fail_metrics,
                "missing_metrics": missing_metrics,
                "critical_failures": critical_failures,
                "critical_missing": critical_missing,
                "metrics_without_threshold": no_threshold_metrics,
                "critical_rule": "critical=true 的指标为工程关键指标；任一 critical 指标失败时，该算法不能判定为通过，综合分不能抵消关键失败。",
            }
        )

    decision_order = {"通过": 0, "有条件通过": 1, "信息不足": 2, "不通过": 3}
    decisions.sort(
        key=lambda item: (
            decision_order.get(item["decision"], 9),
            -1.0 if item["acceptance_score"] is None else -item["acceptance_score"],
        )
    )
    return {
        "decisions": decisions,
        "critical_rule": "critical=true 的指标为工程关键指标；任一 critical 指标失败时，该算法不能判定为通过，综合分不能抵消关键失败。",
    }


def compare_metrics(args: argparse.Namespace) -> dict:
    specs = load_metric_specs(args.spec)
    candidates = load_compare_candidates(args.metrics, specs)
    rankings = metric_rankings(candidates, specs)
    result: dict[str, object] = {
        "mode": args.mode,
        "candidate_count": len(candidates),
        "metrics": [
            {
                "metric": spec["metric"],
                "display_name": spec["display_name"],
                "direction": spec["direction"],
                "weight": clean_float(spec["weight"]),
                "acceptable_min": clean_float(spec["acceptable_min"]),
                "acceptable_max": clean_float(spec["acceptable_max"]),
                "critical": spec["critical"],
                "category": spec["category"],
            }
            for spec in specs
        ],
        "candidates": [
            {"candidate_id": candidate["candidate_id"], "algorithm": candidate["algorithm"], "scenario": candidate["scenario"]}
            for candidate in candidates
        ],
        "metric_rankings": rankings,
    }
    if args.mode in {"paper", "dual"}:
        result["paper_evaluation"] = paper_evaluation(candidates, specs)
    if args.mode in {"engineering", "dual"}:
        result["engineering_acceptance"] = engineering_evaluation(candidates, specs)
    if args.mode == "dual":
        result["recommendation_basis"] = "Use paper relative_score for research evidence and engineering decision/critical failures for deployability; do not let relative_score override critical failures."
    return result


def require_matplotlib():
    mpl_dir = Path("/private/tmp/beamforming_metrics_mpl").expanduser()
    mpl_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(mpl_dir))
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches
        from matplotlib.colors import BoundaryNorm, ListedColormap
    except Exception as exc:  # pragma: no cover - exercised only when matplotlib is absent/broken.
        raise RuntimeError("Plotting commands require matplotlib. Install matplotlib or run metric commands without plotting.") from exc
    return plt, mpatches, BoundaryNorm, ListedColormap


def load_json_file(path: str) -> dict:
    with Path(path).expanduser().open("r") as f:
        return json.load(f)


def safe_filename(text: str) -> str:
    cleaned = []
    for ch in text:
        if ch.isalnum() or ch in {"-", "_"}:
            cleaned.append(ch)
        else:
            cleaned.append("_")
    name = "".join(cleaned).strip("_")
    return name or "metric"


def save_plot(fig, path: Path, dpi: int) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=dpi, bbox_inches="tight")
    return str(path)


def candidate_label(item: dict) -> str:
    return str(item.get("candidate_id") or item.get("algorithm") or "")


def decision_color(decision: str | None) -> str:
    return {
        "通过": "#2ca25f",
        "有条件通过": "#fdae61",
        "不通过": "#d73027",
        "信息不足": "#969696",
    }.get(decision or "", "#bdbdbd")


def decision_label(decision: str | None) -> str:
    return {
        "通过": "Pass",
        "有条件通过": "Conditional",
        "不通过": "Fail",
        "信息不足": "Insufficient",
    }.get(decision or "", "Unknown")


def plot_paper_relative_score(compare_data: dict, output_dir: Path, dpi: int) -> str | None:
    paper = compare_data.get("paper_evaluation")
    if not paper:
        return None
    rows = paper.get("relative_scores", [])
    if not rows:
        return None
    plt, _, _, _ = require_matplotlib()
    labels = [candidate_label(row) for row in rows]
    values = [
        0.0
        if (row.get("evidence_adjusted_score", row.get("relative_score"))) is None
        else float(row.get("evidence_adjusted_score", row.get("relative_score")))
        for row in rows
    ]
    completeness = [row.get("evidence_completeness") for row in rows]

    fig, ax = plt.subplots(figsize=(max(7, 0.65 * len(labels)), 4.2))
    bars = ax.bar(labels, values, color="#4c78a8")
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("Evidence-adjusted score")
    ax.set_title("Paper Evidence-Adjusted Score")
    ax.tick_params(axis="x", rotation=30)
    for bar, row, complete in zip(bars, rows, completeness):
        adjusted = row.get("evidence_adjusted_score", row.get("relative_score"))
        text = f"{adjusted:.2f}" if adjusted is not None else "NA"
        if complete is not None and complete < 1:
            rel = row.get("relative_score")
            rel_text = "NA" if rel is None else f"{rel:.2f}"
            text += f"\nrel {rel_text}, comp {complete:.2f}"
            bar.set_hatch("//")
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.02, text, ha="center", va="bottom", fontsize=8)
    return save_plot(fig, output_dir / "paper_relative_score.png", dpi)


def plot_engineering_acceptance_score(compare_data: dict, output_dir: Path, dpi: int) -> str | None:
    engineering = compare_data.get("engineering_acceptance")
    if not engineering:
        return None
    rows = engineering.get("decisions", [])
    if not rows:
        return None
    plt, mpatches, _, _ = require_matplotlib()
    labels = [candidate_label(row) for row in rows]
    values = [0.0 if row.get("acceptance_score") is None else float(row["acceptance_score"]) for row in rows]
    colors = [decision_color(row.get("decision")) for row in rows]

    fig, ax = plt.subplots(figsize=(max(7, 0.70 * len(labels)), 4.6))
    bars = ax.bar(labels, values, color=colors)
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("Acceptance score")
    ax.set_title("Engineering Acceptance Score")
    ax.tick_params(axis="x", rotation=30)
    for bar, row in zip(bars, rows):
        critical_fail = len(row.get("critical_failures", []))
        critical_missing = len(row.get("critical_missing", []))
        suffix = ""
        if critical_fail:
            suffix = f"\ncritical fail {critical_fail}"
        elif critical_missing:
            suffix = f"\ncritical missing {critical_missing}"
        score = "NA" if row.get("acceptance_score") is None else f"{row['acceptance_score']:.2f}"
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.02,
            f"{score}\n{decision_label(row.get('decision'))}{suffix}",
            ha="center",
            va="bottom",
            fontsize=8,
        )
    patches = [
        mpatches.Patch(color="#2ca25f", label="Pass"),
        mpatches.Patch(color="#fdae61", label="Conditional"),
        mpatches.Patch(color="#d73027", label="Fail"),
        mpatches.Patch(color="#969696", label="Insufficient"),
    ]
    ax.legend(handles=patches, loc="upper right", fontsize=8)
    return save_plot(fig, output_dir / "engineering_acceptance_score.png", dpi)


def plot_engineering_heatmap(compare_data: dict, output_dir: Path, dpi: int) -> str | None:
    engineering = compare_data.get("engineering_acceptance")
    metrics = compare_data.get("metrics", [])
    if not engineering or not metrics:
        return None
    decisions = engineering.get("decisions", [])
    if not decisions:
        return None

    metric_ids = [metric["metric"] for metric in metrics]
    metric_to_col = {metric: idx for idx, metric in enumerate(metric_ids)}
    matrix = np.zeros((len(decisions), len(metric_ids)), dtype=int)

    for row_idx, decision in enumerate(decisions):
        for item in decision.get("passed_metrics", []):
            if item["metric"] in metric_to_col:
                matrix[row_idx, metric_to_col[item["metric"]]] = 1
        for item in decision.get("failed_metrics", []):
            if item["metric"] in metric_to_col:
                matrix[row_idx, metric_to_col[item["metric"]]] = 3 if item.get("critical") else 2
        for item in decision.get("missing_metrics", []):
            if item["metric"] in metric_to_col:
                matrix[row_idx, metric_to_col[item["metric"]]] = 5 if item.get("critical") else 4

    plt, mpatches, BoundaryNorm, ListedColormap = require_matplotlib()
    colors = ["#e8f1fb", "#2ca25f", "#fdae61", "#b2182b", "#bdbdbd", "#525252"]
    cmap = ListedColormap(colors)
    norm = BoundaryNorm(np.arange(-0.5, 6.5, 1), cmap.N)
    fig, ax = plt.subplots(figsize=(max(8, 0.85 * len(metric_ids)), max(3.8, 0.55 * len(decisions))))
    ax.imshow(matrix, cmap=cmap, norm=norm, aspect="auto")
    ax.set_xticks(np.arange(len(metric_ids)))
    ax.set_xticklabels(metric_ids, rotation=45, ha="right", fontsize=8)
    ax.set_yticks(np.arange(len(decisions)))
    ax.set_yticklabels([candidate_label(row) for row in decisions], fontsize=8)
    ax.set_title("Engineering Pass/Fail Heatmap")
    symbols = {0: "N/A", 1: "PASS", 2: "FAIL", 3: "CRIT", 4: "MISS", 5: "C-MISS"}
    for i in range(matrix.shape[0]):
        for j in range(matrix.shape[1]):
            ax.text(j, i, symbols[int(matrix[i, j])], ha="center", va="center", fontsize=7, color="white" if matrix[i, j] in {3, 5} else "black")
    legend = [
        mpatches.Patch(color=colors[0], label="No threshold"),
        mpatches.Patch(color=colors[1], label="Pass"),
        mpatches.Patch(color=colors[2], label="Non-critical fail"),
        mpatches.Patch(color=colors[3], label="Critical fail"),
        mpatches.Patch(color=colors[4], label="Missing"),
        mpatches.Patch(color=colors[5], label="Critical missing"),
    ]
    ax.legend(handles=legend, loc="upper left", bbox_to_anchor=(1.01, 1.0), fontsize=8)
    return save_plot(fig, output_dir / "engineering_pass_fail_heatmap.png", dpi)


def plot_metric_rankings(compare_data: dict, output_dir: Path, dpi: int) -> list[str]:
    rankings = compare_data.get("metric_rankings", {})
    specs = {metric["metric"]: metric for metric in compare_data.get("metrics", [])}
    if not rankings:
        return []
    plt, _, _, _ = require_matplotlib()
    files: list[str] = []
    metric_dir = output_dir / "metrics"
    for metric, detail in rankings.items():
        rows = detail.get("ranking", [])
        if not rows:
            continue
        labels = [candidate_label(row) for row in rows]
        values = [float(row["value"]) for row in rows]
        direction = detail.get("direction")
        spec = specs.get(metric, {})
        fig, ax = plt.subplots(figsize=(max(7, 0.70 * len(labels)), 4.2))
        bars = ax.bar(labels, values, color="#72b7b2")
        ax.set_title(f"{metric} ranking ({direction}-is-better)")
        ax.set_ylabel(metric)
        ax.tick_params(axis="x", rotation=30)
        if spec.get("acceptable_min") is not None:
            ax.axhline(float(spec["acceptable_min"]), color="#2ca25f", linestyle="--", linewidth=1, label="acceptable_min")
        if spec.get("acceptable_max") is not None:
            ax.axhline(float(spec["acceptable_max"]), color="#d73027", linestyle="--", linewidth=1, label="acceptable_max")
        if spec.get("acceptable_min") is not None or spec.get("acceptable_max") is not None:
            ax.legend(fontsize=8)
        for bar, value in zip(bars, values):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(), f"{value:g}", ha="center", va="bottom", fontsize=8)
        missing_count = len(detail.get("missing", []))
        if missing_count:
            ax.text(0.99, 0.95, f"missing: {missing_count}", ha="right", va="top", transform=ax.transAxes, fontsize=8)
        files.append(save_plot(fig, metric_dir / f"metric_{safe_filename(metric)}.png", dpi))
    return files


def plot_compare(args: argparse.Namespace) -> dict:
    compare_data = load_json_file(args.compare_json)
    output_dir = Path(args.output_dir).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    generated: list[str] = []
    for path in (
        plot_paper_relative_score(compare_data, output_dir, args.dpi),
        plot_engineering_acceptance_score(compare_data, output_dir, args.dpi),
        plot_engineering_heatmap(compare_data, output_dir, args.dpi),
    ):
        if path:
            generated.append(path)
    if not args.skip_metric_plots:
        generated.extend(plot_metric_rankings(compare_data, output_dir, args.dpi))
    return {
        "output_dir": str(output_dir),
        "generated_count": len(generated),
        "files": generated,
    }


def metric_spec_by_name(specs: list[dict]) -> dict[str, dict]:
    return {spec["metric"]: spec for spec in specs}


def is_better_or_equal(a: float, b: float, direction: str) -> bool:
    return a >= b if direction == "higher" else a <= b


def is_strictly_better(a: float, b: float, direction: str) -> bool:
    return a > b if direction == "higher" else a < b


def pareto_points(candidates: list[dict], x_metric: str, y_metric: str, x_direction: str, y_direction: str) -> list[dict]:
    points: list[dict] = []
    for candidate in candidates:
        x = candidate["values"].get(x_metric)
        y = candidate["values"].get(y_metric)
        if x is None or y is None:
            continue
        points.append(
            {
                "algorithm": candidate["algorithm"],
                "candidate_id": candidate["candidate_id"],
                "scenario": candidate["scenario"],
                "x": float(x),
                "y": float(y),
                "pareto": False,
                "dominated_by": [],
            }
        )

    for idx, point in enumerate(points):
        dominated_by: list[str] = []
        for other_idx, other in enumerate(points):
            if idx == other_idx:
                continue
            no_worse = is_better_or_equal(other["x"], point["x"], x_direction) and is_better_or_equal(other["y"], point["y"], y_direction)
            strictly_better = is_strictly_better(other["x"], point["x"], x_direction) or is_strictly_better(other["y"], point["y"], y_direction)
            if no_worse and strictly_better:
                dominated_by.append(other["candidate_id"])
        point["dominated_by"] = dominated_by
        point["pareto"] = not dominated_by
    return points


def pareto_sort_key(point: dict, x_direction: str) -> float:
    return point["x"] if x_direction == "lower" else -point["x"]


def plot_pareto(args: argparse.Namespace) -> dict:
    specs = load_metric_specs(args.spec)
    spec_map = metric_spec_by_name(specs)
    if args.x not in spec_map:
        raise ValueError(f"x metric {args.x!r} was not found in metric spec.")
    if args.y not in spec_map:
        raise ValueError(f"y metric {args.y!r} was not found in metric spec.")
    candidates = load_compare_candidates(args.metrics, specs)
    if args.scenario:
        candidates = [candidate for candidate in candidates if candidate["scenario"] == args.scenario]
    if not candidates:
        raise ValueError("No candidates remain after applying filters.")

    x_spec = spec_map[args.x]
    y_spec = spec_map[args.y]
    points = pareto_points(candidates, args.x, args.y, x_spec["direction"], y_spec["direction"])
    if not points:
        raise ValueError("No candidates have both x and y metric values.")

    pareto_front = sorted([point for point in points if point["pareto"]], key=lambda item: pareto_sort_key(item, x_spec["direction"]))
    dominated = [point for point in points if not point["pareto"]]

    plt, _, _, _ = require_matplotlib()
    fig, ax = plt.subplots(figsize=(7.2, 5.2))
    dominated_points = dominated
    if dominated_points:
        ax.scatter(
            [point["x"] for point in dominated_points],
            [point["y"] for point in dominated_points],
            color="#bdbdbd",
            edgecolor="#636363",
            s=70,
            label="Dominated",
            zorder=2,
        )
    ax.scatter(
        [point["x"] for point in pareto_front],
        [point["y"] for point in pareto_front],
        color="#2b8cbe",
        edgecolor="#045a8d",
        s=85,
        label="Pareto front",
        zorder=3,
    )
    if len(pareto_front) >= 2:
        ax.plot([point["x"] for point in pareto_front], [point["y"] for point in pareto_front], color="#2b8cbe", linewidth=1.5, zorder=1)
    if args.label_points:
        for point in points:
            ax.annotate(point["algorithm"], (point["x"], point["y"]), xytext=(5, 5), textcoords="offset points", fontsize=8)
    ax.set_xlabel(f"{args.x} ({x_spec['direction']} is better)")
    ax.set_ylabel(f"{args.y} ({y_spec['direction']} is better)")
    title = f"Pareto: {args.x} vs {args.y}"
    if args.scenario:
        title += f" [{args.scenario}]"
    ax.set_title(title)
    ax.grid(True, linestyle="--", alpha=0.35)
    ax.legend(fontsize=8)

    output_path = Path(args.output).expanduser()
    png_path = save_plot(fig, output_path, args.dpi)
    json_path = output_path.with_suffix(".json")
    summary = {
        "x_metric": args.x,
        "y_metric": args.y,
        "x_direction": x_spec["direction"],
        "y_direction": y_spec["direction"],
        "scenario": args.scenario,
        "pareto_front": [point["candidate_id"] for point in pareto_front],
        "dominated": [point["candidate_id"] for point in dominated],
        "points": [
            {
                "algorithm": point["algorithm"],
                "candidate_id": point["candidate_id"],
                "scenario": point["scenario"],
                "x": clean_float(point["x"]),
                "y": clean_float(point["y"]),
                "pareto": point["pareto"],
                "dominated_by": point["dominated_by"],
            }
            for point in points
        ],
        "files": {"png": png_path, "json": str(json_path)},
    }
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def aggregate_values(values: list[float], method: str) -> float:
    arr = np.asarray(values, dtype=float)
    if method == "mean":
        return float(np.mean(arr))
    if method == "median":
        return float(np.median(arr))
    if method == "min":
        return float(np.min(arr))
    if method == "max":
        return float(np.max(arr))
    raise ValueError(f"Unsupported aggregate method: {method}")


def parse_x_numeric(text: str) -> float | None:
    stripped = text.strip()
    if stripped == "" or stripped.lower() in {"nan", "na", "none", "null"}:
        return None
    try:
        return float(stripped)
    except ValueError:
        return None


def summarize_series_points(points: list[dict], y_direction: str) -> dict:
    values = [point["y"] for point in points]
    if not values:
        return {
            "valid_count": 0,
            "mean_y": None,
            "std_y": None,
            "best_y": None,
            "best_x": None,
            "worst_y": None,
            "worst_x": None,
        }
    best = max(points, key=lambda item: item["y"]) if y_direction == "higher" else min(points, key=lambda item: item["y"])
    worst = min(points, key=lambda item: item["y"]) if y_direction == "higher" else max(points, key=lambda item: item["y"])
    return {
        "valid_count": len(points),
        "mean_y": clean_float(float(np.mean(values))),
        "std_y": clean_float(float(np.std(values))) if len(values) > 1 else 0.0,
        "best_y": clean_float(best["y"]),
        "best_x": clean_float(best["x"]) if isinstance(best["x"], float) else best["x"],
        "worst_y": clean_float(worst["y"]),
        "worst_x": clean_float(worst["x"]) if isinstance(worst["x"], float) else worst["x"],
    }


def plot_scenario_curves(args: argparse.Namespace) -> dict:
    specs = load_metric_specs(args.spec)
    spec_map = metric_spec_by_name(specs)
    if args.y not in spec_map:
        raise ValueError(f"y metric {args.y!r} was not found in metric spec.")
    rows = read_csv_records(args.metrics)
    if not rows:
        raise ValueError("metrics CSV has no data rows.")
    fieldnames = set(rows[0].keys())
    for required in ("algorithm", args.x, args.y):
        if required not in fieldnames:
            raise ValueError(f"metrics CSV is missing required column {required!r}.")

    entries: list[dict] = []
    numeric_flags: list[bool] = []
    for row_idx, row in enumerate(rows):
        algorithm = (row.get("algorithm") or "").strip()
        if not algorithm:
            continue
        scenario = (row.get("scenario") or "").strip() or None
        if args.scenario and scenario != args.scenario:
            continue
        raw_x = (row.get(args.x) or "").strip()
        x_numeric = parse_x_numeric(raw_x)
        y = parse_optional_float(row.get(args.y))
        if raw_x == "" or y is None:
            continue
        numeric_flags.append(x_numeric is not None)
        entries.append(
            {
                "algorithm": algorithm,
                "scenario": scenario,
                "raw_x": raw_x,
                "x_numeric": x_numeric,
                "y": float(y),
                "row_index": row_idx,
            }
        )
    if not entries:
        raise ValueError("No rows have usable algorithm, x, and y values after filtering.")

    x_is_numeric = all(numeric_flags)
    if x_is_numeric:
        x_order: list[float | str] = sorted({float(entry["x_numeric"]) for entry in entries})
        x_position = {value: float(value) for value in x_order}
        x_labels = {value: f"{value:g}" for value in x_order}
    else:
        if args.x_order:
            requested = [item.strip() for item in args.x_order.split(",") if item.strip()]
            missing = sorted({entry["raw_x"] for entry in entries if entry["raw_x"] not in requested})
            categories = requested + missing
        else:
            categories = sorted({entry["raw_x"] for entry in entries})
        x_order = categories
        x_position = {value: float(idx) for idx, value in enumerate(categories)}
        x_labels = {value: value for value in categories}

    grouped: dict[tuple[str, float | str], list[float]] = {}
    scenarios_by_group: dict[tuple[str, float | str], set[str]] = {}
    for entry in entries:
        x_key: float | str = float(entry["x_numeric"]) if x_is_numeric else entry["raw_x"]
        key = (entry["algorithm"], x_key)
        grouped.setdefault(key, []).append(entry["y"])
        if entry["scenario"]:
            scenarios_by_group.setdefault(key, set()).add(entry["scenario"])

    algorithms = sorted({entry["algorithm"] for entry in entries})
    series: list[dict] = []
    for algorithm in algorithms:
        points: list[dict] = []
        for x_key in x_order:
            key = (algorithm, x_key)
            values = grouped.get(key)
            if not values:
                continue
            y = aggregate_values(values, args.aggregate)
            points.append(
                {
                    "x": clean_float(float(x_key)) if x_is_numeric else str(x_key),
                    "x_label": x_labels[x_key],
                    "x_plot": x_position[x_key],
                    "y": clean_float(y),
                    "n": len(values),
                    "scenarios": sorted(scenarios_by_group.get(key, set())),
                }
            )
        if points:
            summary = summarize_series_points(points, spec_map[args.y]["direction"])
            series.append({"algorithm": algorithm, "points": points, **summary})
    if not series:
        raise ValueError("No algorithm series could be built from the selected x/y columns.")

    y_spec = spec_map[args.y]
    plt, _, _, _ = require_matplotlib()
    fig, ax = plt.subplots(figsize=(max(7.2, 0.55 * len(x_order)), 5.0))
    for item in series:
        xs = [point["x_plot"] for point in item["points"]]
        ys = [point["y"] for point in item["points"]]
        ax.plot(xs, ys, marker="o", linewidth=1.8, markersize=5, label=item["algorithm"])
        for point in item["points"]:
            if point["n"] > 1:
                ax.annotate(f"n={point['n']}", (point["x_plot"], point["y"]), xytext=(4, 5), textcoords="offset points", fontsize=7)

    if not x_is_numeric:
        ax.set_xticks([x_position[value] for value in x_order])
        ax.set_xticklabels([x_labels[value] for value in x_order], rotation=30, ha="right")
    ax.set_xlabel(args.x)
    ax.set_ylabel(f"{args.y} ({y_spec['direction']} is better)")
    title = f"Scenario Curve: {args.y} vs {args.x}"
    if args.scenario:
        title += f" [{args.scenario}]"
    ax.set_title(title)
    if y_spec.get("acceptable_min") is not None:
        ax.axhline(float(y_spec["acceptable_min"]), color="#2ca25f", linestyle="--", linewidth=1, label="acceptable_min")
    if y_spec.get("acceptable_max") is not None:
        ax.axhline(float(y_spec["acceptable_max"]), color="#d73027", linestyle="--", linewidth=1, label="acceptable_max")
    ax.grid(True, linestyle="--", alpha=0.35)
    ax.legend(fontsize=8)

    output_path = Path(args.output).expanduser()
    png_path = save_plot(fig, output_path, args.dpi)
    json_path = output_path.with_suffix(".json")
    summary = {
        "x": args.x,
        "y": args.y,
        "y_direction": y_spec["direction"],
        "scenario_filter": args.scenario,
        "x_is_numeric": x_is_numeric,
        "x_order": [clean_float(float(value)) if x_is_numeric else value for value in x_order],
        "aggregate": args.aggregate,
        "series": [
            {
                "algorithm": item["algorithm"],
                "valid_count": item["valid_count"],
                "mean_y": item["mean_y"],
                "std_y": item["std_y"],
                "best_y": item["best_y"],
                "best_x": item["best_x"],
                "worst_y": item["worst_y"],
                "worst_x": item["worst_x"],
                "points": [
                    {
                        "x": point["x"],
                        "x_label": point["x_label"],
                        "y": point["y"],
                        "n": point["n"],
                        "scenarios": point["scenarios"],
                    }
                    for point in item["points"]
                ],
            }
            for item in series
        ],
        "files": {"png": png_path, "json": str(json_path)},
    }
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def parse_metric_list(text: str | None, specs: list[dict]) -> list[dict]:
    if not text:
        return specs
    spec_map = metric_spec_by_name(specs)
    names = [item.strip() for item in text.split(",") if item.strip()]
    if len(names) < 3:
        raise ValueError("Radar charts need at least three metrics.")
    missing = [name for name in names if name not in spec_map]
    if missing:
        raise ValueError(f"Selected metrics not found in metric spec: {', '.join(missing)}")
    return [spec_map[name] for name in names]


def radar_axis_label(spec: dict) -> str:
    display = str(spec.get("display_name") or spec["metric"])
    return display if display.isascii() else spec["metric"]


def radar_candidate_rows(candidates: list[dict], specs: list[dict]) -> list[dict]:
    per_metric_scores = {spec["metric"]: normalized_metric_scores(candidates, spec) for spec in specs}
    total_weight = sum(max(0.0, spec["weight"]) for spec in specs)
    rows: list[dict] = []
    for candidate in candidates:
        scores: dict[str, float | None] = {}
        raw_values: dict[str, float | None] = {}
        missing: list[str] = []
        weighted = 0.0
        valid_weight = 0.0
        for spec in specs:
            metric = spec["metric"]
            score = per_metric_scores[metric][candidate["candidate_id"]]
            value = candidate["values"].get(metric)
            raw_values[metric] = clean_float(value)
            scores[metric] = clean_float(score)
            if score is None:
                missing.append(metric)
                continue
            weight = max(0.0, spec["weight"])
            weighted += float(score) * weight
            valid_weight += weight
        relative_score = clean_float(weighted / valid_weight) if valid_weight > 0 else None
        evidence_completeness = clean_float(valid_weight / total_weight) if total_weight > 0 else None
        selection_score = (
            clean_float(relative_score * evidence_completeness)
            if relative_score is not None and evidence_completeness is not None
            else None
        )
        rows.append(
            {
                "algorithm": candidate["algorithm"],
                "candidate_id": candidate["candidate_id"],
                "scenario": candidate["scenario"],
                "raw_values": raw_values,
                "normalized_scores": scores,
                "missing_metrics": missing,
                "relative_score": relative_score,
                "evidence_completeness": evidence_completeness,
                "selection_score": selection_score,
            }
        )
    rows.sort(key=lambda item: -1.0 if item["selection_score"] is None else item["selection_score"], reverse=True)
    return rows


def plot_radar(args: argparse.Namespace) -> dict:
    specs = load_metric_specs(args.spec)
    selected_specs = parse_metric_list(args.include_metrics, specs)
    if len(selected_specs) < 3:
        raise ValueError("Radar charts need at least three metrics.")
    candidates = load_compare_candidates(args.metrics, selected_specs)
    if args.scenario:
        candidates = [candidate for candidate in candidates if candidate["scenario"] == args.scenario]
    if not candidates:
        raise ValueError("No candidates remain after applying filters.")

    rows = radar_candidate_rows(candidates, selected_specs)
    max_candidates = args.max_candidates
    if max_candidates < 0:
        raise ValueError("--max-candidates must be zero or positive.")
    plotted_rows = rows if max_candidates == 0 else rows[:max_candidates]
    omitted_rows = [] if max_candidates == 0 else rows[max_candidates:]
    if not plotted_rows:
        raise ValueError("No candidates available for radar plotting.")

    metric_ids = [spec["metric"] for spec in selected_specs]
    labels = [radar_axis_label(spec) for spec in selected_specs]
    angles = np.linspace(0, 2.0 * math.pi, len(metric_ids), endpoint=False)
    closed_angles = np.concatenate([angles, angles[:1]])

    plt, _, _, _ = require_matplotlib()
    fig, ax = plt.subplots(figsize=(7.2, 6.2), subplot_kw={"projection": "polar"})
    for row in plotted_rows:
        values = [row["normalized_scores"].get(metric) for metric in metric_ids]
        plot_values = [0.0 if value is None else float(value) for value in values]
        closed_values = plot_values + plot_values[:1]
        label = candidate_label(row)
        if row.get("evidence_completeness") is not None and row["evidence_completeness"] < 1:
            label += f" (comp {row['evidence_completeness']:.2f})"
        ax.plot(closed_angles, closed_values, linewidth=1.8, marker="o", markersize=3.5, label=label)
        ax.fill(closed_angles, closed_values, alpha=0.08)

    ax.set_xticks(angles)
    ax.set_xticklabels(labels, fontsize=8)
    ax.set_ylim(0, 1.0)
    ax.set_yticks([0.25, 0.5, 0.75, 1.0])
    ax.set_yticklabels(["0.25", "0.50", "0.75", "1.00"], fontsize=8)
    ax.set_title("Radar: normalized metric scores", pad=18)
    ax.grid(True, linestyle="--", alpha=0.35)
    ax.legend(loc="upper left", bbox_to_anchor=(1.05, 1.05), fontsize=8)

    output_path = Path(args.output).expanduser()
    png_path = save_plot(fig, output_path, args.dpi)
    json_path = output_path.with_suffix(".json")
    summary = {
        "normalization": "direction-aware min-max normalization within the filtered metrics table; 1.0 is best within this table.",
        "critical_rule_note": "Radar scores are relative visualization scores and must not override engineering critical=true one-vote veto results.",
        "scenario": args.scenario,
        "plotted_count": len(plotted_rows),
        "omitted_count": len(omitted_rows),
        "metrics": [
            {
                "metric": spec["metric"],
                "display_name": spec["display_name"],
                "direction": spec["direction"],
                "weight": clean_float(spec["weight"]),
                "critical": spec["critical"],
                "category": spec["category"],
            }
            for spec in selected_specs
        ],
        "candidates": plotted_rows,
        "omitted_candidates": [
            {
                "algorithm": row["algorithm"],
                "candidate_id": row["candidate_id"],
                "scenario": row["scenario"],
                "relative_score": row["relative_score"],
                "evidence_completeness": row["evidence_completeness"],
                "selection_score": row["selection_score"],
            }
            for row in omitted_rows
        ],
        "files": {"png": png_path, "json": str(json_path)},
    }
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute lightweight underwater beamforming metrics.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    spectrum = subparsers.add_parser("spectrum", help="Evaluate 1D or reduced 2D spatial spectrum metrics.")
    spectrum.add_argument("--power", required=True, help="Spectrum data path, .npy or .csv. Last axis must be bearing/angle.")
    spectrum.add_argument("--angles", help="Angle path or comma-separated angle list. Defaults to sample indices.")
    spectrum.add_argument("--scale", choices=["db", "power", "amplitude"], default="db")
    spectrum.add_argument("--reduce", choices=["max", "mean", "sum"], default="max", help="Reduction for 2D data before 1D metrics.")
    spectrum.add_argument("--mainlobe-exclusion-deg", type=float, default=5.0)
    spectrum.add_argument("--false-peak-threshold-db", type=float, default=12.0)
    spectrum.add_argument("--truth-deg", help="Comma-separated truth bearings for DOA error metrics.")
    spectrum.add_argument("--top-k", type=int, default=5)
    spectrum.set_defaults(func=spectrum_metrics)

    doa = subparsers.add_parser("doa", help="Evaluate DOA estimates against optional truth bearings.")
    doa.add_argument("--estimates", required=True, help="CSV/NPY table. Rows=frames/trials, columns=detections; blanks/NaN mean missing.")
    doa.add_argument("--truth", help="CSV/NPY truth table with the same row count as estimates.")
    doa.add_argument("--gate-deg", type=float, default=5.0, help="Maximum angular error for a truth-estimate match.")
    doa.add_argument("--max-frame-output", type=int, default=20, help="Number of frame-level details to include in JSON preview.")
    doa.set_defaults(func=doa_metrics)

    fb = subparsers.add_parser("freq-bearing", help="Evaluate a P(f, theta) frequency-bearing matrix.")
    fb.add_argument("--matrix", required=True, help="CSV/NPY matrix with rows=frequency and columns=bearing.")
    fb.add_argument("--freqs", help="Frequency axis path or comma-separated values. Defaults to row indices.")
    fb.add_argument("--angles", help="Bearing axis path or comma-separated values. Defaults to column indices.")
    fb.add_argument("--scale", choices=["db", "power", "amplitude"], default="db")
    fb.add_argument("--freq-band", help="Inclusive frequency band formatted as low:high or low,high.")
    fb.add_argument("--fuse", choices=["power-sum", "power-mean", "db-max", "db-mean"], default="power-sum")
    fb.add_argument("--truth-deg", help="Comma-separated truth bearings for error metrics.")
    fb.add_argument("--mainlobe-exclusion-deg", type=float, default=5.0)
    fb.add_argument("--false-peak-threshold-db", type=float, default=12.0)
    fb.add_argument("--top-k", type=int, default=5)
    fb.add_argument("--max-frequency-output", type=int, default=20)
    fb.set_defaults(func=freq_bearing_metrics)

    btr = subparsers.add_parser("btr", help="Evaluate a P(t, theta) bearing-time record matrix.")
    btr.add_argument("--matrix", required=True, help="CSV/NPY matrix with rows=time/frame and columns=bearing.")
    btr.add_argument("--times", help="Time axis path or comma-separated values. Defaults to row indices.")
    btr.add_argument("--angles", help="Bearing axis path or comma-separated values. Defaults to column indices.")
    btr.add_argument("--scale", choices=["db", "power", "amplitude"], default="db")
    btr.add_argument("--truth-track", help="CSV/NPY truth bearing track. Rows must match BTR frames; first finite value is used.")
    btr.add_argument("--gate-deg", type=float, default=5.0)
    btr.add_argument("--top-k", type=int, default=3)
    btr.add_argument("--relative-threshold-db", type=float, default=12.0)
    btr.add_argument("--max-jump-deg", type=float, default=5.0)
    btr.add_argument("--background-exclusion-deg", type=float, default=5.0)
    btr.add_argument("--secondary-peak-threshold-db", type=float, default=6.0)
    btr.add_argument("--max-frame-output", type=int, default=20)
    btr.set_defaults(func=btr_metrics)

    signal = subparsers.add_parser("signal", help="Evaluate a beamformed time-domain output signal.")
    signal.add_argument("--signal", required=True, help="CSV/NPY signal. 1D, or 2D with rows=samples and columns=outputs.")
    signal.add_argument("--fs", type=float, required=True, help="Sampling rate in Hz.")
    signal.add_argument("--column", type=int, default=0)
    signal.add_argument("--target-segment", help="Target segment in seconds, formatted as start:end.")
    signal.add_argument("--noise-segment", help="Noise segment in seconds, formatted as start:end.")
    signal.add_argument("--interference-segment", help="Interference segment in seconds, formatted as start:end.")
    signal.add_argument("--baseline", help="Baseline/input signal with the same shape convention and sample count.")
    signal.add_argument("--reference", help="Clean/reference signal for waveform distortion metrics.")
    signal.add_argument("--detrend", choices=["none", "mean"], default="mean")
    signal.add_argument("--eps", type=float, default=1e-12)
    signal.set_defaults(func=signal_metrics)

    out = subparsers.add_parser("spectrum-output", help="Evaluate a beam output spectrum or PSD.")
    out.add_argument("--spectrum", required=True, help="CSV/NPY spectrum. 1D, or 2D with rows=frequency and columns=outputs.")
    out.add_argument("--freqs", required=True, help="Frequency axis path or comma-separated values.")
    out.add_argument("--column", type=int, default=0)
    out.add_argument("--scale", choices=["db", "power", "amplitude"], default="db")
    out.add_argument("--target-band", help="Target frequency band formatted as low:high.")
    out.add_argument("--noise-band", help="Noise/reference frequency band formatted as low:high.")
    out.add_argument("--interference-band", help="Interference frequency band formatted as low:high.")
    out.add_argument("--baseline", help="Baseline spectrum with matching frequency bins.")
    out.add_argument("--floor-percentile", type=float, default=50.0)
    out.add_argument("--eps", type=float, default=1e-12)
    out.set_defaults(func=spectrum_output_metrics)

    tf = subparsers.add_parser("time-frequency", help="Evaluate a P(t, f) time-frequency matrix.")
    tf.add_argument("--matrix", required=True, help="CSV/NPY matrix with rows=time frames and columns=frequency bins.")
    tf.add_argument("--times", help="Time axis path or comma-separated values. Defaults to row indices.")
    tf.add_argument("--freqs", required=True, help="Frequency axis path or comma-separated values.")
    tf.add_argument("--scale", choices=["db", "power", "amplitude"], default="db")
    tf.add_argument("--target-band", required=True, help="Target frequency band formatted as low:high.")
    tf.add_argument("--noise-band", help="Noise/reference frequency band formatted as low:high.")
    tf.add_argument("--interference-band", help="Interference frequency band formatted as low:high.")
    tf.add_argument("--baseline", help="Baseline P(t, f) matrix with matching shape.")
    tf.add_argument("--presence-threshold-db", type=float, default=6.0)
    tf.add_argument("--floor-percentile", type=float, default=50.0)
    tf.add_argument("--max-frame-output", type=int, default=20)
    tf.add_argument("--eps", type=float, default=1e-12)
    tf.set_defaults(func=time_frequency_metrics)

    compare = subparsers.add_parser("compare", help="Compare algorithms from a metrics table and metric specification.")
    compare.add_argument("--metrics", required=True, help="CSV table with algorithm column and metric value columns.")
    compare.add_argument("--spec", required=True, help="CSV metric spec with metric,direction,weight,threshold,critical fields.")
    compare.add_argument("--mode", choices=["paper", "engineering", "dual"], default="dual")
    compare.set_defaults(func=compare_metrics)

    plot_compare_parser = subparsers.add_parser("plot-compare", help="Generate plots from a compare JSON result.")
    plot_compare_parser.add_argument("--compare-json", required=True, help="JSON file produced by the compare command.")
    plot_compare_parser.add_argument("--output-dir", required=True, help="Directory for generated PNG files.")
    plot_compare_parser.add_argument("--dpi", type=int, default=160)
    plot_compare_parser.add_argument("--skip-metric-plots", action="store_true")
    plot_compare_parser.set_defaults(func=plot_compare)

    pareto = subparsers.add_parser("plot-pareto", help="Generate a Pareto tradeoff plot from metrics and metric spec CSV files.")
    pareto.add_argument("--metrics", required=True, help="CSV table with algorithm column and metric value columns.")
    pareto.add_argument("--spec", required=True, help="CSV metric spec with metric,direction,weight,threshold,critical fields.")
    pareto.add_argument("--x", required=True, help="Metric name for x axis.")
    pareto.add_argument("--y", required=True, help="Metric name for y axis.")
    pareto.add_argument("--output", required=True, help="Output PNG path. A same-name JSON summary is also written.")
    pareto.add_argument("--scenario", help="Optional scenario filter matching the scenario column.")
    pareto.add_argument("--label-points", action=argparse.BooleanOptionalAction, default=True)
    pareto.add_argument("--dpi", type=int, default=160)
    pareto.set_defaults(func=plot_pareto)

    scenario_curves = subparsers.add_parser("plot-scenario-curves", help="Plot one metric versus a scenario variable for each algorithm.")
    scenario_curves.add_argument("--metrics", required=True, help="CSV table with algorithm, scenario-variable, and metric columns.")
    scenario_curves.add_argument("--spec", required=True, help="CSV metric spec with metric,direction,weight,threshold,critical fields.")
    scenario_curves.add_argument("--x", required=True, help="Scenario variable column, such as snr_db, snapshots, target_sep_deg, or sea_state.")
    scenario_curves.add_argument("--y", required=True, help="Metric column to plot on the y axis.")
    scenario_curves.add_argument("--output", required=True, help="Output PNG path. A same-name JSON summary is also written.")
    scenario_curves.add_argument("--scenario", help="Optional scenario filter matching the scenario column.")
    scenario_curves.add_argument("--x-order", help="Comma-separated category order for nonnumeric x values.")
    scenario_curves.add_argument("--aggregate", choices=["mean", "median", "min", "max"], default="mean")
    scenario_curves.add_argument("--dpi", type=int, default=160)
    scenario_curves.set_defaults(func=plot_scenario_curves)

    radar = subparsers.add_parser("plot-radar", help="Generate a normalized multi-metric radar chart from metrics and metric spec CSV files.")
    radar.add_argument("--metrics", required=True, help="CSV table with algorithm column and metric value columns.")
    radar.add_argument("--spec", required=True, help="CSV metric spec with metric,direction,weight,threshold,critical fields.")
    radar.add_argument("--output", required=True, help="Output PNG path. A same-name JSON summary is also written.")
    radar.add_argument("--include-metrics", help="Comma-separated metric list. Defaults to all metrics in the spec.")
    radar.add_argument("--scenario", help="Optional scenario filter matching the scenario column.")
    radar.add_argument("--max-candidates", type=int, default=8, help="Plot top candidates by weighted normalized score adjusted by evidence completeness; use 0 for no limit.")
    radar.add_argument("--dpi", type=int, default=160)
    radar.set_defaults(func=plot_radar)

    args = parser.parse_args()
    print(json.dumps(args.func(args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
