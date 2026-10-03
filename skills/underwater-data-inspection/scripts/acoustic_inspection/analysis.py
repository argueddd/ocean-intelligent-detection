"""Bounded first-pass spectral analysis. No source repair or normalization."""
import os
from pathlib import Path
import numpy as np
from scipy import signal
from .readers import InputRequired
from .quality import as_float


def analyze(source, cfg, dataset, out):
    fs = dataset["sample_rate_hz"]["value"]
    if fs is None:
        raise InputRequired("sample_rate_required", "Confirm sampling rate before seconds/Hz analysis.")
    start, requested_stop = dataset["sample_range"]
    stop = min(requested_stop, start+cfg["analysis_max_samples"])
    channels = dataset["channel_indices"][:cfg["analysis_max_channels"]]
    n = stop-start
    if n < 8:
        raise InputRequired("short_record", "At least 8 samples are required for this spectral baseline.")
    nperseg = cfg.get("nperseg", min(4096, n))
    if nperseg > n:
        raise InputRequired("window_too_long", "nperseg exceeds the actual analysis length; no silent shortening.")
    overlap = int(nperseg*cfg["overlap_fraction"])
    hop = nperseg-overlap
    segments = 1+(n-nperseg)//hop
    used = nperseg+(segments-1)*hop
    band = cfg.get("band_hz", [0.0, fs/2])
    if not (0 <= band[0] < band[1] <= fs/2):
        raise InputRequired("band_out_of_range", "band_hz must lie within [0, fs/2].")
    # Reserve space for raw input, transforms, products and plotting copies.
    estimate = n*(source.c+len(channels)*32)*8
    if estimate > source.budget:
        raise InputRequired("memory_budget", "Analysis working-set estimate exceeds budget; explicitly reduce analysis range/channels.")
    raw = source.read(start, stop, channels)
    x = as_float(raw)
    result = dict(
        coverage=dict(sample_range=[start, stop], channel_indices=channels,
                      complete_requested_range=(stop == requested_stop and channels == dataset["channel_indices"]),
                      selection_policy="prefix of requested sample/channel range; not a representative sample",
                      spectrum_sample_range=[start, start+used], unused_tail_samples=n-used),
        settings=dict(sample_rate_hz=fs, nperseg=nperseg, nfft=nperseg, window="hann",
                      overlap_fraction_requested=cfg["overlap_fraction"], noverlap=overlap,
                      detrend="constant per segment", scaling="density", return_onesided=True,
                      full_segments=segments, frequency_grid_spacing_hz=fs/nperseg, band_hz=band,
                      numeric_conversion="temporary float64; source unchanged",
                      display_db_floor=1e-300, display_db_reference="1 original numeric unit squared per Hz",
                      waveform_display="at most 4000 uniformly indexed points; not peak-preserving"),
        channels=[], pairs=[], artifacts=[])
    products = dict(time_s=(np.arange(n)+start)/fs, waveform=x, channel_indices=np.array(channels))
    valid = []
    kwargs = dict(fs=fs, window="hann", nperseg=nperseg, noverlap=overlap,
                  nfft=nperseg, detrend="constant")
    for j, channel in enumerate(channels):
        row = dict(channel_index=channel)
        if not np.isfinite(x[:, j]).all():
            row.update(status="skipped", reason="Analysis interval contains NaN/Inf; no filling or concatenation.")
            result["channels"].append(row)
            continue
        f, p = signal.welch(x[:, j], scaling="density", return_onesided=True, **kwargs)
        tf_f, tf_t, tf_p = signal.spectrogram(x[:, j], scaling="density", mode="psd",
                                             return_onesided=True, **kwargs)
        if not np.isfinite(p).all() or not np.isfinite(tf_p).all():
            raise InputRequired("numeric_range", "Spectral estimation overflow; no automatic rescaling.")
        mask = (f >= band[0]) & (f <= band[1])
        if not mask.any():
            raise InputRequired("empty_frequency_band", "No estimated frequency bins fall in the requested band.")
        products["frequency_hz"] = f[mask]
        products["frame_time_s"] = tf_t+start/fs
        products[f"psd_ch{channel}"] = p[mask]
        products[f"tf_psd_ch{channel}"] = tf_p[mask]
        peak = int(np.argmax(p[mask]))
        row.update(status="completed", full_band_psd_integral=float(p.sum()*fs/nperseg),
                   strongest_bin_hz=float(f[mask][peak]), strongest_bin_psd=float(p[mask][peak]),
                   interpretation="Strongest spectral bin only; no target or tonal-detection claim.")
        result["channels"].append(row)
        valid.append(j)
    for a in range(len(valid)):
        for b in range(a+1, len(valid)):
            ja, jb = valid[a], valid[b]
            pair = dict(channel_indices=[channels[ja], channels[jb]])
            if np.std(x[:, ja]) == 0 or np.std(x[:, jb]) == 0:
                pair.update(status="skipped", reason="Constant channel; correlation/coherence undefined.")
            else:
                pair.update(status="completed", correlation=float(np.corrcoef(x[:, ja], x[:, jb])[0, 1]))
                if segments < 2:
                    pair["coherence_reason"] = "Fewer than two complete segments; no coherence estimate."
                else:
                    cf, coh = signal.coherence(x[:, ja], x[:, jb], **kwargs)
                    key = f"coherence_ch{channels[ja]}_ch{channels[jb]}"
                    products[key] = coh[(cf >= band[0]) & (cf <= band[1])]
                    pair["coherence_product"] = key
                    pair["coherence_nonfinite_bins"] = int((~np.isfinite(products[key])).sum())
            result["pairs"].append(pair)
    np.savez_compressed(out/"analysis_products.npz", **products)
    result["artifacts"].append("analysis_products.npz")
    # Keep plotting cache inside the new run output.
    os.environ.setdefault("MPLCONFIGDIR", str(out/".mplconfig"))
    os.environ.setdefault("XDG_CACHE_HOME", str(out/".cache"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    indexes = np.unique(np.linspace(0, n-1, min(n, 4000), dtype=int))
    fig, axes = plt.subplots(len(channels), 1, figsize=(10, max(3, len(channels)*2.2)), squeeze=False)
    for j, channel in enumerate(channels):
        axes[j, 0].plot(products["time_s"][indexes], x[indexes, j], linewidth=.6)
        axes[j, 0].set_ylabel(f"ch {channel}\nraw value")
    axes[-1, 0].set_xlabel("Time (s), uniform fs-derived axis")
    fig.suptitle(f"Waveform preview | samples [{start}, {stop}) | display subsampled")
    fig.tight_layout()
    fig.savefig(out/"waveform.png", dpi=140)
    plt.close(fig)
    result["artifacts"].append("waveform.png")
    if valid:
        fig, ax = plt.subplots(figsize=(10, 4))
        for j in valid:
            channel = channels[j]
            ax.plot(products["frequency_hz"], 10*np.log10(np.maximum(products[f"psd_ch{channel}"], 1e-300)), label=f"ch {channel}")
        ax.set(xlabel="Frequency (Hz)", ylabel="PSD (dB re 1 raw-unit²/Hz)", title="Welch PSD | uncalibrated numeric scale")
        ax.legend()
        fig.tight_layout()
        fig.savefig(out/"psd.png", dpi=140)
        plt.close(fig)
        result["artifacts"].append("psd.png")
    for j in valid:
        channel = channels[j]
        fig, ax = plt.subplots(figsize=(10, 4))
        z = 10*np.log10(np.maximum(products[f"tf_psd_ch{channel}"], 1e-300))
        mesh = ax.pcolormesh(products["frame_time_s"], products["frequency_hz"], z, shading="nearest", cmap="viridis")
        ax.set(xlabel="Window-center time (s)", ylabel="Frequency (Hz)", title=f"Spectrogram ch {channel} | samples [{start}, {start+used})")
        fig.colorbar(mesh, ax=ax, label="PSD (dB re 1 raw-unit²/Hz)")
        fig.tight_layout()
        name = f"spectrogram_ch{channel}.png"
        fig.savefig(out/name, dpi=140)
        plt.close(fig)
        result["artifacts"].append(name)
    result["status"] = "completed" if len(valid) == len(channels) else "partial"
    return result
