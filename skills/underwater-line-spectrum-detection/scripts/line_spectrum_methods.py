#!/usr/bin/env python3
"""Baseline methods for underwater acoustic line-spectrum detection.

This script intentionally implements stable, interpretable baselines rather
than paper-specific algorithms. Inputs are simple CSV/NPY files and outputs are
JSON plus optional CSV artifacts, so the methods can be chained with the
metrics script or adapted to project-specific formats.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np


EPS = 1e-12


def read_vector(path: str, column: Optional[str] = None) -> np.ndarray:
    p = Path(path)
    if p.suffix.lower() == ".npy":
        values = np.load(p, allow_pickle=False)
        if values.ndim == 2 and values.shape[1] == 1:
            values = values[:, 0]
        if values.ndim != 1 or not np.isrealobj(values) or values.dtype.kind not in "fiu":
            raise ValueError("NPY vector input must be real 1D or [sample,1]; select a beam explicitly, never flatten multiple columns")
        return np.asarray(values, dtype=float)
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
        if has_header:
            reader = csv.DictReader(f)
            rows = list(reader)
            if not rows:
                return np.asarray([], dtype=float)
            col = column or first_numeric_column(rows[0])
            return np.asarray([float(r[col]) for r in rows if str(r.get(col, "")).strip()], dtype=float)
        reader = csv.reader(f)
        vals: List[float] = []
        for row in reader:
            clean = [x.strip() for x in row if x.strip()]
            if clean:
                vals.append(float(clean[0]))
        return np.asarray(vals, dtype=float)


def first_numeric_column(row: Dict[str, Any]) -> str:
    for key, value in row.items():
        try:
            float(value)
            return key
        except (TypeError, ValueError):
            continue
    return next(iter(row.keys()))


def read_matrix(path: str) -> np.ndarray:
    p = Path(path)
    if p.suffix.lower() == ".npy":
        return np.asarray(np.load(p), dtype=float)
    return np.loadtxt(p, delimiter=",")


def read_records(path: str) -> List[Dict[str, Any]]:
    with Path(path).open("r", newline="") as f:
        return [dict(row) for row in csv.DictReader(f)]


def write_records(path: str, rows: Sequence[Dict[str, Any]], fieldnames: Optional[Sequence[str]] = None) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        keys: List[str] = []
        for row in rows:
            for key in row.keys():
                if key not in keys:
                    keys.append(key)
        fieldnames = keys
    with p.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(fieldnames))
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


def write_vector_csv(path: str, column: str, values: Sequence[float]) -> None:
    write_records(path, [{column: float(v)} for v in values], [column])


def write_signal_csv(path: str, time_s: np.ndarray, signal: np.ndarray) -> None:
    write_records(
        path,
        [{"time_s": float(t), "amplitude": float(x)} for t, x in zip(time_s, signal)],
        ["time_s", "amplitude"],
    )


def jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [jsonable(v) for v in value]
    if isinstance(value, tuple):
        return [jsonable(v) for v in value]
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def emit(result: Dict[str, Any], output: Optional[str]) -> None:
    text = json.dumps(jsonable(result), ensure_ascii=False, indent=2)
    if output:
        Path(output).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)


def arg_settings(args: argparse.Namespace) -> Dict[str, Any]:
    return {k: v for k, v in vars(args).items() if k != "func"}


def parse_range(text: Optional[str]) -> Optional[Tuple[float, float]]:
    if not text:
        return None
    parts = text.replace(":", ",").split(",")
    if len(parts) != 2:
        raise ValueError(f"Expected lo:hi range, got {text!r}")
    lo, hi = float(parts[0]), float(parts[1])
    return (lo, hi) if lo <= hi else (hi, lo)


def parse_float_list(text: Optional[str]) -> List[float]:
    if not text:
        return []
    return [float(x.strip()) for x in text.split(",") if x.strip()]


def to_db(values: np.ndarray, scale: str) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    if scale == "db":
        return arr
    return 10.0 * np.log10(np.maximum(arr, EPS))


def to_linear_power(values: np.ndarray, scale: str) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    if scale == "linear":
        return np.maximum(arr, EPS)
    return np.power(10.0, arr / 10.0)


def window_values(name: str, n: int) -> np.ndarray:
    key = name.lower()
    if key in {"hann", "hanning"}:
        return np.hanning(n)
    if key == "hamming":
        return np.hamming(n)
    if key == "blackman":
        return np.blackman(n)
    if key == "rect":
        return np.ones(n)
    if key == "flattop":
        # Five-term flat-top window coefficients commonly used for amplitude accuracy.
        idx = np.arange(n)
        x = 2.0 * np.pi * idx / max(n - 1, 1)
        return (
            0.21557895
            - 0.41663158 * np.cos(x)
            + 0.277263158 * np.cos(2 * x)
            - 0.083578947 * np.cos(3 * x)
            + 0.006947368 * np.cos(4 * x)
        )
    raise ValueError(f"Unsupported window {name!r}")


def detrend_frame(frame: np.ndarray, mode: str) -> np.ndarray:
    if mode == "none":
        return frame
    if mode == "mean":
        return frame - np.mean(frame)
    if mode == "linear":
        x = np.arange(frame.size, dtype=float)
        coeff = np.polyfit(x, frame, 1)
        return frame - np.polyval(coeff, x)
    raise ValueError(f"Unsupported detrend mode {mode!r}")


def welch_psd(
    signal: np.ndarray,
    fs: float,
    nperseg: int,
    noverlap: int,
    nfft: Optional[int],
    window: str,
    detrend: str,
) -> Tuple[np.ndarray, np.ndarray, Dict[str, Any]]:
    values = np.asarray(signal)
    if values.ndim == 2 and values.shape[1] == 1:
        values = values[:, 0]
    if values.ndim != 1 or not np.isrealobj(values) or values.dtype.kind not in "fiu":
        raise ValueError("Welch requires one explicit real waveform; multiple beams must not be flattened")
    y = np.asarray(values, dtype=float)
    if y.size < nperseg:
        raise ValueError(f"signal length {y.size} is shorter than nperseg {nperseg}")
    if noverlap >= nperseg:
        raise ValueError("noverlap must be smaller than nperseg")
    nfft_val = int(nfft or next_pow2(nperseg))
    if nfft_val < nperseg:
        raise ValueError("nfft must be at least nperseg")
    step = nperseg - noverlap
    starts = list(range(0, y.size - nperseg + 1, step))
    if not starts:
        starts = [0]
    win = window_values(window, nperseg)
    win_power = float(np.sum(win * win))
    acc = None
    for start in starts:
        frame = detrend_frame(y[start : start + nperseg], detrend)
        spec = np.fft.rfft(frame * win, n=nfft_val)
        psd = (np.abs(spec) ** 2) / max(fs * win_power, EPS)
        if nfft_val % 2 == 0:
            if psd.size > 2:
                psd[1:-1] *= 2.0
        else:
            if psd.size > 1:
                psd[1:] *= 2.0
        acc = psd if acc is None else acc + psd
    avg = acc / max(len(starts), 1)
    freqs = np.fft.rfftfreq(nfft_val, d=1.0 / fs)
    meta = {
        "fs": fs,
        "nperseg": nperseg,
        "noverlap": noverlap,
        "nfft": nfft_val,
        "window": window,
        "detrend": detrend,
        "segment_count": len(starts),
        "df_hz": float(freqs[1] - freqs[0]) if freqs.size > 1 else None,
    }
    return freqs, avg, meta


def next_pow2(n: int) -> int:
    return 1 << (int(n) - 1).bit_length()


def band_mask(freqs: np.ndarray, band: Optional[str]) -> np.ndarray:
    rng = parse_range(band)
    if rng is None:
        return np.ones(freqs.shape, dtype=bool)
    lo, hi = rng
    return (freqs >= lo) & (freqs <= hi)


def local_background(
    levels_db: np.ndarray,
    idx: int,
    guard_bins: int,
    train_bins: int,
    estimator: str,
    percentile: float,
) -> float:
    n = levels_db.size
    left0 = max(0, idx - guard_bins - train_bins)
    left1 = max(0, idx - guard_bins)
    right0 = min(n, idx + guard_bins + 1)
    right1 = min(n, idx + guard_bins + train_bins + 1)
    vals = np.concatenate([levels_db[left0:left1], levels_db[right0:right1]])
    if vals.size == 0:
        vals = np.delete(levels_db, idx) if n > 1 else levels_db
    if vals.size == 0:
        return float(levels_db[idx])
    if estimator == "median":
        return float(np.median(vals))
    if estimator == "mean":
        return float(10.0 * np.log10(np.mean(np.power(10.0, vals / 10.0)) + EPS))
    if estimator == "percentile":
        return float(np.percentile(vals, percentile))
    raise ValueError(f"Unsupported background estimator {estimator!r}")


def is_local_max(levels: np.ndarray, idx: int) -> bool:
    if idx <= 0 or idx >= levels.size - 1:
        return False
    return levels[idx] >= levels[idx - 1] and levels[idx] >= levels[idx + 1]


def detect_adaptive_peaks(
    freqs: np.ndarray,
    levels: np.ndarray,
    scale: str,
    threshold_db: float,
    guard_bins: int,
    train_bins: int,
    min_distance_bins: int,
    max_peaks: Optional[int],
    band: Optional[str],
    background: str,
    percentile: float,
    local_max_only: bool = True,
) -> List[Dict[str, Any]]:
    levels_db = to_db(levels, scale)
    mask = band_mask(freqs, band)
    sub_idx = np.flatnonzero(mask)
    if sub_idx.size == 0:
        return []
    candidates: List[Dict[str, Any]] = []
    sub_levels_db = levels_db[sub_idx]
    sub_freqs = freqs[sub_idx]
    for j in range(sub_idx.size):
        if local_max_only and not is_local_max(sub_levels_db, j):
            continue
        noise = local_background(sub_levels_db, j, guard_bins, train_bins, background, percentile)
        score = float(sub_levels_db[j] - noise)
        if score >= threshold_db:
            candidates.append(
                {
                    "freq_hz": float(sub_freqs[j]),
                    "level_db": float(sub_levels_db[j]),
                    "noise_floor_db": noise,
                    "line_snr_db": score,
                    "bin": int(sub_idx[j]),
                }
            )
    return suppress_close_peaks(candidates, min_distance_bins, max_peaks)


def suppress_close_peaks(
    candidates: Sequence[Dict[str, Any]],
    min_distance_bins: int,
    max_peaks: Optional[int],
) -> List[Dict[str, Any]]:
    ranked = sorted(candidates, key=lambda x: float(x.get("line_snr_db", x.get("score", 0.0))), reverse=True)
    selected: List[Dict[str, Any]] = []
    used_bins: List[int] = []
    for cand in ranked:
        b = int(cand.get("bin", -10**9))
        if b != -10**9 and any(abs(b - ub) < min_distance_bins for ub in used_bins):
            continue
        selected.append(dict(cand))
        if b != -10**9:
            used_bins.append(b)
        if max_peaks is not None and len(selected) >= max_peaks:
            break
    selected.sort(key=lambda x: (float(x.get("time_s", 0.0)), float(x["freq_hz"])))
    return selected


def cfar_noise_floor(
    powers: np.ndarray,
    idx: int,
    guard_bins: int,
    train_bins: int,
    method: str,
    os_rank: float,
) -> float:
    n = powers.size
    left0 = max(0, idx - guard_bins - train_bins)
    left1 = max(0, idx - guard_bins)
    right0 = min(n, idx + guard_bins + 1)
    right1 = min(n, idx + guard_bins + train_bins + 1)
    vals = np.concatenate([powers[left0:left1], powers[right0:right1]])
    vals = vals[np.isfinite(vals)]
    if vals.size == 0:
        vals = np.delete(powers, idx) if n > 1 else powers
    vals = np.maximum(vals, EPS)
    if method == "ca":
        return float(np.mean(vals))
    if method == "os":
        q = min(max(os_rank, 0.0), 100.0)
        return float(np.percentile(vals, q))
    if method == "go":
        left = powers[left0:left1]
        right = powers[right0:right1]
        left_mean = float(np.mean(left)) if left.size else EPS
        right_mean = float(np.mean(right)) if right.size else EPS
        return max(left_mean, right_mean)
    if method == "so":
        left = powers[left0:left1]
        right = powers[right0:right1]
        left_mean = float(np.mean(left)) if left.size else EPS
        right_mean = float(np.mean(right)) if right.size else EPS
        return min(left_mean, right_mean)
    raise ValueError(f"Unsupported CFAR method {method!r}")


def detect_cfar(
    freqs: np.ndarray,
    levels: np.ndarray,
    scale: str,
    threshold_db: float,
    guard_bins: int,
    train_bins: int,
    min_distance_bins: int,
    max_peaks: Optional[int],
    band: Optional[str],
    method: str,
    os_rank: float,
    local_max_only: bool,
) -> List[Dict[str, Any]]:
    powers = to_linear_power(levels, scale)
    levels_db = to_db(levels, scale)
    mask = band_mask(freqs, band)
    sub_idx = np.flatnonzero(mask)
    if sub_idx.size == 0:
        return []
    sub_powers = powers[sub_idx]
    sub_levels_db = levels_db[sub_idx]
    sub_freqs = freqs[sub_idx]
    candidates: List[Dict[str, Any]] = []
    threshold_ratio = 10.0 ** (threshold_db / 10.0)
    for j in range(sub_idx.size):
        if local_max_only and not is_local_max(sub_levels_db, j):
            continue
        noise_power = cfar_noise_floor(sub_powers, j, guard_bins, train_bins, method, os_rank)
        threshold_power = noise_power * threshold_ratio
        if sub_powers[j] >= threshold_power:
            noise_db = 10.0 * math.log10(max(noise_power, EPS))
            candidates.append(
                {
                    "freq_hz": float(sub_freqs[j]),
                    "level_db": float(sub_levels_db[j]),
                    "noise_floor_db": noise_db,
                    "threshold_db": float(10.0 * math.log10(max(threshold_power, EPS))),
                    "line_snr_db": float(sub_levels_db[j] - noise_db),
                    "cfar_method": method,
                    "bin": int(sub_idx[j]),
                }
            )
    return suppress_close_peaks(candidates, min_distance_bins, max_peaks)


def cmd_psd_detect(args: argparse.Namespace) -> Dict[str, Any]:
    freqs = read_vector(args.freqs)
    levels = read_vector(args.spectrum)
    if freqs.size != levels.size:
        raise ValueError(f"freqs length {freqs.size} != spectrum length {levels.size}")
    detections = detect_adaptive_peaks(
        freqs,
        levels,
        args.scale,
        args.threshold_db,
        args.guard_bins,
        args.train_bins,
        args.min_distance_bins,
        args.max_peaks,
        args.band,
        args.background,
        args.percentile,
        not args.no_local_max,
    )
    if args.detections_csv:
        write_records(args.detections_csv, detections)
    return {
        "mode": "psd-detect",
        "settings": arg_settings(args),
        "detection_count": len(detections),
        "detections": detections,
    }


def cmd_psd_cfar(args: argparse.Namespace) -> Dict[str, Any]:
    freqs = read_vector(args.freqs)
    levels = read_vector(args.spectrum)
    if freqs.size != levels.size:
        raise ValueError(f"freqs length {freqs.size} != spectrum length {levels.size}")
    detections = detect_cfar(
        freqs,
        levels,
        args.scale,
        args.threshold_db,
        args.guard_bins,
        args.train_bins,
        args.min_distance_bins,
        args.max_peaks,
        args.band,
        args.cfar,
        args.os_rank,
        not args.no_local_max,
    )
    if args.detections_csv:
        write_records(args.detections_csv, detections)
    return {
        "mode": "psd-cfar",
        "settings": arg_settings(args),
        "detection_count": len(detections),
        "detections": detections,
    }


def cmd_welch_detect(args: argparse.Namespace) -> Dict[str, Any]:
    signal = read_vector(args.signal, column=args.signal_column)
    freqs, psd, meta = welch_psd(
        signal,
        args.fs,
        args.nperseg,
        args.noverlap,
        args.nfft,
        args.window,
        args.detrend,
    )
    if args.psd_csv:
        write_records(
            args.psd_csv,
            [{"freq_hz": float(f), "psd": float(p), "psd_db": float(10.0 * math.log10(max(p, EPS)))} for f, p in zip(freqs, psd)],
            ["freq_hz", "psd", "psd_db"],
        )
    if args.freqs_csv:
        write_vector_csv(args.freqs_csv, "freq_hz", freqs)
    if args.spectrum_csv:
        write_vector_csv(args.spectrum_csv, "level_db", 10.0 * np.log10(np.maximum(psd, EPS)))
    detections = detect_adaptive_peaks(
        freqs,
        psd,
        "linear",
        args.threshold_db,
        args.guard_bins,
        args.train_bins,
        args.min_distance_bins,
        args.max_peaks,
        args.band,
        args.background,
        args.percentile,
        not args.no_local_max,
    )
    if args.detections_csv:
        write_records(args.detections_csv, detections)
    return {
        "mode": "welch-detect",
        "settings": arg_settings(args),
        "welch": meta,
        "detection_count": len(detections),
        "detections": detections,
    }


def cmd_lofar_detect(args: argparse.Namespace) -> Dict[str, Any]:
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
    detections: List[Dict[str, Any]] = []
    for frame_idx, t in enumerate(times):
        peaks = detect_adaptive_peaks(
            freqs,
            matrix[frame_idx],
            args.scale,
            args.threshold_db,
            args.guard_bins,
            args.train_bins,
            args.min_distance_bins,
            args.max_peaks_per_frame,
            args.band,
            args.background,
            args.percentile,
            not args.no_local_max,
        )
        for p in peaks:
            row = dict(p)
            row["time_s"] = float(t)
            row["frame"] = int(frame_idx)
            detections.append(row)
    detections.sort(key=lambda r: (float(r["time_s"]), float(r["freq_hz"])))
    if args.detections_csv:
        write_records(args.detections_csv, detections)
    return {
        "mode": "lofar-detect",
        "settings": arg_settings(args),
        "frame_count": int(times.size),
        "frequency_bin_count": int(freqs.size),
        "detection_count": len(detections),
        "sample_detections": detections[: min(100, len(detections))],
    }


@dataclass
class Track:
    track_id: int
    points: List[Dict[str, Any]]
    missed_until_s: float

    @property
    def last(self) -> Dict[str, Any]:
        return self.points[-1]


def detection_score(row: Dict[str, Any]) -> float:
    for key in ("score", "line_snr_db", "level_db"):
        if str(row.get(key, "")).strip():
            try:
                return float(row[key])
            except (TypeError, ValueError):
                continue
    return 0.0


def read_detection_table(path: str) -> List[Dict[str, Any]]:
    rows = read_records(path)
    out: List[Dict[str, Any]] = []
    for row in rows:
        if not str(row.get("freq_hz", "")).strip():
            continue
        item = dict(row)
        item["freq_hz"] = float(row["freq_hz"])
        if str(row.get("time_s", "")).strip():
            item["time_s"] = float(row["time_s"])
        elif str(row.get("frame", "")).strip():
            item["time_s"] = float(row["frame"])
        else:
            raise ValueError("ridge-track requires time_s or frame in detections")
        for key in ("score", "line_snr_db", "level_db"):
            if str(row.get(key, "")).strip():
                item[key] = float(row[key])
        out.append(item)
    out.sort(key=lambda r: (float(r["time_s"]), -detection_score(r)))
    return out


def close_track(track: Track, min_points: int, min_duration_s: float) -> Optional[Dict[str, Any]]:
    pts = track.points
    if len(pts) < min_points:
        return None
    duration = float(pts[-1]["time_s"]) - float(pts[0]["time_s"])
    if duration < min_duration_s:
        return None
    freqs = np.asarray([float(p["freq_hz"]) for p in pts], dtype=float)
    scores = np.asarray([detection_score(p) for p in pts], dtype=float)
    return {
        "track_id": track.track_id,
        "point_count": len(pts),
        "start_time_s": float(pts[0]["time_s"]),
        "end_time_s": float(pts[-1]["time_s"]),
        "duration_s": duration,
        "start_freq_hz": float(freqs[0]),
        "end_freq_hz": float(freqs[-1]),
        "mean_freq_hz": float(np.mean(freqs)),
        "freq_span_hz": float(np.max(freqs) - np.min(freqs)),
        "mean_score": float(np.mean(scores)) if scores.size else None,
        "points": pts,
    }


def cmd_ridge_track(args: argparse.Namespace) -> Dict[str, Any]:
    detections = read_detection_table(args.detections)
    by_time: Dict[float, List[Dict[str, Any]]] = {}
    for det in detections:
        by_time.setdefault(float(det["time_s"]), []).append(det)
    times = sorted(by_time.keys())
    active: List[Track] = []
    closed: List[Dict[str, Any]] = []
    next_id = 1
    for t in times:
        frame = sorted(by_time[t], key=detection_score, reverse=True)
        used = set()
        assignments: List[Tuple[float, int, int]] = []
        for ti, track in enumerate(active):
            dt = max(t - float(track.last["time_s"]), 0.0)
            gate = args.gate_hz + args.max_drift_hz_per_s * dt
            for di, det in enumerate(frame):
                if di in used:
                    continue
                err = abs(float(det["freq_hz"]) - float(track.last["freq_hz"]))
                if err <= gate:
                    assignments.append((err, ti, di))
        assigned_tracks = set()
        for _, ti, di in sorted(assignments, key=lambda x: x[0]):
            if ti in assigned_tracks or di in used:
                continue
            active[ti].points.append(frame[di])
            active[ti].missed_until_s = t
            assigned_tracks.add(ti)
            used.add(di)

        still_active: List[Track] = []
        for ti, track in enumerate(active):
            if ti in assigned_tracks:
                still_active.append(track)
                continue
            gap = t - float(track.last["time_s"])
            if gap <= args.max_gap_s:
                still_active.append(track)
            else:
                summary = close_track(track, args.min_points, args.min_duration_s)
                if summary:
                    closed.append(summary)
        active = still_active

        for di, det in enumerate(frame):
            if di in used:
                continue
            active.append(Track(track_id=next_id, points=[det], missed_until_s=t))
            next_id += 1

    for track in active:
        summary = close_track(track, args.min_points, args.min_duration_s)
        if summary:
            closed.append(summary)
    closed.sort(key=lambda r: (-int(r["point_count"]), float(r["start_time_s"]), float(r["mean_freq_hz"])))
    if args.tracks_csv:
        summary_rows = [{k: v for k, v in row.items() if k != "points"} for row in closed]
        write_records(args.tracks_csv, summary_rows)
    if args.points_csv:
        point_rows: List[Dict[str, Any]] = []
        for tr in closed:
            for p in tr["points"]:
                row = dict(p)
                row["track_id"] = tr["track_id"]
                point_rows.append(row)
        write_records(args.points_csv, point_rows)
    return {
        "mode": "ridge-track",
        "settings": arg_settings(args),
        "input_detection_count": len(detections),
        "track_count": len(closed),
        "tracks": closed[: min(args.max_tracks_output, len(closed))],
    }


def read_peak_table(path: str) -> List[Dict[str, Any]]:
    rows = read_records(path)
    peaks: List[Dict[str, Any]] = []
    for row in rows:
        if not str(row.get("freq_hz", "")).strip():
            continue
        item = dict(row)
        item["freq_hz"] = float(row["freq_hz"])
        item["score"] = detection_score(item)
        peaks.append(item)
    peaks.sort(key=lambda r: float(r["freq_hz"]))
    return peaks


def harmonic_candidates_from_peaks(peaks: Sequence[Dict[str, Any]], f0_min: float, f0_max: float) -> List[float]:
    freqs = [float(p["freq_hz"]) for p in peaks]
    candidates: List[float] = []
    for i, f1 in enumerate(freqs):
        for f2 in freqs[i + 1 :]:
            diff = f2 - f1
            if f0_min <= diff <= f0_max:
                candidates.append(diff)
            for order in range(2, 8):
                cand = diff / order
                if f0_min <= cand <= f0_max:
                    candidates.append(cand)
    for f in freqs:
        for order in range(1, 8):
            cand = f / order
            if f0_min <= cand <= f0_max:
                candidates.append(cand)
    return sorted(set(round(c, 6) for c in candidates))


def score_harmonic_family(
    peaks: Sequence[Dict[str, Any]],
    f0: float,
    min_order: int,
    max_order: int,
    tolerance_hz: float,
    relative_tolerance: float,
    missing_penalty: float,
) -> Dict[str, Any]:
    matches: List[Dict[str, Any]] = []
    used = set()
    score = 0.0
    expected_count = 0
    max_freq = max(float(p["freq_hz"]) for p in peaks) if peaks else 0.0
    for order in range(min_order, max_order + 1):
        expected = order * f0
        if expected > max_freq + tolerance_hz:
            continue
        expected_count += 1
        tol = tolerance_hz + abs(expected) * relative_tolerance
        best_i = None
        best_err = None
        for i, peak in enumerate(peaks):
            if i in used:
                continue
            err = float(peak["freq_hz"]) - expected
            if abs(err) <= tol and (best_err is None or abs(err) < abs(best_err)):
                best_i = i
                best_err = err
        if best_i is None or best_err is None:
            score -= missing_penalty
            continue
        used.add(best_i)
        peak = peaks[best_i]
        peak_score = detection_score(peak)
        score += max(peak_score, 1.0) / math.sqrt(max(order, 1))
        matches.append(
            {
                "order": order,
                "expected_freq_hz": float(expected),
                "detected_freq_hz": float(peak["freq_hz"]),
                "error_hz": float(best_err),
                "score": float(peak_score),
            }
        )
    coverage = len(matches) / expected_count if expected_count else 0.0
    err = np.asarray([m["error_hz"] for m in matches], dtype=float)
    return {
        "f0_hz": float(f0),
        "score": float(score),
        "coverage": float(coverage),
        "matched_harmonics": len(matches),
        "expected_harmonics": expected_count,
        "rmse_hz": float(np.sqrt(np.mean(err * err))) if err.size else None,
        "matches": matches,
    }


def cmd_harmonic_assoc(args: argparse.Namespace) -> Dict[str, Any]:
    peaks = read_peak_table(args.peaks)
    if not peaks:
        raise ValueError("No peaks found")
    candidates = parse_float_list(args.candidate_f0s)
    if not candidates:
        if args.f0_step:
            count = int(math.floor((args.f0_max - args.f0_min) / args.f0_step)) + 1
            candidates = [args.f0_min + i * args.f0_step for i in range(max(count, 0))]
        else:
            candidates = harmonic_candidates_from_peaks(peaks, args.f0_min, args.f0_max)
    families = [
        score_harmonic_family(
            peaks,
            f0,
            args.min_order,
            args.max_order,
            args.tolerance_hz,
            args.relative_tolerance,
            args.missing_penalty,
        )
        for f0 in candidates
    ]
    families = [f for f in families if f["matched_harmonics"] >= args.min_matches]
    families.sort(key=lambda f: (-float(f["score"]), -float(f["coverage"]), float(f["f0_hz"])))
    top = families[: args.top_k]
    if args.families_csv:
        rows = [{k: v for k, v in f.items() if k != "matches"} for f in top]
        write_records(args.families_csv, rows)
    return {
        "mode": "harmonic-assoc",
        "settings": arg_settings(args),
        "peak_count": len(peaks),
        "candidate_count": len(candidates),
        "family_count": len(families),
        "families": top,
    }


def parse_line_specs(text: Optional[str]) -> List[Tuple[float, float, float]]:
    specs: List[Tuple[float, float, float]] = []
    if not text:
        return specs
    for item in text.split(","):
        item = item.strip()
        if not item:
            continue
        parts = item.split(":")
        if len(parts) == 1:
            specs.append((float(parts[0]), 1.0, 0.0))
        elif len(parts) == 2:
            specs.append((float(parts[0]), float(parts[1]), 0.0))
        elif len(parts) == 3:
            specs.append((float(parts[0]), float(parts[1]), float(parts[2])))
        else:
            raise ValueError(f"Line spec should be freq[:amp[:phase]], got {item!r}")
    return specs


def parse_drift_specs(text: Optional[str]) -> List[Tuple[float, float, float]]:
    specs: List[Tuple[float, float, float]] = []
    if not text:
        return specs
    for item in text.split(","):
        parts = [p.strip() for p in item.split(":")]
        if len(parts) not in {2, 3}:
            raise ValueError(f"Drift spec should be f_start:f_end[:amp], got {item!r}")
        amp = float(parts[2]) if len(parts) == 3 else 1.0
        specs.append((float(parts[0]), float(parts[1]), amp))
    return specs


def parse_harmonic_specs(text: Optional[str]) -> List[Tuple[float, int, float]]:
    specs: List[Tuple[float, int, float]] = []
    if not text:
        return specs
    for item in text.split(","):
        parts = [p.strip() for p in item.split(":")]
        if len(parts) not in {2, 3}:
            raise ValueError(f"Harmonic spec should be f0:count[:decay], got {item!r}")
        decay = float(parts[2]) if len(parts) == 3 else 1.0
        specs.append((float(parts[0]), int(parts[1]), decay))
    return specs


def cmd_synth(args: argparse.Namespace) -> Dict[str, Any]:
    rng = np.random.default_rng(args.seed)
    n = int(round(args.fs * args.duration_s))
    t = np.arange(n, dtype=float) / args.fs
    signal = np.zeros(n, dtype=float)
    truth_lines: List[Dict[str, Any]] = []
    truth_track: List[Dict[str, Any]] = []

    for freq, amp, phase in parse_line_specs(args.lines):
        signal += amp * np.sin(2.0 * np.pi * freq * t + phase)
        truth_lines.append({"freq_hz": float(freq), "label": f"line_{freq:g}", "amplitude": float(amp)})

    for f0, count, decay in parse_harmonic_specs(args.harmonics):
        for order in range(1, count + 1):
            amp = 1.0 / (order ** decay)
            freq = f0 * order
            phase = rng.uniform(0.0, 2.0 * np.pi)
            signal += amp * np.sin(2.0 * np.pi * freq * t + phase)
            truth_lines.append(
                {
                    "freq_hz": float(freq),
                    "label": f"harmonic_{f0:g}_{order}",
                    "f0_hz": float(f0),
                    "order": order,
                    "amplitude": float(amp),
                }
            )

    for idx, (f_start, f_end, amp) in enumerate(parse_drift_specs(args.drift_lines), start=1):
        duration = max(args.duration_s, EPS)
        k = (f_end - f_start) / duration
        phase = 2.0 * np.pi * (f_start * t + 0.5 * k * t * t)
        signal += amp * np.sin(phase)
        frame_count = max(args.truth_track_points, 2)
        for ti in np.linspace(0.0, args.duration_s, frame_count):
            freq = f_start + k * ti
            truth_track.append({"time_s": float(ti), "freq_hz": float(freq), "label": f"drift_{idx}"})

    signal_power = float(np.mean(signal * signal))
    if args.snr_db is not None:
        noise_power = signal_power / max(10.0 ** (args.snr_db / 10.0), EPS) if signal_power > 0 else 1.0
        signal += rng.normal(0.0, math.sqrt(noise_power), size=n)
    elif args.noise_std > 0:
        signal += rng.normal(0.0, args.noise_std, size=n)

    if args.output.endswith(".npy"):
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        np.save(args.output, signal)
    else:
        write_signal_csv(args.output, t, signal)
    if args.truth_lines_csv:
        write_records(args.truth_lines_csv, truth_lines)
    if args.truth_track_csv:
        write_records(args.truth_track_csv, truth_track)
    return {
        "mode": "synth",
        "settings": arg_settings(args),
        "sample_count": n,
        "signal_power": signal_power,
        "output": args.output,
        "truth_line_count": len(truth_lines),
        "truth_track_count": len(truth_track),
        "truth_lines": truth_lines,
        "truth_track_sample": truth_track[: min(20, len(truth_track))],
    }


def add_common_detection_args(parser: argparse.ArgumentParser, cfar: bool = False) -> None:
    parser.add_argument("--scale", choices=["db", "linear"], default="db")
    parser.add_argument("--band", help="Search band as lo:hi in Hz")
    parser.add_argument("--threshold-db", type=float, default=6.0)
    parser.add_argument("--guard-bins", type=int, default=2)
    parser.add_argument("--train-bins", type=int, default=20)
    parser.add_argument("--min-distance-bins", type=int, default=2)
    parser.add_argument("--max-peaks", type=int)
    parser.add_argument("--no-local-max", action="store_true", help="Do not require local maxima")
    parser.add_argument("--detections-csv")
    parser.add_argument("--output")
    if not cfar:
        parser.add_argument("--background", choices=["median", "mean", "percentile"], default="median")
        parser.add_argument("--percentile", type=float, default=50.0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    synth = sub.add_parser("synth", help="Generate a synthetic tonal/harmonic/drifting-line signal")
    synth.add_argument("--output", required=True, help="Output signal CSV or NPY")
    synth.add_argument("--fs", type=float, required=True)
    synth.add_argument("--duration-s", type=float, required=True)
    synth.add_argument("--lines", help="Comma list of freq[:amp[:phase]]")
    synth.add_argument("--harmonics", help="Comma list of f0:count[:decay]")
    synth.add_argument("--drift-lines", help="Comma list of f_start:f_end[:amp]")
    synth.add_argument("--noise-std", type=float, default=0.0)
    synth.add_argument("--snr-db", type=float)
    synth.add_argument("--seed", type=int, default=0)
    synth.add_argument("--truth-lines-csv")
    synth.add_argument("--truth-track-csv")
    synth.add_argument("--truth-track-points", type=int, default=50)
    synth.add_argument("--json-output")
    synth.set_defaults(func=cmd_synth)

    welch = sub.add_parser("welch-detect", help="Raw waveform -> Welch PSD -> adaptive peak detection")
    welch.add_argument("--signal", required=True)
    welch.add_argument("--signal-column")
    welch.add_argument("--fs", type=float, required=True)
    welch.add_argument("--nperseg", type=int, required=True)
    welch.add_argument("--noverlap", type=int, default=0)
    welch.add_argument("--nfft", type=int)
    welch.add_argument("--window", choices=["hann", "hamming", "blackman", "rect", "flattop"], default="hann")
    welch.add_argument("--detrend", choices=["none", "mean", "linear"], default="mean")
    welch.add_argument("--threshold-db", type=float, default=6.0)
    welch.add_argument("--guard-bins", type=int, default=2)
    welch.add_argument("--train-bins", type=int, default=20)
    welch.add_argument("--min-distance-bins", type=int, default=2)
    welch.add_argument("--max-peaks", type=int)
    welch.add_argument("--band")
    welch.add_argument("--background", choices=["median", "mean", "percentile"], default="median")
    welch.add_argument("--percentile", type=float, default=50.0)
    welch.add_argument("--no-local-max", action="store_true")
    welch.add_argument("--psd-csv")
    welch.add_argument("--freqs-csv")
    welch.add_argument("--spectrum-csv", help="Write one-column Welch PSD in dB for metric-script input")
    welch.add_argument("--detections-csv")
    welch.add_argument("--output")
    welch.set_defaults(func=cmd_welch_detect)

    psd = sub.add_parser("psd-detect", help="PSD/spectrum vector -> adaptive peak detection")
    psd.add_argument("--spectrum", required=True)
    psd.add_argument("--freqs", required=True)
    add_common_detection_args(psd)
    psd.set_defaults(func=cmd_psd_detect)

    cfar = sub.add_parser("psd-cfar", help="PSD/spectrum vector -> CA/OS/GO/SO-CFAR peak detection")
    cfar.add_argument("--spectrum", required=True)
    cfar.add_argument("--freqs", required=True)
    add_common_detection_args(cfar, cfar=True)
    cfar.add_argument("--cfar", choices=["ca", "os", "go", "so"], default="os")
    cfar.add_argument("--os-rank", type=float, default=75.0, help="Percentile used by OS-CFAR")
    cfar.set_defaults(func=cmd_psd_cfar)

    lofar = sub.add_parser("lofar-detect", help="LOFAR/time-frequency matrix -> framewise line candidates")
    lofar.add_argument("--matrix", required=True)
    lofar.add_argument("--times", required=True)
    lofar.add_argument("--freqs", required=True)
    lofar.add_argument("--scale", choices=["db", "linear"], default="db")
    lofar.add_argument("--band")
    lofar.add_argument("--threshold-db", type=float, default=6.0)
    lofar.add_argument("--guard-bins", type=int, default=2)
    lofar.add_argument("--train-bins", type=int, default=20)
    lofar.add_argument("--min-distance-bins", type=int, default=2)
    lofar.add_argument("--max-peaks-per-frame", type=int, default=10)
    lofar.add_argument("--background", choices=["median", "mean", "percentile"], default="median")
    lofar.add_argument("--percentile", type=float, default=50.0)
    lofar.add_argument("--no-local-max", action="store_true")
    lofar.add_argument("--detections-csv")
    lofar.add_argument("--output")
    lofar.set_defaults(func=cmd_lofar_detect)

    ridge = sub.add_parser("ridge-track", help="Framewise detections -> simple greedy ridge tracks")
    ridge.add_argument("--detections", required=True)
    ridge.add_argument("--gate-hz", type=float, default=2.0)
    ridge.add_argument("--max-drift-hz-per-s", type=float, default=0.0)
    ridge.add_argument("--max-gap-s", type=float, default=1.0)
    ridge.add_argument("--min-points", type=int, default=3)
    ridge.add_argument("--min-duration-s", type=float, default=0.0)
    ridge.add_argument("--max-tracks-output", type=int, default=20)
    ridge.add_argument("--tracks-csv")
    ridge.add_argument("--points-csv")
    ridge.add_argument("--output")
    ridge.set_defaults(func=cmd_ridge_track)

    harmonic = sub.add_parser("harmonic-assoc", help="Peak list -> fundamental/harmonic family association")
    harmonic.add_argument("--peaks", required=True)
    harmonic.add_argument("--candidate-f0s", help="Comma-separated candidate fundamentals")
    harmonic.add_argument("--f0-min", type=float, default=1.0)
    harmonic.add_argument("--f0-max", type=float, required=True)
    harmonic.add_argument("--f0-step", type=float)
    harmonic.add_argument("--min-order", type=int, default=1)
    harmonic.add_argument("--max-order", type=int, default=20)
    harmonic.add_argument("--tolerance-hz", type=float, default=1.0)
    harmonic.add_argument("--relative-tolerance", type=float, default=0.0)
    harmonic.add_argument("--missing-penalty", type=float, default=1.0)
    harmonic.add_argument("--min-matches", type=int, default=2)
    harmonic.add_argument("--top-k", type=int, default=5)
    harmonic.add_argument("--families-csv")
    harmonic.add_argument("--output")
    harmonic.set_defaults(func=cmd_harmonic_assoc)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    result = args.func(args)
    json_output = getattr(args, "json_output", None)
    if getattr(args, "command", None) != "synth" and json_output is None:
        json_output = getattr(args, "output", None)
    emit(result, json_output)


if __name__ == "__main__":
    main()
