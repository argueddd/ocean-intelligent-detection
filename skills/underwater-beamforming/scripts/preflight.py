#!/usr/bin/env python3
"""Manifest/approval preflight only. No waveform reader or numerical executor."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
import sys

VERSION = "0.2"
MAX_CONFIG_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class Array:
    item: object
    minimum: int = 0
    length: int | None = None


@dataclass(frozen=True)
class Optional:
    item: object


@dataclass(frozen=True)
class Choice:
    values: tuple


STR, NUM, POS, NONNEG, INT, UINT, PINT, BOOL = range(8)
VEC3 = Array(NUM, length=3)
RANGE = Array(UINT, length=2)
IDS = Array(STR, minimum=1)
SOURCE = {"path": STR, "field": STR, "size_bytes": UINT, "mtime_ns": UINT}
INPUT = {
    "source": SOURCE,
    "representation": Choice(("time_waveform_real",)),
    "data_role": Choice(("sensor_array", "single_sensor", "beamformed", "unknown")),
    "axes": Array(STR, length=2),
    "shape": Array(PINT, length=2),
    "dtype": Choice(("int8", "uint8", "int16", "uint16", "int32", "uint32",
                     "int64", "uint64", "float32", "float64")),
    "sample_rate_hz": POS,
    "sample_range": RANGE,
    "channels": IDS,
    "units": STR,
    "time_reference": {"kind": Choice(("relative", "utc")), "origin": STR},
    "processing_history": Array(STR),
}
COORDINATES = {
    "name": STR, "origin": STR, "x_positive": STR,
    "y_positive": STR, "z_positive": STR,
    "handedness": Choice(("right", "left")),
}
GEOMETRY = {
    "channel_ids": IDS, "coordinates_m": Array(VEC3, minimum=2),
    "coordinate_system": COORDINATES, "reference_m": VEC3,
    "model_kind": Choice(("measured", "nominal")), "model_description": STR,
}
PROPAGATION = {"model": Choice(("plane_wave",)), "sound_speed_m_s": POS,
               "source_or_rationale": STR}
SYNC = {"status": Choice(("verified", "assumed", "unknown")), "details": STR}
CALIBRATION = {
    "status": Choice(("calibrated", "uncalibrated", "assumed", "unknown")),
    "handling": Choice(("applied_upstream", "none")), "details": STR,
}
GRID_AXIS = {"start_deg": NUM, "stop_deg": NUM, "step_deg": POS,
             "include_stop": BOOL}
DIRECTION = {
    "mode": Choice(("specified", "grid")),
    "parameterization": Choice(("array_angle", "azimuth_elevation")),
    "angle_unit": Choice(("deg",)), "coordinate_frame": STR,
    "zero_direction": STR, "positive_direction": STR,
    "directions_deg": Optional(Array(Array(NUM, minimum=1), minimum=1)),
    "grid_axes": Optional(Array(GRID_AXIS, minimum=1)),
    "grid_order": Optional(Choice(("first_axis_slowest",))),
}
PROCESSING = {
    "channels": IDS, "band_hz": Array(NONNEG, length=2),
    "preprocessing": Array(Choice(("demean", "linear_detrend"))),
    "precision": Choice(("float32", "float64")),
}
TRANSFORM = {
    "domain": Choice(("stft",)),
    "window": Choice(("hann", "hamming", "boxcar")), "window_periodic": BOOL,
    "window_samples": PINT, "hop_samples": PINT, "nfft": PINT,
    "boundary": Choice(("zeros", "reflect", "no_padding")),
    "synthesis": Choice(("dual_window", "overlap_add")),
    "normalization": Choice(("amplitude_preserving",)),
    "out_of_band": Choice(("zero", "full_band")),
    "time_alignment": Choice(("reference_position",)),
}
CBF = {"element_weights": Array(NUM, minimum=2),
       "normalization": Choice(("unit_response",))}
MVDR = {
    "training": {"mode": Choice(("processing_range", "specified_range")),
                 "sample_range": Optional(RANGE)},
    "covariance_window_frames": PINT, "update_interval_frames": PINT,
    "center_snapshots": BOOL,
    "diagonal_loading": {"mode": Choice(("none", "absolute", "trace_relative")),
                         "value": NONNEG},
    "min_snapshots": PINT, "max_condition_number": POS,
    "failure_policy": Choice(("stop", "mark_invalid")),
    "normalization": Choice(("unit_response",)),
}
OUTPUT = {
    "directory": STR, "format": Choice(("npy",)), "save_time_domain": BOOL,
    "beam_selection": Choice(("all_requested",)),
    "auxiliary_products": Array(Choice(("psd", "time_frequency", "spatial_spectrum",
                                        "frequency_angle", "btr"))),
    "weights": Choice(("save_all", "reproducible_recipe")),
    "max_waveform_bytes": PINT,
}
OUTPUT_V04 = {**OUTPUT, "beam_selection": Choice(("explicit_indices",)),
              "time_domain_beam_indices": Array(UINT)}
HANDOFF = {
    "selected_channels": IDS,
    "unknown_direction_policy": Choice(("allow_anonymous", "require_known")),
    "beam_directions": Optional(Array(STR, minimum=1)),
}
SCHEMAS = {
    "input": INPUT, "geometry": GEOMETRY, "propagation": PROPAGATION,
    "synchronization": SYNC, "calibration": CALIBRATION,
    "algorithms": Array(Choice(("cbf", "mvdr")), minimum=1),
    "direction_plan": DIRECTION, "processing": PROCESSING,
    "transform": TRANSFORM, "cbf": CBF, "mvdr": MVDR,
    "output": OUTPUT, "handoff": HANDOFF,
}
RECORD = {
    "key": STR, "kind": Choice(("fact", "model_assumption", "processing_choice")),
    "status": Choice(("unknown", "proposed", "confirmed", "conflict", "not_applicable")),
    "value_sha256": STR, "scope_sha256": STR, "evidence": STR,
    "confirmation": {"method": Choice(("user", "source")), "reference": STR},
}


def canonical_digest(value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def fingerprints(plan):
    """Hashes are identifiers, not permission or proof of user confirmation."""
    if not isinstance(plan, dict):
        raise ValueError("配置根节点必须是 JSON 对象")
    body = {k: v for k, v in plan.items() if k != "parameter_records"}
    return {"scope_sha256": canonical_digest(body),
            "groups": {k: canonical_digest(v) for k, v in body.items() if k in SCHEMAS}}


def _pairs_no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"重复 JSON 键：{key}")
        result[key] = value
    return result


def load_plan(path):
    path = Path(path)
    with path.open("rb") as handle:
        raw = handle.read(MAX_CONFIG_BYTES + 1)
    if len(raw) > MAX_CONFIG_BYTES:
        raise ValueError("配置超过 2 MiB；检查器不接受过大的配置文件")
    def bad_constant(value):
        raise ValueError(f"JSON 不允许 {value}")
    return json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs_no_duplicates,
                      parse_constant=bad_constant)


def _number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


class Preflight:
    def __init__(self, plan, base_dir):
        self.plan = plan
        self.base = Path(base_dir).resolve()
        self.issues = []
        self._issue_keys = set()
        self.valid = {}
        self.required = []
        self.approved = set()
        self.route = "unresolved"
        self.beams = None
        self.estimate = None
        self.source_check = {"status": "not_checked", "content_hash_verified": False}
        self.digests = None

    def issue(self, code, path, message, severity="needs_input"):
        key = (code, path, message)
        if key not in self._issue_keys:
            self._issue_keys.add(key)
            self.issues.append({"code": code, "path": path, "severity": severity,
                                "message": message})

    def schema(self, value, spec, path):
        if isinstance(spec, Optional):
            spec = spec.item
        if value is None:
            self.issue("MISSING_PARAMETER", path, f"请明确 {path}，不能采用默认值。")
            return False
        before = len(self.issues)
        if isinstance(spec, dict):
            if not isinstance(value, dict):
                self.issue("TYPE_ERROR", path, "必须是对象。", "invalid")
                return False
            for key in sorted(value.keys() - spec.keys()):
                self.issue("UNKNOWN_KEY", f"{path}.{key}", "未知字段，不会忽略或纠正拼写。", "invalid")
            for key, field in spec.items():
                if isinstance(field, Optional) and key not in value:
                    continue
                self.schema(value.get(key), field, f"{path}.{key}")
        elif isinstance(spec, Array):
            if not isinstance(value, list):
                self.issue("TYPE_ERROR", path, "必须是数组。", "invalid")
            else:
                if len(value) < spec.minimum or (spec.length is not None and len(value) != spec.length):
                    self.issue("ARRAY_LENGTH", path, "数组长度不满足接口约定。", "invalid")
                for i, item in enumerate(value):
                    self.schema(item, spec.item, f"{path}[{i}]")
        elif isinstance(spec, Choice):
            if type(value) is not str or value not in spec.values:
                self.issue("UNSUPPORTED_VALUE", path, f"本版可检查的取值为 {list(spec.values)}；不会自动替换。", "unsupported")
        else:
            predicates = {
                STR: lambda v: isinstance(v, str) and bool(v.strip()),
                NUM: _number,
                POS: lambda v: _number(v) and v > 0,
                NONNEG: lambda v: _number(v) and v >= 0,
                INT: lambda v: type(v) is int,
                UINT: lambda v: type(v) is int and v >= 0,
                PINT: lambda v: type(v) is int and v > 0,
                BOOL: lambda v: type(v) is bool,
            }
            if not predicates[spec](value):
                self.issue("INVALID_VALUE", path, "类型、有限性或数值范围不符合约定（布尔值不是数值）。", "invalid")
        return len(self.issues) == before

    def unique(self, values, path):
        if len(set(values)) != len(values):
            self.issue("DUPLICATE_VALUE", path, "存在重复项，不会静默去重。", "invalid")

    def path(self, value):
        path = Path(value).expanduser()
        return (self.base / path).resolve() if not path.is_absolute() else path.resolve()

    def input_checks(self):
        inp = self.plan["input"]
        if inp["axes"] != ["sample", "channel"]:
            self.issue("AXES_NOT_STANDARD", "input.axes", "需要已确认的 [sample, channel] 视图，不猜测或转置。", "unsupported")
        self.unique(inp["channels"], "input.channels")
        n, c = inp["shape"]
        if len(inp["channels"]) != c:
            self.issue("CHANNEL_COUNT", "input.channels", "通道 ID 数量与形状不一致。", "invalid")
        start, stop = inp["sample_range"]
        if not 0 <= start < stop <= n:
            self.issue("SAMPLE_RANGE", "input.sample_range", "样本区间必须非空且位于源范围内。", "invalid")
        role = inp["data_role"]
        if role == "sensor_array" and c < 2:
            self.issue("NOT_AN_ARRAY", "input.data_role", "原始阵列至少需要两个明确的阵元通道。", "invalid")
        if role == "single_sensor" and c != 1:
            self.issue("ROLE_SHAPE_CONFLICT", "input.data_role", "单阵元身份与通道数量冲突。", "invalid")
        if role == "unknown":
            self.issue("UNKNOWN_ROLE", "input.data_role", "请确认这些列是阵元、单阵元还是已形成的波束。")
        source = inp["source"]
        try:
            path = self.path(source["path"])
            if not path.is_file():
                raise ValueError("源路径不是现有普通文件")
            stat = path.stat()
            self.source_check.update({"path": str(path), "status": "metadata_matched",
                                      "size_bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns})
            if stat.st_size != source["size_bytes"] or stat.st_mtime_ns != source["mtime_ns"]:
                self.source_check["status"] = "changed"
                self.issue("SOURCE_CHANGED", "input.source", "源文件大小/修改时间与清单不符；请重新检查并确认。", "invalid")
        except (OSError, ValueError, RuntimeError) as exc:
            self.source_check["status"] = "unavailable"
            self.issue("SOURCE_UNAVAILABLE", "input.source.path", str(exc), "invalid")

    def direction_checks(self):
        d = self.plan["direction_plan"]
        dims = 1 if d["parameterization"] == "array_angle" else 2
        if d["mode"] == "specified":
            if "grid_axes" in d or "grid_order" in d:
                self.issue("MODE_CONFLICT", "direction_plan", "指定方向模式不能同时包含网格配置。", "invalid")
            values = d.get("directions_deg")
            if values is None:
                self.issue("MISSING_DIRECTIONS", "direction_plan.directions_deg", "请给出明确方向。")
                return
            if any(len(row) != dims for row in values):
                self.issue("DIRECTION_DIMENSION", "direction_plan.directions_deg", "方向维数与参数化方式不一致。", "invalid")
                return
            rows = [tuple(row) for row in values]
            self.unique(rows, "direction_plan.directions_deg")
            if dims == 2 and any(not -90 <= row[1] <= 90 for row in values):
                self.issue("ELEVATION_RANGE", "direction_plan.directions_deg", "俯仰角须在 [-90, 90] 度内。", "invalid")
            if dims == 2 and len({(row[0] % 360, row[1]) for row in rows}) != len(rows):
                self.issue("DUPLICATE_DIRECTION", "direction_plan.directions_deg", "存在按 360 度周期重复的方向。", "invalid")
            self.beams = len(values)
        else:
            if "directions_deg" in d:
                self.issue("MODE_CONFLICT", "direction_plan", "网格模式不能同时包含指定方向列表。", "invalid")
            axes = d.get("grid_axes")
            if axes is None or "grid_order" not in d:
                self.issue("MISSING_GRID", "direction_plan", "请明确网格轴、步长、端点和排列顺序。")
                return
            if len(axes) != dims:
                self.issue("GRID_DIMENSION", "direction_plan.grid_axes", "网格轴数量与方向参数化不一致。", "invalid")
                return
            counts = []
            for i, axis in enumerate(axes):
                a, b, step = (Decimal(str(axis[k])) for k in ("start_deg", "stop_deg", "step_deg"))
                if b < a or (a == b and not axis["include_stop"]):
                    self.issue("GRID_RANGE", f"direction_plan.grid_axes[{i}]", "网格必须非空且为升序。", "invalid")
                    continue
                # Decimal avoids silently rounding a requested endpoint onto a grid.
                q = (b - a) / step
                if axis["include_stop"] and q != q.to_integral_value():
                    self.issue("GRID_ENDPOINT", f"direction_plan.grid_axes[{i}]", "终点不落在步长网格上，不能自动四舍五入。", "invalid")
                    continue
                count = int(q) + 1 if axis["include_stop"] else int(q.to_integral_value(rounding="ROUND_CEILING"))
                counts.append(count)
                if dims == 2 and i == 1 and not (-90 <= a <= b <= 90):
                    self.issue("ELEVATION_RANGE", "direction_plan.grid_axes[1]", "俯仰角网格超出 [-90, 90]。", "invalid")
                if dims == 2 and i == 0 and count > 1 and step * (count - 1) >= 360:
                    self.issue("AZIMUTH_WRAP", "direction_plan.grid_axes[0]", "网格跨越完整方位周期，可能重复；请显式重新定义。", "invalid")
            if len(counts) == dims:
                self.beams = math.prod(counts)

    def array_checks(self):
        p = self.plan
        if self.valid.get("algorithms"):
            self.unique(p["algorithms"], "algorithms")
            for name in ("cbf", "mvdr"):
                if name not in p["algorithms"] and name in p:
                    self.issue("UNUSED_ALGORITHM", name, "配置了未选择的算法，请澄清而非静默忽略。", "invalid")
        if self.valid.get("processing"):
            proc = p["processing"]
            self.unique(proc["channels"], "processing.channels")
            self.unique(proc["preprocessing"], "processing.preprocessing")
            if len(proc["channels"]) < 2:
                self.issue("NOT_AN_ARRAY", "processing.channels", "波束形成需至少两个选定阵元。", "invalid")
            lo, hi = proc["band_hz"]
            if lo >= hi:
                self.issue("FREQUENCY_RANGE", "processing.band_hz", "频带必须非空且升序。", "invalid")
            if self.valid.get("input"):
                inp = p["input"]
                if any(ch not in inp["channels"] for ch in proc["channels"]):
                    self.issue("UNKNOWN_CHANNEL", "processing.channels", "所选通道不在输入清单中。", "invalid")
                if hi > inp["sample_rate_hz"] / 2:
                    self.issue("ABOVE_NYQUIST", "processing.band_hz", "频带超过实数采样的 Nyquist 频率。", "invalid")
                positions = [inp["channels"].index(ch) for ch in proc["channels"] if ch in inp["channels"]]
                if positions != sorted(positions):
                    self.issue("CHANNEL_REORDER", "processing.channels", "所选通道不保持源顺序；不能静默重排。", "invalid")
        if self.valid.get("geometry"):
            g = p["geometry"]
            self.unique(g["channel_ids"], "geometry.channel_ids")
            self.unique([tuple(row) for row in g["coordinates_m"]], "geometry.coordinates_m")
            if len(g["channel_ids"]) != len(g["coordinates_m"]):
                self.issue("GEOMETRY_COUNT", "geometry", "坐标数量与阵元 ID 数量不一致。", "invalid")
            if self.valid.get("processing") and g["channel_ids"] != p["processing"]["channels"]:
                self.issue("GEOMETRY_MAPPING", "geometry.channel_ids", "几何行顺序必须与选定阵元完全一致。", "invalid")
        for name in ("synchronization", "calibration"):
            if self.valid.get(name) and p[name]["status"] == "unknown":
                self.issue("UNKNOWN_CONDITION", name, "请说明依据，或明确是否接受带限制的实验假设。")
        if self.valid.get("calibration"):
            c = p["calibration"]
            if c["handling"] == "applied_upstream" and c["status"] != "calibrated":
                self.issue("CALIBRATION_CONFLICT", "calibration", "标定状态与已在上游应用标定的声明冲突。", "invalid")
        if self.valid.get("direction_plan"):
            self.direction_checks()
            if self.valid.get("geometry") and p["direction_plan"]["coordinate_frame"] != p["geometry"]["coordinate_system"]["name"]:
                self.issue("FRAME_MISMATCH", "direction_plan.coordinate_frame", "方向与几何坐标框架不一致；本版不自动变换。", "invalid")
        if self.valid.get("transform"):
            tr = p["transform"]
            if tr["nfft"] < tr["window_samples"] or tr["hop_samples"] > tr["window_samples"]:
                self.issue("TRANSFORM_LENGTH", "transform", "要求 nfft ≥ 窗长且步长不超过窗长。", "invalid")
            if self.valid.get("input") and tr["window_samples"] > p["input"]["sample_range"][1] - p["input"]["sample_range"][0]:
                self.issue("WINDOW_TOO_LONG", "transform.window_samples", "窗口超过请求片段；不能自动改窗长或扩大数据范围。", "invalid")
            if tr["out_of_band"] == "full_band" and self.valid.get("input") and self.valid.get("processing"):
                if p["processing"]["band_hz"] != [0, p["input"]["sample_rate_hz"] / 2]:
                    self.issue("BAND_POLICY_CONFLICT", "transform.out_of_band", "full_band 要求处理频带覆盖 0 至 fs/2。", "invalid")
        if self.valid.get("cbf"):
            weights = p["cbf"]["element_weights"]
            if self.valid.get("processing") and len(weights) != len(p["processing"]["channels"]):
                self.issue("WEIGHT_COUNT", "cbf.element_weights", "阵元权重数量不匹配。", "invalid")
            total = sum(weights)
            if total == 0 or not _number(total):
                self.issue("ZERO_WEIGHT_SUM", "cbf.element_weights", "权重和为零或溢出，不能按指定的单位响应归一化。", "invalid")
        if self.valid.get("mvdr"):
            m = p["mvdr"]
            if m["max_condition_number"] <= 1:
                self.issue("CONDITION_LIMIT", "mvdr.max_condition_number", "条件数上限必须大于 1。", "invalid")
            if m["min_snapshots"] > m["covariance_window_frames"]:
                self.issue("SNAPSHOT_COUNT", "mvdr", "最小快拍数超过协方差窗口帧数。", "invalid")
            load = m["diagonal_loading"]
            if load["mode"] == "none" and load["value"] != 0:
                self.issue("LOADING_CONFLICT", "mvdr.diagonal_loading", "none 与非零加载值冲突。", "invalid")
            if load["mode"] != "none" and load["value"] <= 0:
                self.issue("LOADING_CONFLICT", "mvdr.diagonal_loading", "启用加载时值须为正数；不加载请明确使用 none。", "invalid")
            training = m["training"]
            if training["mode"] == "processing_range" and "sample_range" in training:
                self.issue("TRAINING_CONFLICT", "mvdr.training", "processing_range 不应另给区间。", "invalid")
            if training["mode"] == "specified_range" and "sample_range" not in training:
                self.issue("MISSING_TRAINING_RANGE", "mvdr.training.sample_range", "请明确训练样本范围。")
            if self.valid.get("input") and self.valid.get("transform"):
                interval = training.get("sample_range", p["input"]["sample_range"])
                start, stop = interval
                if not 0 <= start < stop <= p["input"]["shape"][0]:
                    self.issue("TRAINING_RANGE", "mvdr.training", "训练区间越界或为空。", "invalid")
                tr = p["transform"]
                frames = max(0, 1 + (stop - start - tr["window_samples"]) // tr["hop_samples"])
                if frames < m["covariance_window_frames"]:
                    self.issue("INSUFFICIENT_TRAINING_FRAMES", "mvdr.training", "无填充完整帧不足以构成指定协方差窗口，不会自动扩展或缩短。", "invalid")
        if self.valid.get("output"):
            out = p["output"]
            if p.get("schema_version") == "0.4":
                selected = out["time_domain_beam_indices"]
                self.unique(selected, "output.time_domain_beam_indices")
                if self.beams is not None and any(i >= self.beams for i in selected):
                    self.issue("RETAINED_BEAM_RANGE", "output.time_domain_beam_indices", "保留索引不在计算方向中；不会寻找最近方向。", "invalid")
                if out["save_time_domain"] != bool(selected):
                    self.issue("RETENTION_CONFLICT", "output", "save_time_domain 必须与明确保留的索引列表一致；空列表仅表示明确不保存。", "invalid")
            elif not out["save_time_domain"]:
                self.issue("TIME_DOMAIN_REQUIRED", "output.save_time_domain", "本模块主要交付是时域数据，不能只保存图片。", "invalid")
            self.unique(out["auxiliary_products"], "output.auxiliary_products")
            try:
                raw_dest = Path(out["directory"]).expanduser()
                if not raw_dest.is_absolute():
                    raw_dest = self.base / raw_dest
                dest = raw_dest.resolve()
                if raw_dest.is_symlink() or dest.exists():
                    self.issue("OUTPUT_EXISTS", "output.directory", "结果目录必须是新目录，不能覆盖。", "invalid")
            except (OSError, ValueError, RuntimeError) as exc:
                self.issue("OUTPUT_PATH", "output.directory", str(exc), "invalid")
            if all(self.valid.get(k) for k in ("input", "processing", "algorithms")) and self.beams is not None:
                start, stop = p["input"]["sample_range"]
                nbytes = 4 if p["processing"]["precision"] == "float32" else 8
                saved_beams = len(out["time_domain_beam_indices"]) if p.get("schema_version") == "0.4" else self.beams
                self.estimate = (stop - start) * saved_beams * len(p["algorithms"]) * nbytes
                if self.estimate > out["max_waveform_bytes"]:
                    self.issue("OUTPUT_BUDGET", "output.max_waveform_bytes", "预计时域数组大小超出已确认预算；请决定，不能自动缩小任务。")

    def handoff_checks(self):
        if not self.valid.get("handoff"):
            return
        h = self.plan["handoff"]
        self.unique(h["selected_channels"], "handoff.selected_channels")
        if self.valid.get("input"):
            inp = self.plan["input"]
            if any(ch not in inp["channels"] for ch in h["selected_channels"]):
                self.issue("UNKNOWN_CHANNEL", "handoff.selected_channels", "交接通道不在源通道清单中。", "invalid")
            if inp["data_role"] == "beamformed" and h["unknown_direction_policy"] == "require_known":
                directions = h.get("beam_directions")
                if directions is None or len(directions) != len(h["selected_channels"]):
                    self.issue("MISSING_BEAM_METADATA", "handoff.beam_directions", "请补齐选定波束的方向定义，或明确接受匿名波束分析。")

    def approval_checks(self):
        records = self.plan.get("parameter_records")
        if records is None:
            records = []
        if not isinstance(records, list):
            self.issue("TYPE_ERROR", "parameter_records", "确认记录必须为数组。", "invalid")
            records = []
        indexed = {}
        for i, rec in enumerate(records):
            if not self.schema(rec, RECORD, f"parameter_records[{i}]"):
                continue
            key = rec["key"]
            if key not in SCHEMAS or key not in self.plan:
                self.issue("UNKNOWN_APPROVAL_KEY", f"parameter_records[{i}].key", "确认记录指向不存在或未知配置组。", "invalid")
                continue
            if key in indexed:
                self.issue("DUPLICATE_APPROVAL", f"parameter_records[{i}].key", "同一组存在多个确认记录，请解决歧义。", "invalid")
                continue
            indexed[key] = rec
        for key in self.required:
            rec = indexed.get(key)
            if rec is None:
                self.issue("CONFIRMATION_REQUIRED", key, "需要对应配置组的明确确认记录；摘要不是确认。")
                continue
            if rec["status"] == "conflict":
                self.issue("PARAMETER_CONFLICT", key, "记录存在冲突，须由用户明确解决。", "invalid")
                continue
            if rec["status"] != "confirmed":
                self.issue("NOT_CONFIRMED", key, "未知、建议或不适用记录不能代替本组确认。")
                continue
            if rec["scope_sha256"] != self.digests["scope_sha256"] or rec["value_sha256"] != self.digests["groups"].get(key):
                self.issue("STALE_CONFIRMATION", key, "确认记录不匹配当前配置/范围；请重新核对并确认。")
                continue
            # Only pure input facts may cite a source instead of an explicit user decision.
            if rec["confirmation"]["method"] == "source":
                inp = self.plan.get("input", {})
                if key != "input" or rec["kind"] != "fact" or inp.get("units") == "unknown" or "unknown" in inp.get("processing_history", []):
                    self.issue("USER_DECISION_REQUIRED", key, "模型、处理选择或未知信息的使用范围必须由用户明确确认。")
                    continue
            self.approved.add(key)

    def run(self):
        if not isinstance(self.plan, dict):
            self.issue("ROOT_TYPE", "$", "配置根必须为对象。", "invalid")
            return self.result()
        try:
            self.digests = fingerprints(self.plan)
        except (ValueError, TypeError, OverflowError, RecursionError) as exc:
            self.issue("INVALID_JSON_VALUE", "$", str(exc), "invalid")
            return self.result()
        for key in sorted(self.plan.keys() - (SCHEMAS.keys() | {"schema_version", "parameter_records"})):
            self.issue("UNKNOWN_KEY", key, "未知顶层字段，不会忽略。", "invalid")
        if self.plan.get("schema_version") not in ("0.2", "0.4"):
            self.issue("SCHEMA_VERSION", "schema_version", "本检查器要求 schema_version=0.2 或 0.4，不自动转换旧配置。", "invalid")
        self.required = ["input"]
        self.valid["input"] = self.schema(self.plan.get("input"), INPUT, "input")
        inp = self.plan.get("input")
        role = inp.get("data_role") if isinstance(inp, dict) else None
        if role == "sensor_array":
            self.required += ["algorithms", "geometry", "propagation", "synchronization",
                              "calibration", "direction_plan", "processing", "transform", "output"]
            algs = self.plan.get("algorithms")
            if isinstance(algs, list):
                self.required += [a for a in ("cbf", "mvdr") if a in algs]
            if "handoff" in self.plan:
                self.issue("ROUTE_CONFLICT", "handoff", "原始阵列任务不应同时配置已有波束交接。", "invalid")
        elif role in ("single_sensor", "beamformed"):
            self.required += ["handoff"]
            for key in sorted(self.plan.keys() & (SCHEMAS.keys() - {"input", "handoff"})):
                self.issue("ROUTE_CONFLICT", key, "单阵元/已有波束旁路不应包含阵列计算配置。", "invalid")
        for key in (k for k in SCHEMAS if k != "input"):
            if key in self.plan or key in self.required:
                spec = OUTPUT_V04 if key == "output" and self.plan.get("schema_version") == "0.4" else SCHEMAS[key]
                self.valid[key] = self.schema(self.plan.get(key), spec, key)
        if self.valid["input"]:
            self.input_checks()
        if role == "sensor_array":
            self.array_checks()
        elif role in ("single_sensor", "beamformed"):
            self.handoff_checks()
        self.approval_checks()
        if "input" in self.approved and self.valid["input"]:
            self.route = {"sensor_array": "beamforming", "single_sensor": "single_sensor_handoff",
                          "beamformed": "beamformed_handoff"}.get(role, "unresolved")
        return self.result()

    def result(self):
        severities = {issue["severity"] for issue in self.issues}
        status = ("invalid" if "invalid" in severities else "unsupported" if "unsupported" in severities
                  else "needs_input" if severities else "passed")
        parameter_status = "complete" if status == "passed" else "needs_input" if status == "needs_input" else "invalid"
        return {
            "schema_version": VERSION, "preflight_status": status,
            "parameter_status": parameter_status, "route": self.route,
            "implementation_status": {"preflight": "implemented", "cbf": "external_executor_required",
                                      "mvdr": "external_executor_required", "time_reconstruction": "external_executor_required"},
            "execution_status": "not_run", "can_execute": False,
            "execution_blockers": ["本预检查入口不执行计算或复制；阵列计算使用 execute.py，检查导出后的旁路交接使用 bypass_handoff.py，均须独立确认。"],
            "handoff_status": "blocked" if self.route.endswith("_handoff") else "not_requested",
            "handoff_execution_status": "not_run",
            "handoff_manifest_ready": status == "passed" and self.route.endswith("_handoff"),
            "issues": self.issues,
            "questions": [i for i in self.issues if i["severity"] == "needs_input"],
            "configuration_fingerprints": self.digests,
            "required_confirmation_groups": self.required,
            "confirmed_groups": sorted(self.approved), "source_check": self.source_check,
            "planned_beam_count": self.beams,
            "estimated_waveform_payload_bytes": self.estimate,
            "estimate_excludes": ["NPY 文件头", "权重", "辅助产物", "内存和临时工作空间"],
            "not_checked": ["波形内容、真实格式/轴/类型", "NaN/Inf、削波及采集缺口",
                            "实测同步、标定与阵列几何真实性", "确认记录来源的真实性",
                            "窗函数可逆性、协方差数值条件和波束形成效果",
                            "实际存储空间及写权限", "下游接口联调"],
            "artifacts": [],
        }


def check_plan(plan, base_dir="."):
    """Read only filesystem metadata; never read samples, change plan or run algorithms."""
    checker = Preflight(plan, base_dir)
    try:
        return checker.run()
    except (ValueError, TypeError, OverflowError, RecursionError, InvalidOperation) as exc:
        checker.issue("INVALID_CONFIGURATION", "$", str(exc), "invalid")
        return checker.result()


def require_executable(report):
    """Legacy metadata reports are never numerical-execution authorization tokens."""
    raise RuntimeError("本预检查报告不是数值计算授权；请使用 execute.py 的独立门禁。")


def markdown_report(report):
    lines = ["# 波束形成计算前检查", "", f"预检查状态：{report['preflight_status']}",
             f"参数状态：{report['parameter_status']}", f"分流：{report['route']}",
             "", "本次未执行波束形成或线谱检测。通过只代表本检查器覆盖的配置检查通过。",
             "", "## 问题与待确认项", ""]
    if not report["issues"]:
        lines.append("未发现本检查器覆盖的配置问题；数值执行另须通过 execute.py 门禁。")
    for item in report["issues"]:
        path = item["path"].replace("\n", " ")
        message = item["message"].replace("\n", " ")
        lines.append(f"- [{item['code']}] {path}：{message}")
    lines += ["", "## 检查边界", ""] + [f"- 未验证：{x}" for x in report["not_checked"]]
    if report["planned_beam_count"] is not None:
        lines += ["", f"计划波束数：{report['planned_beam_count']}（未生成信号）"]
    if report["estimated_waveform_payload_bytes"] is not None:
        lines.append(f"时域数组净数据量估计：{report['estimated_waveform_payload_bytes']} 字节；不含权重、文件头或工作空间。")
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("check", "digests"):
        child = sub.add_parser(command)
        child.add_argument("config", type=Path)
        if command == "check":
            child.add_argument("--out", type=Path, help="新目录，仅保存预检查报告，不创建算法结果")
    args = parser.parse_args(argv)
    try:
        plan = load_plan(args.config)
        if args.command == "digests":
            print(json.dumps(fingerprints(plan), ensure_ascii=False, indent=2, allow_nan=False))
            return 0
        report = check_plan(plan, args.config.resolve().parent)
        if args.out is not None:
            if isinstance(plan, dict) and isinstance(plan.get("output"), dict):
                target = plan["output"].get("directory")
                if isinstance(target, str) and target.strip():
                    future = Path(target).expanduser()
                    if not future.is_absolute():
                        future = args.config.resolve().parent / future
                    future = future.resolve()
                    report_dir = args.out.resolve()
                    if report_dir == future or future in report_dir.parents:
                        raise ValueError("预检查报告目录不能占用未来算法结果目录或其子目录")
            # Exclusive directory creation prevents overwriting an existing result or symlink.
            args.out.mkdir(parents=True, exist_ok=False)
            with (args.out / "preflight.json").open("x", encoding="utf-8") as handle:
                json.dump(report, handle, ensure_ascii=False, indent=2, allow_nan=False)
                handle.write("\n")
            with (args.out / "report.md").open("x", encoding="utf-8") as handle:
                handle.write(markdown_report(report))
        print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
        return 0 if report["preflight_status"] == "passed" else 2 if report["preflight_status"] == "needs_input" else 1
    except (OSError, ValueError, TypeError, OverflowError, RecursionError, InvalidOperation) as exc:
        print(json.dumps({"preflight_status": "invalid", "can_execute": False,
                          "execution_status": "not_run", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
