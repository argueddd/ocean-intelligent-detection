"""Read-only container probing and explicitly selected waveform access."""
from __future__ import annotations
import math
from pathlib import Path
import struct
import wave
import zipfile
import numpy as np
import h5py
from scipy.io import whosmat, loadmat


class InputRequired(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def entry(name, shape, dtype, **extra):
    dt = np.dtype(dtype)
    shape = tuple(int(x) for x in shape)
    return dict(field=name, shape=list(shape), dtype=str(dt),
                estimated_bytes=math.prod(shape) * dt.itemsize,
                supported=dt.kind in "iuf" and dt.itemsize <= 8 and len(shape) in (1, 2),
                **extra)


def npy_header(stream):
    version = np.lib.format.read_magic(stream)
    if version == (1, 0):
        return np.lib.format.read_array_header_1_0(stream)
    if version == (2, 0):
        return np.lib.format.read_array_header_2_0(stream)
    raise InputRequired("unsupported_npy_version", f"NPY header version {version} is not supported.")


def fingerprint(path):
    p = Path(path).resolve(strict=True)
    s = p.stat()
    return dict(path=str(p), size_bytes=s.st_size, mtime_ns=s.st_mtime_ns)


def wav_layout(path):
    """Inspect public RIFF chunk headers without loading PCM or wave internals."""
    with Path(path).open("rb") as stream:
        header = stream.read(12)
        if len(header) != 12 or header[:4] != b"RIFF" or header[8:] != b"WAVE":
            raise InputRequired("unsupported_wav", "Only RIFF/WAVE PCM is supported.")
        stream.seek(0, 2)
        actual_size = stream.tell()
        riff_end = 8 + struct.unpack("<I", header[4:8])[0]
        if riff_end < 12:
            raise InputRequired("invalid_wav_structure", "WAV RIFF size does not contain its format identifier.")
        if riff_end > actual_size:
            raise InputRequired("truncated_wav", "WAV RIFF declares bytes beyond the end of the file.")
        if riff_end != actual_size:
            raise InputRequired("invalid_wav_structure", "WAV has bytes outside its declared RIFF container; no bytes are silently discarded.")
        offset, data_bytes, format_header = 12, None, None
        while offset < riff_end:
            if riff_end-offset < 8:
                raise InputRequired("truncated_wav", "WAV has an incomplete RIFF chunk header.")
            stream.seek(offset)
            tag, size = struct.unpack("<4sI", stream.read(8))
            payload_end = offset+8+size
            if payload_end > riff_end:
                raise InputRequired("truncated_wav", f"WAV chunk {tag!r} declares bytes beyond the RIFF container.")
            if tag == b"fmt ":
                if format_header is not None:
                    raise InputRequired("unsupported_wav", "Multiple WAV format chunks are not supported.")
                if size < 16:
                    raise InputRequired("truncated_wav", "WAV PCM format chunk is shorter than 16 bytes.")
                format_header = stream.read(16)
            elif tag == b"data":
                if data_bytes is not None:
                    raise InputRequired("unsupported_wav", "Multiple WAV data chunks are not supported; no audio chunk is silently ignored.")
                data_bytes = size
            # RIFF chunks are word-aligned. Python wave/scipy writers can omit
            # the final pad for an odd-length mono PCM8 data chunk; accept that
            # exact final-chunk case without changing or adding source bytes.
            offset = payload_end + (size % 2 if payload_end < riff_end else 0)
        if format_header is None or data_bytes is None:
            raise InputRequired("unsupported_wav", "WAV requires one format chunk and one data chunk.")
        encoding, channels, rate, byte_rate, alignment, bits = struct.unpack("<HHIIHH", format_header)
        return dict(riff_bytes=riff_end, data_bytes=data_bytes,
                    audio_format_code=encoding, channel_count=channels,
                    sample_rate_hz=rate, byte_rate=byte_rate,
                    declared_block_align=alignment, bits_per_sample=bits)


def probe(path):
    p = Path(path)
    suffix = p.suffix.lower()
    result = dict(source=fingerprint(p), fields=[], limitations=[])
    if h5py.is_hdf5(p):
        result["format"] = "hdf5"
        with h5py.File(p, "r") as f:
            def visit(name, obj):
                if isinstance(obj, h5py.Dataset):
                    unsafe = bool(obj.is_virtual or obj.external)
                    e = entry("/" + name, obj.shape, obj.dtype,
                              external_storage=unsafe)
                    if unsafe:
                        e["supported"] = False
                    result["fields"].append(e)
            f.visititems(visit)
        result["limitations"] = ["Axes require confirmation; no implicit MATLAB transpose.",
                                 "Soft/external links and external/virtual dataset storage are not read."]
    elif suffix == ".sio":
        from .sio import read_header
        header = read_header(p)
        result["format"] = "sio"
        result["sio_header"] = header
        result["fields"] = [entry("data", (header["sample_count"], header["channel_count"]), header["dtype"])]
        result["limitations"] = ["Supported SIO variant: id=10, int16 or float32, complete channel record groups.",
                                "Header has no sampling rate, units, sensor identity or array geometry.",
                                "Trailing record padding is not valid waveform data."]
    elif suffix == ".mat":
        result["format"] = "mat"
        types = dict(double="float64", single="float32", int8="int8", uint8="uint8",
                     int16="int16", uint16="uint16", int32="int32", uint32="uint32",
                     int64="int64", uint64="uint64")
        for name, shape, kind in whosmat(p):
            e = entry(name, shape, types.get(kind, "object"), matlab_class=kind)
            result["fields"].append(e)
        result["limitations"] = ["Selected variables are decoded in memory.",
                                 "Complex values are rejected after decoding; MAT class alone cannot establish realness."]
    elif suffix == ".npy":
        result["format"] = "npy"
        with p.open("rb") as f:
            shape, order, dtype = npy_header(f)
        result["fields"] = [entry("data", shape, dtype, fortran_order=order)]
    elif suffix == ".npz":
        result["format"] = "npz"
        with zipfile.ZipFile(p) as z:
            names = set()
            for item in z.infolist():
                if not item.filename.endswith(".npy"):
                    continue
                name = item.filename[:-4]
                if name in names:
                    raise InputRequired("duplicate_field", f"Duplicate archive field: {name}")
                names.add(name)
                with z.open(item) as stream:
                    shape, order, dtype = npy_header(stream)
                result["fields"].append(entry(name, shape, dtype, fortran_order=order))
        result["limitations"] = ["Selected archive member must fit decoded-memory budget."]
    elif suffix == ".wav":
        result["format"] = "wav"
        layout = wav_layout(p)
        try:
            with wave.open(str(p), "rb") as f:
                width = f.getsampwidth()
                if f.getcomptype() != "NONE" or width not in (1, 2, 4):
                    raise InputRequired("unsupported_wav", "Only uncompressed PCM WAV 8/16/32-bit is supported.")
                if layout["bits_per_sample"] not in (8, 16, 32):
                    raise InputRequired("unsupported_wav", f"Only PCM 8/16/32-bit containers are supported; WAV declares {layout['bits_per_sample']} bits. Bit depths are never rounded to a supported width.")
                if layout["sample_rate_hz"] <= 0:
                    raise InputRequired("invalid_wav_header", "WAV header sampling rate must be positive; no replacement rate is inferred.")
                frame_bytes = f.getnchannels()*width
                if layout["declared_block_align"] != frame_bytes:
                    raise InputRequired("invalid_wav_frame", "WAV PCM block alignment conflicts with its channel count and sample width.")
                expected_byte_rate = layout["sample_rate_hz"]*frame_bytes
                if layout["byte_rate"] != expected_byte_rate:
                    raise InputRequired("invalid_wav_header", f"WAV byte rate {layout['byte_rate']} conflicts with fs × frame width ({expected_byte_rate}); no header value is silently corrected.")
                if layout["data_bytes"] % frame_bytes:
                    raise InputRequired("wav_partial_frame", f"WAV data has {layout['data_bytes']} bytes, not a whole number of {frame_bytes}-byte PCM frames; no tail bytes are discarded.")
                dtype = {1: "uint8", 2: "int16", 4: "int32"}[width]
                result["fields"] = [entry("data", (f.getnframes(), f.getnchannels()), dtype)]
                result["header_sample_rate_hz"] = f.getframerate()
                result["sample_width_bytes"] = width
                result["wav_layout"] = {**layout, "frame_bytes": frame_bytes}
                result["limitations"] = ["PCM integer encoding is preserved; uint8 is not automatically centered."]
        except wave.Error as e:
            raise InputRequired("unsupported_wav", str(e)) from e
    else:
        raise InputRequired("unsupported_format", f"Unsupported format: {suffix or '(no extension)'}")
    return result


def select_field(info, cfg):
    selected = cfg.get("field")
    if selected is None and info["format"] in ("npy", "wav", "sio"):
        selected = "data"  # Defined by format, not inferred from array size/name.
    available = [e["field"] for e in info["fields"]]
    if selected not in available:
        raise InputRequired("field_required", f"Confirm waveform field; available fields: {available}")
    e = next(e for e in info["fields"] if e["field"] == selected)
    if not e["supported"]:
        raise InputRequired("unsupported_array", f"Unsupported waveform structure/type/storage: {e}")
    return e


def scalar_rate(path, info, field, budget):
    entries = [e for e in info["fields"] if e["field"] == field]
    if len(entries) != 1 or math.prod(entries[0]["shape"]) != 1:
        raise InputRequired("invalid_rate_field", "sample_rate_field must identify exactly one numeric scalar.")
    e = entries[0]
    if np.dtype(e["dtype"]).kind not in "iuf" or e.get("external_storage"):
        raise InputRequired("invalid_rate_field", "Sampling rate field must be a real numeric scalar in this file.")
    kind = info["format"]
    if kind == "hdf5":
        with h5py.File(path, "r") as f:
            val = f[field][()]
    elif kind == "mat":
        if sum(x["estimated_bytes"] for x in info["fields"]) * 2 > budget:
            raise InputRequired("memory_budget", "MAT decoding estimate exceeds budget.")
        val = loadmat(path, variable_names=[field], squeeze_me=False)[field]
    elif kind == "npz":
        with np.load(path, allow_pickle=False) as f:
            val = f[field]
    else:
        raise InputRequired("invalid_rate_field", "This format does not provide named scalar metadata fields.")
    a = np.asarray(val)
    if a.dtype.kind not in "iuf":
        raise InputRequired("invalid_rate_field", "Sampling-rate scalar is not real numeric.")
    v = float(a.reshape(-1)[0])
    if not np.isfinite(v) or v <= 0:
        raise InputRequired("invalid_rate_field", "Sampling rate must be finite and positive.")
    return v


class Source:
    """Explicit sample/channel view; no filtering, scaling, filling or reordering."""
    def __init__(self, path, info, selected, cfg):
        self.path, self.info, self.selected = Path(path), info, selected
        self.shape = selected["shape"]
        axis = cfg.get("sample_axis", 0 if info["format"] in ("wav", "sio") else None)
        if type(axis) is not int or axis not in (0, 1) or axis >= len(self.shape):
            raise InputRequired("sample_axis_required",
                                f"Confirm sample_axis for shape {self.shape}; no axis is inferred.")
        if info["format"] in ("wav", "sio") and axis != 0:
            raise InputRequired("axis_conflict", f"{info['format'].upper()} format defines sample_axis=0; supplied axis conflicts.")
        self.axis = axis
        self.n = self.shape[axis]
        self.c = self.shape[1-axis] if len(self.shape) == 2 else 1
        if self.n < 1 or self.c < 1:
            raise InputRequired("empty_data", "The selected waveform has zero samples or channels.")
        self.budget = int(cfg["max_read_mib"] * 1024**2)
        self.array = None
        kind = info["format"]
        if kind in ("mat", "npz"):
            estimate = (sum(e["estimated_bytes"] for e in info["fields"])
                        if kind == "mat" else selected["estimated_bytes"])
            if estimate * 2 > self.budget:
                raise InputRequired("memory_budget",
                                    f"{kind} decoding estimate with 2x allowance exceeds max_read_mib; no silent partial load.")
        if kind == "mat":
            self.array = loadmat(path, variable_names=[selected["field"]], squeeze_me=False)[selected["field"]]
        elif kind == "npz":
            with np.load(path, allow_pickle=False) as f:
                self.array = f[selected["field"]]
        elif kind == "npy":
            self.array = np.load(path, mmap_mode="r", allow_pickle=False)
        if self.array is not None and self.array.dtype.kind not in "iuf":
            self.close()
            raise InputRequired("unsupported_array", "Only real numeric waveforms are supported.")

    def close(self):
        if isinstance(self.array, np.memmap) and self.array._mmap is not None:
            self.array._mmap.close()
        self.array = None

    def block_size(self, requested):
        # Full original channel width is read before channel selection.
        size = max(np.dtype(self.selected["dtype"]).itemsize, 8)
        capacity = self.budget // (self.c * size * 8)
        if capacity < 1:
            raise InputRequired("memory_budget", "Even one full-channel frame exceeds working-memory allowance.")
        return min(requested, capacity)

    def read(self, start, stop, channels):
        if not (0 <= start < stop <= self.n):
            raise InputRequired("invalid_slice", "Read slice out of range.")
        key = slice(start, stop) if len(self.shape) == 1 else (
            (slice(start, stop), slice(None)) if self.axis == 0 else (slice(None), slice(start, stop)))
        kind = self.info["format"]
        if kind == "sio":
            from .sio import read_samples
            return read_samples(self.path, self.info["sio_header"], start, stop, channels)
        if kind == "hdf5":
            with h5py.File(self.path, "r") as f:
                raw = f[self.selected["field"]][key]
        elif kind == "wav":
            width = self.info["sample_width_bytes"]
            with wave.open(str(self.path), "rb") as f:
                f.setpos(start)
                buf = f.readframes(stop-start)
            if len(buf) != (stop-start)*self.c*width:
                raise InputRequired("truncated_data", "WAV data is shorter than its declared frame count.")
            raw = np.frombuffer(buf, dtype={1: "u1", 2: "<i2", 4: "<i4"}[width]).reshape(-1, self.c)
        else:
            raw = self.array[key]
        if raw.ndim == 1:
            raw = raw[:, None]
        elif self.axis == 1:
            raw = raw.T
        return raw[:, channels]
