"""Explicit-parameter CA/OS CFAR. No I/O, defaults, repairs or target decisions."""
from __future__ import annotations

import math
import numpy as np
from cfar_theory import ca_coefficient_iid_exponential, os_coefficient_iid_exponential

VERSION = "1.0.0"


def merge(intervals):
    result = []
    for a, b in sorted(intervals):
        if result and a <= result[-1][1]:
            result[-1][1] = max(b, result[-1][1])
        else:
            result.append([int(a), int(b)])
    return result


def complement(requested, processed):
    result = []
    for a, b in requested:
        cursor = a
        for c, d in processed:
            if d <= cursor or c >= b:
                continue
            if c > cursor:
                result.append([cursor, c])
            cursor = max(cursor, d)
        if cursor < b:
            result.append([cursor, b])
    return result


def frame_count(intervals, length, hop, origin):
    count = 0
    for a, b in intervals:
        first = a if origin == "each_interval_start" else ((a + hop - 1) // hop) * hop
        count += max(0, (b - length - first) // hop + 1)
    return count


def plan(task, inp, waveform, mask, max_working_bytes, *, calibrating=False):
    """Check complete frames and geometric CFAR cells, without computing a PSD."""
    p = task["resolved_parameters"]
    s, c, th = p["spectrum"], p["cfar"], p["threshold"]
    length, hop, nfft = s["window_length"], s["hop_length"], s["nfft"]
    fs = inp["sample_rate_hz"]
    n = inp["waveform"]["sample_count"]
    if length < 2 or hop < 1 or nfft < length:
        raise ValueError("Require window_length >= 2, hop >= 1, nfft >= window_length.")
    count = frame_count(task["scope"]["sample_intervals"], length, hop, s["frame_origin"])
    # Includes conservative Python candidate/ledger storage; not an OS RSS promise.
    estimate = n * 32 + (nfft // 2 + 1) * max(count, 1) * 12288 + length * 128 + 1048576
    if estimate > max_working_bytes:
        raise ValueError(f"Working allocation estimate {estimate} exceeds explicit limit {max_working_bytes}.")
    if waveform.shape != (n, 1) or waveform.dtype != np.dtype("float64"):
        raise ValueError("Waveform must remain float64 [sample, 1].")
    if mask is not None and (mask.shape != (n,) or mask.dtype != np.dtype("bool")):
        raise ValueError("Mask must remain bool [sample].")
    validity = inp["validity"]
    if validity["status"] != "known" and s["unknown_validity"] != "analyze_unverified":
        raise ValueError("Unknown validity requires an explicit analyze_unverified decision.")
    if validity["status"] == "known" and validity["sample_intervals"] is None and mask is None:
        raise ValueError("Known validity has no intervals or mask.")
    freq = np.fft.rfftfreq(nfft, 1 / fs)
    rlo, rhi = c["reference_band_hz"]
    lo, hi = task["scope"]["search_band_hz"]
    if not 0 <= rlo < rhi <= fs / 2 or not rlo <= lo < hi <= rhi:
        raise ValueError("Search band must lie inside explicit reference band and Nyquist.")
    cov = inp["frequency_coverage"]
    if cov["status"] == "known" and not cov["band_hz"][0] <= rlo < rhi <= cov["band_hz"][1]:
        raise ValueError("Reference support exceeds known upstream band; no silent expansion.")
    R, G = c["reference_per_side"], c["guard_per_side"]
    method = task["detector"]["detector_id"]
    if method == "ca_cfar" and c["rank"] is not None:
        raise ValueError("CA requires rank=null, not an ignored OS parameter.")
    if method == "os_cfar" and (type(c["rank"]) is not int or not 1 <= c["rank"] <= 2 * R):
        raise ValueError("OS rank is a one-based integer in 1..2*reference_per_side.")
    if 2 * R > 100000:
        raise ValueError("Reference count exceeds implemented theory/core bound.")
    offsets = np.r_[np.arange(-G-R, -G), np.arange(G+1, G+R+1)]
    interior = (freq > 0) & (freq < fs / 2) & (freq >= rlo) & (freq <= rhi)
    cuts, excluded = [], []
    for k in np.flatnonzero((freq >= lo) & (freq <= hi)):
        refs = k + offsets
        eligible = bool(interior[k] and refs[0] >= 0 and refs[-1] < len(freq)
                        and np.all(interior[refs]))
        if eligible:
            cuts.append(int(k))
        else:
            excluded.append(int(k))
    if excluded and c["insufficient_reference"] == "stop":
        raise ValueError("Search contains DC/Nyquist or cells without full two-sided references.")
    if not cuts:
        raise ValueError("No eligible CFAR cells; this is not a zero-candidate success.")
    frames, ledger = [], []
    for a, b in task["scope"]["sample_intervals"]:
        first = a if s["frame_origin"] == "each_interval_start" else ((a + hop - 1) // hop) * hop
        for start in range(first, b - length + 1, hop):
            end = start + length
            reason = None
            if validity["sample_intervals"] is not None and not any(
                    v <= start and end <= w for v, w in validity["sample_intervals"]):
                reason = "outside_known_valid_intervals"
            if mask is not None and not np.all(mask[start:end]):
                reason = "invalid_mask_samples"
            if not np.all(np.isfinite(waveform[start:end, 0])):
                reason = "nonfinite_samples"
            if reason and s["invalid_frame"] == "stop":
                raise ValueError(f"Invalid complete frame [{start},{end}): {reason}.")
            ledger.append({"start_sample": start, "stop_sample": end,
                           "status": "skipped" if reason else "eligible", "reason": reason})
            if reason is None:
                frames.append([start, end])
    if not frames:
        raise ValueError("No complete valid frames; this is not a zero-candidate success.")
    if task["task_kind"] == "average_spectrum" and th["event_scope"] != "segment":
        raise ValueError("Average-spectrum detection is one segment event, not per-frame detection.")
    if not calibrating and th["route"] == "theory":
        model = th["theory_assumption"]
        if model is None or th["calibration_ref"] is not None:
            raise ValueError("Theory requires explicit model rationale and calibration_ref=null.")
        if task["task_kind"] == "average_spectrum":
            raise ValueError("Averaged PSD is not single exponential: choose matching offline calibration.")
        if (s["window"] != "rectangular" or nfft != length or inp["data_role"] == "beamformed") and (
                model["applicability"] != "nominal_approximation"):
            raise ValueError("Window/zero padding/beamformed input needs explicit nominal_approximation acknowledgement.")
    elif not calibrating and (th["theory_assumption"] is not None or th["calibration_ref"] is None):
        raise ValueError("Calibration requires a record and theory_assumption=null.")
    width = p["candidates"]["group_width_hz"]
    if width is not None and not 0 <= width[0] <= width[1]:
        raise ValueError("Invalid explicitly selected group-width range.")
    rows = len(frames) if task["task_kind"] == "framewise" else 1
    M = len(cuts) * (rows if th["event_scope"] == "segment" else 1)
    p_cell = th["event_probability"] / M
    if p_cell == 0:
        raise ValueError("Cell budget underflow; cannot replace it by zero.")
    return {"frequency_hz": freq, "cuts": np.asarray(cuts, dtype=np.int64), "offsets": offsets,
            "excluded_frequency_bins": excluded, "frames": frames, "frame_ledger": ledger,
            "rows": rows, "tests_per_event": M, "p_cell": p_cell,
            "working_bytes_estimate": estimate,
            "validity_status": validity["status"], "scope": task["scope"]}


def periodogram(x, fs, params):
    length = params["window_length"]
    window = np.ones(length) if params["window"] == "rectangular" else (
        0.5 - 0.5 * np.cos(2 * np.pi * np.arange(length) / length))
    values = x - np.mean(x) if params["demean"] else x
    with np.errstate(over="raise", invalid="raise", divide="raise"):
        y = np.fft.rfft(values * window, n=params["nfft"])
        psd = np.abs(y) ** 2 / (fs * np.sum(window ** 2))
        psd[1:-1 if params["nfft"] % 2 == 0 else None] *= 2
    if not np.all(np.isfinite(psd)):
        raise ValueError("Nonfinite PSD; no rescaling or replacement.")
    return psd


def spectra(waveform, fs, task, prepared):
    """Yield row index, exact sample support and one linear PSD."""
    params = task["resolved_parameters"]["spectrum"]
    if task["task_kind"] == "framewise":
        for i, (a, b) in enumerate(prepared["frames"]):
            yield i, [[a, b]], periodogram(waveform[a:b, 0], fs, params)
    else:
        total = np.zeros(len(prepared["frequency_hz"]), dtype=np.float64)
        count = len(prepared["frames"])
        # Sum scaled terms to avoid unnecessary overflow; arithmetic mean, no other weights.
        for a, b in prepared["frames"]:
            total += periodogram(waveform[a:b, 0], fs, params) / count
        if not np.all(np.isfinite(total)):
            raise ValueError("Nonfinite averaged PSD.")
        yield 0, merge(prepared["frames"]), total


def background(psd, task, prepared):
    c = task["resolved_parameters"]["cfar"]
    cuts = prepared["cuts"]
    z = np.empty(len(cuts))
    for i, k in enumerate(cuts):
        values = psd[k + prepared["offsets"]]
        z[i] = np.mean(values) if task["detector"]["detector_id"] == "ca_cfar" else (
            np.partition(values, c["rank"] - 1)[c["rank"] - 1])
    good = np.isfinite(z) & (z > 0)
    if not np.all(good) and c["zero_background"] == "stop":
        raise ValueError("Nonpositive/nonfinite background; no epsilon replacement.")
    return z, good


def candidates(psd, z, threshold, good, prepared, params):
    cuts, freq = prepared["cuts"], prepared["frequency_hz"]
    indices = np.flatnonzero(good & (psd[cuts] > threshold))
    groups = []
    for i in indices:
        if not groups or cuts[i] != cuts[groups[-1][-1]] + 1:
            groups.append([int(i)])
        else:
            groups[-1].append(int(i))
    raw, rejected = [], []
    df = freq[1] - freq[0]
    for group in groups:
        bins = cuts[group]
        max_power = np.max(psd[bins])
        ties = bins[psd[bins] == max_power]
        k = int(ties[0]); ci = int(np.searchsorted(cuts, k))
        width = float(len(bins) * df)
        item = {"bin": k, "frequency_hz": float(freq[k]), "power": float(psd[k]),
                "background": float(z[ci]), "threshold": float(threshold[ci]),
                "ratio": float(psd[k] / z[ci]), "group_bins": [int(bins[0]), int(bins[-1])],
                "group_width_hz": width, "tied_maximum_bins": [int(v) for v in ties],
                "plateau_extent_bins": [int(ties[0]), int(ties[-1])],
                "plateau_is_contiguous": bool(np.all(np.diff(ties) == 1))}
        bounds = params["group_width_hz"]
        if bounds is not None and not bounds[0] <= width <= bounds[1]:
            rejected.append({**item, "reason": "group_width_filter"})
        else:
            raw.append(item)
    kept = []
    distance = params["minimum_peak_distance_hz"]
    for item in sorted(raw, key=lambda x: (-x["power"], x["bin"])):
        if distance is not None and any(abs(item["frequency_hz"] - v["frequency_hz"]) < distance for v in kept):
            rejected.append({**item, "reason": "minimum_peak_distance_filter"})
        else:
            kept.append(item)
    return sorted(kept, key=lambda x: x["bin"]), rejected


def execute(task, inp, waveform, prepared, calibrated_alpha=None):
    p = task["resolved_parameters"]
    th, cf = p["threshold"], p["cfar"]
    coefficient = None
    if th["route"] == "theory":
        method = ca_coefficient_iid_exponential if task["detector"]["detector_id"] == "ca_cfar" else os_coefficient_iid_exponential
        args = [prepared["p_cell"], 2 * cf["reference_per_side"]]
        if task["detector"]["detector_id"] == "os_cfar":
            args.append(cf["rank"])
        coefficient = method(*args)
        alpha = coefficient.alpha
    else:
        alpha = calibrated_alpha
        if type(alpha) not in (int, float) or not math.isfinite(alpha) or alpha <= 0:
            raise ValueError("Missing/invalid matched calibration coefficient.")
    records, rows, psds, backgrounds, thresholds, eligible = [], [], [], [], [], []
    retain = set(task["products"]["compute"])
    keep_arrays = bool(retain & {"spectra", "spectrum_plot", "time_frequency_plot"})
    for i, support, psd in spectra(waveform, inp["sample_rate_hz"], task, prepared):
        z, good = background(psd, task, prepared)
        with np.errstate(over="raise", invalid="raise"):
            threshold = alpha * z
        if not np.all(np.isfinite(threshold[good])):
            raise ValueError("Threshold overflow; no infinite-threshold substitution.")
        found, rejected = candidates(psd, z, threshold, good, prepared, p["candidates"])
        for candidate in found:
            records.append({**candidate, "row": i, "sample_intervals": support})
        rows.append({"row": i, "sample_intervals": support,
                     "status": "tested" if np.any(good) else "no_testable_cells",
                     "tested_bins": prepared["cuts"][good].tolist(),
                     "zero_background_bins": prepared["cuts"][~good].tolist(),
                     "candidate_count": len(found), "rejected_groups": rejected})
        if keep_arrays:
            psds.append(psd)
            backgrounds.append(z); thresholds.append(threshold); eligible.append(good)
    if not any(row["tested_bins"] for row in rows):
        raise ValueError("No tested cells after background exclusions; not a zero-candidate success.")
    processed = merge([v for row in rows if row["tested_bins"] for v in row["sample_intervals"]])
    return {"candidates": records, "rows": rows, "frame_ledger": prepared["frame_ledger"],
            "processed": processed, "excluded": complement(task["scope"]["sample_intervals"], processed),
            "alpha": alpha, "coefficient": vars(coefficient) if coefficient else None,
            "tests_per_event": prepared["tests_per_event"], "p_cell": prepared["p_cell"] if coefficient else None,
            "excluded_frequency_bins": prepared["excluded_frequency_bins"],
            "frequency_hz": prepared["frequency_hz"], "cut_bins": prepared["cuts"],
            "psd": np.asarray(psds) if keep_arrays else None,
            "background": np.asarray(backgrounds) if keep_arrays else None,
            "threshold": np.asarray(thresholds) if keep_arrays else None,
            "cell_valid": np.asarray(eligible) if keep_arrays else None}
