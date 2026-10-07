"""Output-waveform PSD products. Internal API; callers must enforce approval."""
from __future__ import annotations

import html
from pathlib import Path

import numpy as np
from scipy.signal import get_window

import preflight as pf
from beamforming_core import NumericalError

PRODUCTS = ["psd", "time_frequency", "spatial_spectrum", "frequency_angle", "btr"]
IMPLEMENTATION_VERSION = "0.4.2"


def selected_products(requested=None):
    """None is the legacy internal full-bundle API, never a new request default."""
    if requested is None:
        return PRODUCTS.copy()
    if (not isinstance(requested, (list, tuple)) or not requested or
            any(not isinstance(p, str) or p not in PRODUCTS for p in requested) or
            len(set(requested)) != len(requested)):
        raise ValueError("谱产物须为明确、非空、无重复的支持项列表；不自动补项。")
    return list(requested)


def product_layout(requested):
    selected = selected_products(requested)
    layout = {
        "psd": ("psd", ["frequency", "scan_beam"]),
        "time_frequency": ("time_frequency_psd", ["frame", "frequency", "scan_beam"]),
        # Legacy configuration name: actual output power, NOT Capon.
        "spatial_spectrum": ("scan_power", ["scan_beam"]),
        "frequency_angle": ("psd" if "psd" in selected else "frequency_angle",
                            ["frequency", "scan_beam"]),
        "btr": ("btr_power", ["frame", "scan_beam"]),
    }
    return {p: layout[p] for p in selected}


ANALYSIS = {
    "profile": pf.Choice(("reconstructed_waveform_psd_v1",)),
    "window": pf.Choice(("hann", "hamming", "boxcar")),
    "window_periodic": pf.BOOL, "window_samples": pf.PINT,
    "hop_samples": pf.PINT, "nfft": pf.PINT,
    "band_hz": pf.Array(pf.NONNEG, length=2),
    "detrend": pf.Choice(("none",)),
    "frame_origin": pf.Choice(("output_sample_zero",)),
    "validity": pf.Choice(("complete_frames_all_samples_valid",)),
    "scaling": pf.Choice(("onesided_density",)),
    "time_average": pf.Choice(("arithmetic_mean_linear",)),
    "frequency_integration": pf.Choice(("bin_sum_df",)),
    "display": {
        "scale": pf.Choice(("shared_peak_db_per_quantity",)),
        "limits": pf.Choice(("shared_finite_range",)),
        "zero_power": pf.Choice(("mask",)),
    },
}


def check_analysis(settings, fs, samples, allowed_band, issue):
    checker = pf.Preflight({}, ".")
    ok = checker.schema(settings, ANALYSIS, "analysis")
    for problem in checker.issues:
        issue(problem["code"], problem["path"], problem["message"], problem["severity"])
    if not ok:
        return False
    a = settings
    if not 0 < a["hop_samples"] <= a["window_samples"] <= a["nfft"]:
        issue("ANALYSIS_LENGTH", "analysis", "要求 0 < 步长 <= 窗长 <= FFT 长度。", "invalid")
        ok = False
    if a["window_samples"] > samples:
        issue("ANALYSIS_WINDOW", "analysis", "谱分析窗超过片段长度。", "invalid")
        ok = False
    lo, hi = a["band_hz"]
    if not 0 <= lo < hi <= fs / 2 or lo < allowed_band[0] or hi > allowed_band[1]:
        issue("ANALYSIS_BAND", "analysis.band_hz", "分析频带必须位于已计算的频带内；不自动扩大。", "invalid")
        ok = False
    return ok


def estimate(settings, samples, beams, algorithms, requested=None):
    selected = selected_products(requested)
    # Upper bound includes all full frames, even if masks later reject some.
    frames = max(0, 1 + (samples - settings["window_samples"]) // settings["hop_samples"])
    bins = settings["nfft"] // 2 + 1
    # The internal frame PSD cube still exists; this is NOT streaming.
    working_matrix = 8 * algorithms * beams * (frames * bins + bins + frames + 1)
    matrix = 8 * algorithms * beams * (
        frames * bins * ("time_frequency" in selected) +
        bins * bool({"psd", "frequency_angle"}.intersection(selected)) +
        frames * ("btr" in selected) + ("spatial_spectrum" in selected))
    coordinates = 8 * (bins + 2 * frames)
    # Per-beam comparison image plus aggregate maps; conservative image allowance.
    figure_count = (beams * bool({"psd", "time_frequency"}.intersection(selected)) +
                    algorithms * (("frequency_angle" in selected) + ("btr" in selected)) +
                    ("spatial_spectrum" in selected))
    figures = figure_count * 2 * 1024**2
    return {"frames_upper_bound": frames, "bins_upper_bound": bins,
            "requested_products": selected, "figure_count": figure_count,
            "working_bytes": 4 * working_matrix + 8 * samples * beams * algorithms + 64 * 1024**2,
            "artifact_bytes": matrix + coordinates + figures + 6 * 1024**2}


def compute(waveforms, valid, fs, settings, first_sample_offset_seconds, requested=None):
    """Periodograms of FINAL reconstructed y, not internal adaptive STFT coefficients."""
    selected = selected_products(requested)
    x = np.asarray(waveforms)
    valid = np.asarray(valid)
    if x.ndim != 2 or x.dtype.kind != "f" or not np.isfinite(x).all():
        raise NumericalError("谱输入必须是有限实数二维波束时域信号。")
    if valid.dtype.kind != "b" or valid.shape != (len(x),):
        raise NumericalError("有效样本掩码与波形不一致。")
    length, hop, nfft = (settings[k] for k in ("window_samples", "hop_samples", "nfft"))
    candidates = np.arange(0, len(x) - length + 1, hop, dtype=np.int64)
    invalid_count = np.r_[0, np.cumsum(~valid, dtype=np.int64)]
    starts = candidates[(invalid_count[candidates + length] - invalid_count[candidates]) == 0]
    if not len(starts):
        raise NumericalError("没有完整落在有效区间内的分析帧；不会补零、跨缺口或改窗长。")
    frequencies = np.fft.rfftfreq(nfft, 1 / fs)
    active = (frequencies >= settings["band_hz"][0]) & (frequencies <= settings["band_hz"][1])
    if not active.any():
        raise NumericalError("分析频带没有 FFT 频点；不扩大频带。")
    win = get_window(settings["window"], length, fftbins=settings["window_periodic"])
    denominator = fs * np.sum(win ** 2)
    if denominator <= 0:
        raise NumericalError("分析窗能量为零。")
    factors = np.full(len(frequencies), 2.0)
    factors[0] = 1
    if nfft % 2 == 0:
        factors[-1] = 1
    density = np.empty((len(starts), int(active.sum()), x.shape[1]), dtype=np.float64)
    for frame, start in enumerate(starts):
        z = np.fft.rfft(x[start:start + length] * win[:, None], n=nfft, axis=0)
        power = (z.real ** 2 + z.imag ** 2) * (factors / denominator)[:, None]
        density[frame] = power[active]
    if not np.isfinite(density).all():
        raise NumericalError("谱计算产生非有限数；停止发布。")
    values = {
        "frequency_hz": frequencies[active], "frame_start_sample": starts,
        "time_seconds": first_sample_offset_seconds + (starts + (length - 1) / 2) / fs,
    }
    if "time_frequency" in selected:
        values["time_frequency_psd"] = density
    if {"psd", "frequency_angle"}.intersection(selected):
        # Same estimate; store once if both presentations are requested.
        key = "psd" if "psd" in selected else "frequency_angle"
        values[key] = density.mean(axis=0)
    if {"btr", "spatial_spectrum"}.intersection(selected):
        btr = density.sum(axis=1) * (fs / nfft)
        if "btr" in selected:
            values["btr_power"] = btr
        if "spatial_spectrum" in selected:
            values["scan_power"] = btr.mean(axis=0)
    if any(not np.isfinite(v).all() for v in values.values()):
        raise NumericalError("谱归约产生非有限数；停止发布。")
    return values


def attach(arrays, algorithm, values, requested=None):
    for key in dict.fromkeys(suffix for suffix, _ in product_layout(requested).values()):
        arrays[algorithm + "_" + key + ".npy"] = values[key]
    for key in ("frequency_hz", "frame_start_sample", "time_seconds"):
        name = "analysis_" + key + ".npy"
        if name in arrays and not np.array_equal(arrays[name], values[key]):
            raise NumericalError("算法间分析坐标不同，不能放入同一对比结果。")
        arrays[name] = values[key]


def metadata(settings, arrays, algorithms, units, requested=None):
    selected = selected_products(requested)
    per_algorithm = {}
    for algorithm in algorithms:
        entries = {}
        for product, (suffix, axes) in product_layout(selected).items():
            path = algorithm + "_" + suffix + ".npy"
            if path not in arrays:
                raise NumericalError("请求的谱产物缺失：" + path)
            key = "scan_power" if product == "spatial_spectrum" else product
            entries[key] = {"path": path, "axes": axes}
            if product == "frequency_angle" and "psd" in selected:
                entries[key]["alias_of"] = "psd"
        per_algorithm[algorithm] = entries
    return {
        "requested_products": selected, "delivered_products": selected.copy(),
        "implementation_version": IMPLEMENTATION_VERSION,
        "definition": "modified periodograms of reconstructed beam waveforms; NOT Capon inverse quadratic spectrum",
        "settings": settings, "units_input": units,
        "density_units": "input_unit^2/Hz (absolute calibration not inferred)",
        "power_units": "input_unit^2 (absolute calibration not inferred)",
        "actual_frequency_centers_hz": arrays["analysis_frequency_hz.npy"].tolist(),
        "frame_count": len(arrays["analysis_frame_start_sample.npy"]),
        "time_center_definition": "first_sample_offset + (start + (window_samples-1)/2)/fs",
        "frame_start_reference": "output-relative sample index; gaps are not compressed",
        "integration": "sum of included bin PSD values times fs/nfft; closed center selection",
        "per_algorithm": per_algorithm,
        "no_target_selection_or_tracking": True,
        "overlapping_frames_are_not_independent_snapshots": True,
    }


def shared_scale(values):
    """Relative dB only for display; no replacement of linear numeric evidence."""
    positive = [v[v > 0] for v in values]
    positive = [v for v in positive if v.size]
    if not positive:
        return {"reference_linear": None, "db_limits": [-1.0, 0.0], "all_zero": True}
    maximum = max(float(v.max()) for v in positive)
    minimum = min(float(v.min()) for v in positive)
    lower = 10 * (np.log10(minimum) - np.log10(maximum))
    return {"reference_linear": maximum, "db_limits": [min(float(lower), -1.0), 0.0],
            "all_zero": False}


def display_db(values, scale):
    result = np.ma.masked_all(values.shape, dtype=float)
    mask = values > 0
    if scale["reference_linear"] is not None:
        result[mask] = 10 * (np.log10(values[mask]) - np.log10(scale["reference_linear"]))
    return result


def cell_edges(centers, singleton_width):
    centers = np.asarray(centers, dtype=float)
    if len(centers) == 1:
        return np.array([centers[0] - singleton_width / 2, centers[0] + singleton_width / 2])
    mids = (centers[:-1] + centers[1:]) / 2
    return np.r_[centers[0] - (mids[0] - centers[0]), mids, centers[-1] + (centers[-1] - mids[-1])]


def render(destination, arrays, algorithms, directions, direction_plan, title, settings, fs,
           requested=None, beam_ids=None):
    """Static, offline PNG and linked gallery. No target detection, normalization in data or network."""
    selected = selected_products(requested)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap
    from matplotlib.gridspec import GridSpec

    folder = Path(destination) / "figures"
    folder.mkdir(exist_ok=False)
    cmap = LinearSegmentedColormap.from_list("beam_blue", ["#f2f7fb", "#86b7d4", "#285a8e", "#102b48"])
    cmap.set_bad("#d9d9d9")
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "figure.facecolor": "white", "savefig.facecolor": "white"})
    supplied_ids = beam_ids is not None
    if beam_ids is None:
        beam_ids = [f"beam_{i:06d}" for i in range(len(directions))]
    if (len(beam_ids) != len(directions) or any(not isinstance(i, str) or not i for i in beam_ids) or
            len(set(beam_ids)) != len(beam_ids)):
        raise ValueError("图的波束身份与方向数量不一致。")
    labels = [", ".join(f"{x:g}" for x in row) + " deg" for row in directions]
    family = {}
    if {"psd", "frequency_angle"}.intersection(selected):
        family["psd"] = "psd" if "psd" in selected else "frequency_angle"
    if "time_frequency" in selected:
        family["time_frequency"] = "time_frequency_psd"
    if "btr" in selected:
        family["btr"] = "btr_power"
    if "spatial_spectrum" in selected:
        family["scan_power"] = "scan_power"
    scales = {k: shared_scale([arrays[a + "_" + suffix + ".npy"] for a in algorithms])
              for k, suffix in family.items()}
    f, times = arrays["analysis_frequency_hz.npy"], arrays["analysis_time_seconds.npy"]
    # Subsets use categorical product columns so missing angles are not painted over.
    # A genuine monotone single angular coordinate is otherwise allowed. Otherwise use beam IDs,
    # never sort, interpolate, flatten a 2-D grid into a false physical-angle axis.
    d = np.asarray(directions)
    varying = [j for j in range(d.shape[1]) if len(np.unique(d[:, j])) > 1]
    angular = (not supplied_ids and len(varying) == 1 and len(d) > 1 and
               np.all(np.diff(d[:, varying[0]]) > 0))
    coordinate = d[:, varying[0]] if angular else np.arange(len(d))
    xlabel = ("Array angle (deg)" if d.shape[1] == 1 else
              "Azimuth (deg)" if varying == [0] else "Elevation (deg)") if angular else "Scan beam index (see direction table)"
    if supplied_ids:
        xlabel = "Selected product column (see beam ID / direction table)"
    tick_ids = np.unique(np.linspace(0, len(d) - 1, min(9, len(d)), dtype=int))
    figure_names = []

    def finish(fig, name):
        target = folder / name
        with target.open("xb") as handle:
            fig.savefig(handle, format="png", dpi=140, bbox_inches="tight")
        plt.close(fig)
        figure_names.append(name)

    def heat(ax, horizontal, vertical, values, scale, xlab, ylab, heading):
        # Nearest-centered cells; gaps in time are explicitly masked using separate runs.
        z = display_db(values, scale)
        if ylab.startswith("Time") and len(vertical) > 1:
            frame_starts = arrays["analysis_frame_start_sample.npy"]
            typical = settings["hop_samples"]
            cuts = np.r_[0, np.flatnonzero(np.diff(frame_starts) > typical) + 1, len(vertical)]
        else:
            cuts = [0, len(vertical)]
        artist = None
        for low, high in zip(cuts[:-1], cuts[1:]):
            horizontal_width = fs / settings["nfft"] if xlab.startswith("Frequency") else 1.0
            vertical_width = settings["hop_samples"] / fs if ylab.startswith("Time") else fs / settings["nfft"]
            artist = ax.pcolormesh(cell_edges(horizontal, horizontal_width),
                                  cell_edges(vertical[low:high], vertical_width), z[low:high],
                                  shading="flat", cmap=cmap,
                                  vmin=scale["db_limits"][0], vmax=scale["db_limits"][1])
        ax.set(xlabel=xlab, ylabel=ylab, title=heading)
        if scale["all_zero"]:
            ax.text(.5, .5, "All values zero; dB undefined", transform=ax.transAxes, ha="center")
        return artist

    colors = {"cbf": "#275f9c", "mvdr": "#bb641c"}
    styles = {"cbf": "-", "mvdr": "--"}
    per_beam_products = [p for p in ("psd", "time_frequency") if p in selected]
    for beam, label in enumerate(labels):
        if not per_beam_products:
            break
        fig = plt.figure(figsize=(12, 7.5 if len(per_beam_products) == 2 else 4.5), layout="constrained")
        gs = GridSpec(len(per_beam_products), len(algorithms), figure=fig,
                      height_ratios=[1 if p == "psd" else 1.6 for p in per_beam_products])
        if "psd" in selected:
            ax = fig.add_subplot(gs[0, :])
            for a in algorithms:
                ax.plot(f, display_db(arrays[a + "_psd.npy"][:, beam], scales["psd"]),
                        label=a.upper(), color=colors[a], linestyle=styles[a], linewidth=1.2)
            ax.set(xlabel="Frequency (Hz)", ylabel="PSD (relative dB)", ylim=scales["psd"]["db_limits"],
                   title=f"{title} | {beam_ids[beam]} | {label}")
            ax.grid(alpha=.2); ax.legend(loc="upper right")
        else:
            fig.suptitle(f"{title} | {beam_ids[beam]} | {label}")
        if "time_frequency" in selected:
            for column, a in enumerate(algorithms):
                ax = fig.add_subplot(gs[per_beam_products.index("time_frequency"), column])
                artist = heat(ax, f, times, arrays[a + "_time_frequency_psd.npy"][:, :, beam],
                              scales["time_frequency"], "Frequency (Hz)", "Time (s)",
                              a.upper() + " output spectrogram")
                fig.colorbar(artist, ax=ax, label="PSD (relative dB)")
        finish(fig, f"beam_{beam:06d}.png")

    for a in algorithms:
        for kind in ("frequency_angle", "btr"):
            if kind not in selected:
                continue
            fig, ax = plt.subplots(figsize=(11, 6), layout="constrained")
            if kind == "frequency_angle":
                values, vertical, scale, ylab = arrays[a + "_" + family["psd"] + ".npy"], f, scales["psd"], "Frequency (Hz)"
            else:
                values, vertical, scale, ylab = arrays[a + "_btr_power.npy"], times, scales["btr"], "Time (s)"
            artist = heat(ax, coordinate, vertical, values, scale, xlabel, ylab,
                          f"{title} | {a.upper()} | {kind.replace('_', ' ')}")
            ax.set_xticks(coordinate[tick_ids])
            fig.colorbar(artist, ax=ax, label=("PSD" if kind == "frequency_angle" else "Band power") + " (relative dB)")
            finish(fig, a + "_" + kind + ".png")
    if "spatial_spectrum" in selected:
        fig, ax = plt.subplots(figsize=(11, 5), layout="constrained")
        for a in algorithms:
            ax.plot(coordinate, display_db(arrays[a + "_scan_power.npy"], scales["scan_power"]),
                    label=a.upper(), color=colors[a], linestyle="None" if supplied_ids else styles[a],
                    marker=None if angular else "o", linewidth=1.4)
        ax.set(xlabel=xlabel, ylabel="Mean band power (relative dB)",
               ylim=scales["scan_power"]["db_limits"], title=title + " | scan output power (not Capon)")
        ax.set_xticks(coordinate[tick_ids]); ax.legend(); ax.grid(alpha=.2)
        finish(fig, "scan_power.png")
    beam_caption = " + ".join("PSD" if p == "psd" else "spectrogram" for p in per_beam_products)
    rows = ""
    for i, label in enumerate(labels):
        link = (f"<a href='figures/beam_{i:06d}.png'>{beam_caption}</a>"
                if per_beam_products else "未请求逐束图")
        rows += f"<tr><td>{i:06d}</td><td>{html.escape(beam_ids[i])}</td><td>{html.escape(label)}</td><td>{link}</td></tr>"
    aggregates = "".join(f"<figure><img loading='lazy' src='figures/{name}' alt='{name}'><figcaption>{name}</figcaption></figure>"
                         for name in figure_names if not name.startswith("beam_"))
    page = """<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Beamforming results</title><style>body{font:16px system-ui;max-width:1160px;margin:36px auto;padding:0 18px;color:#202b36}img{max-width:100%}table{border-collapse:collapse;width:100%}td,th{padding:9px;border-bottom:1px solid #ddd;text-align:left}figure{margin:28px 0}p{line-height:1.6}</style>"""
    page += "<h1>" + html.escape(title) + "</h1>"
    page += "<p>本次选择的谱产物：" + html.escape(", ".join(selected)) + "；只列出实际生成的图。</p>"
    page += "<p>所有请求方向的输出谱；未自动选峰、选波束或跟踪。时域文件仅按明确保留清单输出。"
    if supplied_ids:
        page += "本图集只包含明确选中的已保存波束；产物列不是原始扫描索引，未保存方向没有补算或插值。"
    page += "图为相对 dB，不是声压级。线性矩阵、频率/时间坐标、单位、有效帧、方向定义与显示参考见 result.json。"
    page += "PSD 与时频图分别在所有方向、所有算法间共用参考和色标；不是各图独立归一化。灰色表示零功率（dB 未定义）。"
    page += "单点图的单元宽度仅用于显示，不代表额外时间/角度覆盖。</p>"
    page += "<p>方向定义：" + html.escape(str(direction_plan)) + "</p>"
    page += aggregates + "<h2>方向与所选逐束图</h2><table><tr><th>产物列</th><th>波束 ID</th><th>方向</th><th>图</th></tr>" + rows + "</table></html>"
    (Path(destination) / "index.html").write_text(page, encoding="utf-8")
    return {"display_scales": scales, "figures": ["figures/" + n for n in figure_names],
            "gallery": "index.html", "angular_axis_used": bool(angular), "requested_products": selected,
            "direction_definition": direction_plan, "beam_ids": list(beam_ids)}
