"""Strict read-only decoder for the record-blocked SWellEx SIO variant.

Derived from the published sioread.m layout, using zero-based sample indices.
No sampling-rate, units, sensor identity or geometry defaults are provided.
"""
import struct
import numpy as np
from .readers import InputRequired


def read_header(path):
    with open(path, "rb") as stream:
        raw = stream.read(128)
        stream.seek(0, 2)
        actual_size = stream.tell()
    if len(raw) != 128:
        raise InputRequired("truncated_sio_header", "SIO needs at least 128 header bytes.")
    orders = [order for order in (">", "<") if struct.unpack(order+"i", raw[28:32])[0] == 32677]
    if len(orders) != 1:
        raise InputRequired("invalid_sio_magic", "Cannot establish byte order from SIO magic 32677.")
    order = orders[0]
    ident, nr, rl, nc, sl, numeric_kind, n, magic = struct.unpack(order+"8i", raw[:32])
    if ident != 10:
        raise InputRequired("unsupported_sio_variant", f"Only SIO id=10 is supported; found {ident}.")
    code = {(2, 0): "i2", (4, 1): "f4"}.get((sl, numeric_kind))
    if code is None:
        raise InputRequired("unsupported_sio_dtype", f"Unsupported SIO (sample_bytes, numeric_kind): {(sl, numeric_kind)}.")
    if nr <= 0 or nc <= 0 or n <= 0 or rl < 128 or rl % sl or nr % nc:
        raise InputRequired("invalid_sio_structure", "Invalid record dimensions or incomplete channel record group.")
    points = rl//sl
    groups = nr//nc
    if not (groups-1)*points < n <= groups*points:
        raise InputRequired("invalid_sio_sample_count", "Valid sample count conflicts with the number of channel record groups.")
    expected_size = (nr+1)*rl
    if actual_size != expected_size:
        raise InputRequired("sio_size_mismatch", f"SIO header requires {expected_size} bytes; found {actual_size}. No truncation/extra bytes are silently repaired.")
    return dict(id=ident, data_records=nr, record_bytes=rl, channel_count=nc,
                sample_bytes=sl, numeric_kind=numeric_kind, sample_count=n,
                magic=magic, byte_order="big" if order == ">" else "little",
                dtype=order+code, record_groups=groups, points_per_record=points,
                padding_samples_per_channel=groups*points-n,
                expected_file_bytes=expected_size,
                embedded_filename=raw[32:56].decode("ascii", errors="backslashreplace").rstrip("\x00 "),
                comment=raw[56:128].decode("ascii", errors="backslashreplace").rstrip("\x00 "),
                layout="one header record, then time groups of channel-major records")


def read_samples(path, header, start, stop, channels):
    n, nc = header["sample_count"], header["channel_count"]
    if not (0 <= start < stop <= n):
        raise InputRequired("invalid_slice", "SIO sample range is out of bounds.")
    if not channels or any(type(ch) is not int or ch < 0 or ch >= nc for ch in channels):
        raise InputRequired("invalid_channels", "SIO channel is out of bounds.")
    points, sl, rl = header["points_per_record"], header["sample_bytes"], header["record_bytes"]
    dtype = np.dtype(header["dtype"])
    result = np.empty((stop-start, len(channels)), dtype=dtype)
    with open(path, "rb") as stream:
        for group in range(start//points, (stop-1)//points+1):
            lo, hi = max(start, group*points), min(stop, (group+1)*points)
            offset_in_record = lo-group*points
            byte_count = (hi-lo)*sl
            for column, ch in enumerate(channels):
                offset = (1+group*nc+ch)*rl + offset_in_record*sl
                stream.seek(offset)
                raw = stream.read(byte_count)
                if len(raw) != byte_count:
                    raise InputRequired("truncated_sio_data", f"Short SIO read at byte offset {offset}.")
                result[lo-start:hi-start, column] = np.frombuffer(raw, dtype=dtype)
    return result
