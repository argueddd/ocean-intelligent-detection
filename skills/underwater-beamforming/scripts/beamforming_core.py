"""Numerical kernels. Internal APIs are NOT authorization entry points."""
from __future__ import annotations

from decimal import Decimal
from itertools import product
import math

import numpy as np
from scipy.signal import get_window


class NumericalError(ValueError):
    pass


def window_values(transform):
    return get_window(transform["window"], transform["window_samples"],
                      fftbins=transform["window_periodic"]).astype(np.float64)


def frame_starts(length, transform, *, training=False):
    size, hop = transform["window_samples"], transform["hop_samples"]
    if training or transform["boundary"] == "no_padding":
        return np.arange(0, length - size + 1, hop, dtype=np.int64)
    first = -((size - 1) // hop) * hop
    return np.arange(first, length, hop, dtype=np.int64)


def analyze(samples, transform, *, training=False):
    """Unscaled rFFT of real windowed frames; axes [frame, frequency, channel]."""
    x = np.asarray(samples, dtype=np.float64)
    if x.ndim != 2 or not np.isfinite(x).all():
        raise NumericalError("输入必须是有限实数二维波形；不修补 NaN/Inf。")
    win = window_values(transform)
    starts = frame_starts(len(x), transform, training=training)
    if not len(starts):
        raise NumericalError("没有完整帧。")
    left = max(0, -int(starts[0]))
    right = max(0, int(starts[-1]) + len(win) - len(x))
    mode = "reflect" if transform["boundary"] == "reflect" and not training else "constant"
    padded = np.pad(x, ((left, right), (0, 0)), mode=mode)
    result = np.empty((len(starts), transform["nfft"] // 2 + 1, x.shape[1]), complex)
    for i, start in enumerate(starts):
        block = padded[int(start) + left:int(start) + left + len(win)]
        result[i] = np.fft.rfft(block * win[:, None], n=transform["nfft"], axis=0)
    if not np.isfinite(result).all():
        raise NumericalError("STFT 数值溢出。")
    return result, starts


def synthesize(spectra, starts, length, transform, coverage_tolerance):
    """WOLA: preserve amplitude, require coverage of EVERY requested sample."""
    # irfft silently drops imaginary endpoint components: prohibit that here.
    edges = [0] + ([spectra.shape[1] - 1] if transform["nfft"] % 2 == 0 else [])
    if np.any(spectra[:, edges, :].imag != 0):
        raise NumericalError("DC/Nyquist 含虚部；不能用 irfft 静默舍弃。")
    win = window_values(transform)
    hop, size = transform["hop_samples"], len(win)
    if transform["synthesis"] == "dual_window":
        residue_energy = np.bincount(np.arange(size) % hop, weights=win * win,
                                     minlength=hop)
        if np.any(residue_energy <= coverage_tolerance):
            raise NumericalError("窗/步长不存在可用的对偶窗；不自动改重叠。")
        dual = win / residue_energy[np.arange(size) % hop]
    else:
        dual = win
    out = np.zeros((length, spectra.shape[2]), dtype=np.float64)
    denom = np.zeros(length)
    for i, start in enumerate(starts):
        block = np.fft.irfft(spectra[i], n=transform["nfft"], axis=0)[:size]
        lo, hi = max(0, int(start)), min(length, int(start) + size)
        src = slice(lo - int(start), hi - int(start))
        out[lo:hi] += block[src] * dual[src, None]
        denom[lo:hi] += win[src] * dual[src]
    if np.any(denom <= coverage_tolerance):
        raise NumericalError("请求区间存在不可重建的样本；不能补零或截断后冒充完整输出。")
    out /= denom[:, None]
    if not np.isfinite(out).all():
        raise NumericalError("时域重建数值溢出。")
    return out


def expand_directions(plan):
    if plan["mode"] == "specified":
        return np.asarray(plan["directions_deg"], dtype=float)
    axes = []
    for axis in plan["grid_axes"]:
        start, stop, step = (Decimal(str(axis[k])) for k in
                             ("start_deg", "stop_deg", "step_deg"))
        count = int((stop - start) // step) + 1
        if not axis["include_stop"] and start + (count - 1) * step == stop:
            count -= 1
        axes.append([float(start + i * step) for i in range(count)])
    return np.asarray(list(product(*axes)), dtype=float)


def direction_vectors(directions, basis, parameterization):
    forward, positive, up = np.asarray(basis, dtype=float)
    radians = np.deg2rad(directions)
    azimuth = radians[:, 0]
    elevation = radians[:, 1] if parameterization == "azimuth_elevation" else np.zeros(len(radians))
    return (np.cos(elevation)[:, None] *
            (np.cos(azimuth)[:, None] * forward + np.sin(azimuth)[:, None] * positive) +
            np.sin(elevation)[:, None] * up)


def steering(frequencies, coordinates, reference, vectors, speed):
    # u points FROM array TOWARD source. x_m(t)=s_ref(t-tau_m).
    # Explicit contraction avoids false Accelerate/SME FPE flags on NumPy 2.2.x.
    # Same dot product and sign convention; do not suppress numerical warnings.
    offsets = np.asarray(coordinates) - np.asarray(reference)
    delays = -np.einsum("mc,bc->mb", offsets, vectors, optimize=False) / speed
    response = np.exp(-2j * np.pi * frequencies[:, None, None] * delays[None, :, :])
    return response, delays


def cbf_weights(response, element_weights):
    gains = np.asarray(element_weights, dtype=float)
    weights = response * (gains / gains.sum())[None, :, None]
    if not np.isfinite(weights).all():
        raise NumericalError("CBF 权重不是有限数。")
    return weights


def mvdr_weights(snapshots, response, settings, response_tolerance):
    """One frequency, all beams. R=mean(x x^H); never use a matrix inverse."""
    x = np.asarray(snapshots, dtype=complex)
    if len(x) < settings["min_snapshots"]:
        raise NumericalError("MVDR 实际快拍不足；不减少最小快拍数。")
    if settings["center_snapshots"]:
        x = x - x.mean(axis=0, keepdims=True)
    covariance = np.einsum("ki,kj->ij", x, x.conj(), optimize=False) / len(x)
    loading = settings["diagonal_loading"]
    delta = (0.0 if loading["mode"] == "none" else
             loading["value"] * np.trace(covariance).real / x.shape[1]
             if loading["mode"] == "trace_relative" else loading["value"])
    loaded = covariance + delta * np.eye(x.shape[1])
    if not np.isfinite(loaded).all():
        raise NumericalError("MVDR 协方差溢出。")
    try:
        np.linalg.cholesky(loaded)
        condition = float(np.linalg.cond(loaded))
        if not math.isfinite(condition) or condition > settings["max_condition_number"]:
            raise NumericalError("MVDR 条件数超过确认阈值；不自动加大加载或改用 CBF。")
        solved = np.linalg.solve(loaded, response)
    except np.linalg.LinAlgError as exc:
        raise NumericalError("MVDR 协方差非正定或不可解；不使用伪逆/算法替代。") from exc
    divisor = np.sum(response.conj() * solved, axis=0)
    if np.any(np.abs(divisor) == 0):
        raise NumericalError("MVDR 单位响应归一化失败。")
    weights = solved / divisor[None, :]
    residual = float(np.max(np.abs(np.sum(weights.conj() * response, axis=0) - 1)))
    if not np.isfinite(weights).all() or residual > response_tolerance:
        raise NumericalError("MVDR 权重未满足单位响应数值容差。")
    return weights, condition, float(delta), residual


def training_window(training_starts, window_samples, anchor_sample, count):
    """Trailing complete frames; explicitly offline-bootstrap first count frames."""
    end = int(np.searchsorted(training_starts + window_samples, anchor_sample, side="right"))
    end = min(len(training_starts), max(count, end))
    if end < count:
        raise NumericalError("完整训练帧不足。")
    return end - count, end


def conservative_mask(length, starts, window_samples, delay_samples):
    mask = np.ones(length, dtype=bool)
    for start in starts:
        if start < 0 or start + window_samples > length:
            mask[max(0, int(start)):min(length, int(start) + window_samples)] = False
    margin = window_samples + int(math.ceil(delay_samples))
    if margin:
        mask[:margin] = False
        mask[max(0, length - margin):] = False
    return mask
