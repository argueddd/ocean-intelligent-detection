"""Streaming statistics, preserving original sample locations."""
import math
import numpy as np
from .readers import InputRequired


def as_float(raw):
    if raw.dtype.kind in "iu" and raw.dtype.itemsize >= 8:
        if np.any(raw > 2**53) or (raw.dtype.kind == "i" and np.any(raw < -(2**53))):
            raise InputRequired("integer_precision", "Values beyond 2^53 cannot be analyzed in float64 without precision loss.")
    return raw.astype(np.float64)


class ChannelStats:
    def __init__(self, channel, identity):
        self.channel, self.identity = channel, identity
        self.total = self.finite = self.nan = self.posinf = self.neginf = self.zero = 0
        # Internal arithmetic scale only: samples, runs and exported units stay
        # unchanged. Squaring raw 1e-200 or 1e200 would underflow or overflow.
        self._scale = self._mean = self._m2 = self._sumsq = 0.0
        self._sum = self._sum_correction = 0.0
        # Variance uses a fixed original-unit origin before scaling, preserving
        # small representable differences on a large DC background.
        self._origin = None
        self._variance_scale = self._shifted_mean = 0.0
        self._shifted_sum = self._shifted_correction = 0.0
        self._offset_sum = self._offset_correction = 0.0
        self.minimum = self.maximum = None
        self.tail_value, self.tail_start, self.tail_length = None, None, 0
        self.constant = dict(start_sample=None, stop_sample=None, length=0)
        self.zeros = dict(start_sample=None, stop_sample=None, length=0)
        self.nonfinite_ranges = []
        self.nonfinite_range_count = 0
        self.last_nonfinite_stop = None

    def feed(self, raw, offset):
        x = as_float(raw)
        good = np.isfinite(x)
        n = len(x)
        self.total += n
        self.nan += int(np.isnan(x).sum())
        self.posinf += int(np.isposinf(x).sum())
        self.neginf += int(np.isneginf(x).sum())
        self.zero += int((good & (x == 0)).sum())
        # Exact first 100 nonfinite intervals, merging at chunk boundaries.
        boundaries = np.diff(np.r_[False, ~good, False].astype(np.int8))
        bad_starts = np.flatnonzero(boundaries == 1)+offset
        bad_stops = np.flatnonzero(boundaries == -1)+offset
        for begin, end in zip(bad_starts, bad_stops):
            if self.last_nonfinite_stop == int(begin):
                if self.nonfinite_range_count <= 100:
                    self.nonfinite_ranges[-1][1] = int(end)
            else:
                self.nonfinite_range_count += 1
                if self.nonfinite_range_count <= 100:
                    self.nonfinite_ranges.append([int(begin), int(end)])
            self.last_nonfinite_stop = int(end)
        vals = x[good]
        if vals.size:
            k = len(vals)
            lo, hi = float(vals.min()), float(vals.max())
            scale = max(self._scale, abs(lo), abs(hi))
            if scale > self._scale:
                factor = self._scale / scale
                if self._mean and not self._mean * factor:
                    raise InputRequired("numeric_range", "Statistics span an unrepresentable float64 arithmetic range; original samples are unchanged.")
                self._mean *= factor
                self._sum *= factor
                self._sum_correction *= factor
                self._sumsq *= factor * factor
                self._scale = scale
            with np.errstate(under="ignore"):
                normalized = vals / scale if scale else vals
            if np.any((vals != 0) & (normalized == 0)):
                raise InputRequired("numeric_range", "Statistics span an unrepresentable float64 arithmetic range; original samples are unchanged.")
            batch_sum = math.fsum(normalized)
            sq = float(np.sum(normalized ** 2))
            count = self.finite + k
            self._feed_variance(vals, k, count)
            self._sumsq += sq
            # Compensated sums avoid a block-dependent false DC residual when
            # large positive and negative values cancel.
            total = self._sum + batch_sum
            if abs(self._sum) >= abs(batch_sum):
                self._sum_correction += (self._sum - total) + batch_sum
            else:
                self._sum_correction += (batch_sum - total) + self._sum
            self._sum = total
            self._mean = math.fsum((self._sum, self._sum_correction)) / count
            if not all(math.isfinite(v) for v in (self._mean, self._m2, self._sumsq)):
                raise InputRequired("numeric_range", "Statistics cannot be represented safely in float64; original samples are unchanged.")
            self.finite = count
            self.minimum = lo if self.minimum is None else min(self.minimum, lo)
            self.maximum = hi if self.maximum is None else max(self.maximum, hi)
        # Vectorized runs; invalid values always break a run.
        same = good[1:] & good[:-1] & (x[1:] == x[:-1])
        starts = np.r_[0, np.flatnonzero(~same)+1]
        stops = np.r_[starts[1:], n]
        lengths = stops-starts
        global_starts = starts+offset
        if good[0] and self.tail_length and x[0] == self.tail_value:
            lengths[0] += self.tail_length
            global_starts[0] = self.tail_start
        for target, mask in ((self.constant, good[starts]), (self.zeros, good[starts] & (x[starts] == 0))):
            eligible = np.where(mask, lengths, 0)
            i = int(np.argmax(eligible))
            if int(eligible[i]) > target["length"]:
                target.update(start_sample=int(global_starts[i]),
                              stop_sample=int(stops[i]+offset), length=int(eligible[i]))
        if good[-1]:
            self.tail_value = x[-1]
            self.tail_start, self.tail_length = int(global_starts[-1]), int(lengths[-1])
        else:
            self.tail_value, self.tail_start, self.tail_length = None, None, 0

    def _feed_variance(self, vals, k, count):
        if self._origin is None:
            self._origin = float(vals[0])
        with np.errstate(over="ignore", invalid="ignore"):
            shifted = vals - self._origin
        representable = np.isfinite(shifted)
        if self._offset_sum is not None:
            try:
                batch_offset = math.fsum(shifted) if np.all(representable) else math.inf
                total = self._offset_sum + batch_offset
                if not math.isfinite(total):
                    self._offset_sum = None
                else:
                    if abs(self._offset_sum) >= abs(batch_offset):
                        self._offset_correction += (self._offset_sum - total) + batch_offset
                    else:
                        self._offset_correction += (batch_offset - total) + self._offset_sum
                    self._offset_sum = total if math.isfinite(self._offset_correction) else None
            except OverflowError:
                self._offset_sum = None
        scale = self._variance_scale
        if np.any(representable):
            scale = max(scale, float(np.max(np.abs(shifted[representable]))))
        if not np.all(representable):
            # Opposite float64 extremes can have an unrepresentable difference
            # even though their population std is representable. Use this safe
            # subtraction only for those elements, retaining close differences.
            scale = max(scale, abs(self._origin), float(np.max(np.abs(vals))))
        if scale > self._variance_scale:
            factor = self._variance_scale / scale
            self._shifted_mean *= factor
            self._shifted_sum *= factor
            self._shifted_correction *= factor
            self._m2 *= factor * factor
            self._variance_scale = scale
        with np.errstate(under="ignore"):
            normalized = shifted / scale if scale else shifted.copy()
            if not np.all(representable):
                normalized[~representable] = vals[~representable] / scale - self._origin / scale
        if np.any(representable & (shifted != 0) & (normalized == 0)):
            raise InputRequired("numeric_range", "Variance spans an unrepresentable float64 arithmetic range; original samples are unchanged.")
        batch_sum = math.fsum(normalized)
        mean = batch_sum / k
        m2 = float(np.sum((normalized - mean) ** 2))
        delta = mean - self._shifted_mean
        self._m2 += m2 + delta * delta * (self.finite * k / count)
        total = self._shifted_sum + batch_sum
        if abs(self._shifted_sum) >= abs(batch_sum):
            self._shifted_correction += (self._shifted_sum - total) + batch_sum
        else:
            self._shifted_correction += (batch_sum - total) + self._shifted_sum
        self._shifted_sum = total
        self._shifted_mean = math.fsum((self._shifted_sum, self._shifted_correction)) / count

    def _original_units(self, value, name, scale=None):
        scale = self._scale if scale is None else scale
        result = value * scale
        if not math.isfinite(result) or (value and scale and result == 0):
            raise InputRequired("numeric_range", f"The {name} statistic is not representable in float64 in original units; original samples are unchanged.")
        return result

    def result(self):
        mean = std = rms = None
        if self.finite:
            mean = self._original_units(self._mean, "mean")
            if self._variance_scale <= abs(self._origin) / 2:
                # Close samples share the origin's sign, so reconstructing this
                # small offset preserves correct DC rounding without cancellation.
                # Retain the compensated raw mean if the offset underflows.
                offset_mean = self._shifted_mean * self._variance_scale
                has_offset = bool(self._shifted_mean)
                if self._offset_sum is not None:
                    try:
                        offset_sum = math.fsum((self._offset_sum, self._offset_correction))
                        if math.isfinite(offset_sum):
                            offset_mean = offset_sum / self.finite
                            has_offset = bool(offset_sum)
                    except OverflowError:
                        pass
                if offset_mean or not has_offset:
                    mean = self._origin + offset_mean
            std = self._original_units(math.sqrt(max(0.0, self._m2 / self.finite)), "population standard deviation", self._variance_scale)
            rms = self._original_units(math.sqrt(self._sumsq / self.finite), "RMS")
        return dict(channel_index=self.channel, channel_id=self.identity,
                    sample_count=self.total, finite_count=self.finite,
                    nan_count=self.nan, positive_inf_count=self.posinf, negative_inf_count=self.neginf,
                    zero_count=self.zero, zero_fraction=self.zero/self.total,
                    finite_fraction=self.finite/self.total,
                    mean=mean, std_population=std, rms=rms,
                    minimum=self.minimum, maximum=self.maximum,
                    absolute_peak=max(abs(self.minimum), abs(self.maximum)) if self.finite else None,
                    longest_constant_run=self.constant, longest_zero_run=self.zeros,
                    nonfinite_ranges=self.nonfinite_ranges,
                    nonfinite_range_count=self.nonfinite_range_count,
                    nonfinite_ranges_truncated=self.nonfinite_range_count > 100,
                    statistics_denominator="finite_count",
                    statistics_reason=None if self.finite else "No finite samples; numeric statistics unavailable.")


def check(source, cfg, dataset):
    start, stop = dataset["sample_range"]
    channels = dataset["channel_indices"]
    stats = [ChannelStats(i, dataset["channel_ids"][j]) for j, i in enumerate(channels)]
    block_size = source.block_size(cfg["block_samples"])
    for offset in range(start, stop, block_size):
        block = source.read(offset, min(offset+block_size, stop), channels)
        for j, s in enumerate(stats):
            s.feed(block[:, j], offset)
    return dict(coverage=dict(sample_range=[start, stop], channel_indices=channels,
                              complete_requested_range=True, block_samples=block_size),
                channels=[s.result() for s in stats])
