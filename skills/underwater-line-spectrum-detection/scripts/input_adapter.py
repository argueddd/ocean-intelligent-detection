#!/usr/bin/env python3
"""Readonly handoff -> SignalInput mapping. No detector, FFT, repair or authorization."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

import validate_contract as contracts

VERSION = "0.1.0"
MAX_JSON = 32 * 1024**2
KINDS = {"beamformed_handoff": ("handoff_version", "confirmed_handoff_request.json", "receive"),
         "bypass_handoff": ("bypass_version", "confirmed_bypass_request.json", "receive-bypass")}


def require(value, message):
    if not value:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def parse(raw):
    value = json.loads(raw, object_pairs_hook=contracts._pairs, parse_constant=contracts._constant)
    contracts._finite(value)
    return value


def signature(st):
    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)


def packet_open(root, name):
    """Reject symlinks and traversal in every package-relative component."""
    require(isinstance(name, str) and name and "\\" not in name, "Invalid package path.")
    parts = name.split("/")
    require(not any(p in ("", ".", "..") for p in parts) and ":" not in parts[0],
            "Package path must be relative, without dot/parent/drive components.")
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            os.close(fd)
            raise ValueError("Only regular package files are supported.")
        return os.fdopen(fd, "rb")
    finally:
        os.close(directory)


def read_json(root, name):
    with packet_open(root, name) as handle:
        before = os.fstat(handle.fileno())
        require(before.st_size <= MAX_JSON, "JSON exceeds 32 MiB.")
        raw = handle.read(MAX_JSON + 1)
        require(len(raw) <= MAX_JSON and signature(before) == signature(os.fstat(handle.fileno())),
                "JSON changed or exceeded its limit during read.")
    return parse(raw), hashlib.sha256(raw).hexdigest(), signature(before)


def file_reference(name, sha):
    return {"location": {"kind": "package_relative", "path": name},
            "sha256": sha, "availability": "available"}


def run_receiver(path, sha, command):
    """Separate interpreter avoids beam/line preflight module-name collision."""
    script = Path(__file__).with_name("beamformed_input.py").resolve()
    completed = subprocess.run([sys.executable, "-B", str(script), command, str(path), "--sha256", sha],
                               cwd=script.parent, capture_output=True, timeout=60)
    require(completed.returncode == 0,
            "Upstream receiver rejected the packet: " +
            completed.stdout.decode("utf-8", errors="replace")[:4000] +
            completed.stderr.decode("utf-8", errors="replace")[:2000])
    result = parse(completed.stdout)
    require(result.get("input_status") == "accepted" and result.get("can_detect") is False and
            result.get("detection_status") == "not_run" and
            result.get("handoff", {}).get("sha256") == sha,
            "Receiver did not return the expected data-only acceptance.")
    return result


class Packet:
    def __init__(self, path, sha, kind, max_package_bytes, max_block_samples):
        require(kind in KINDS, "Explicit supported package_kind is required.")
        require(isinstance(sha, str) and re.fullmatch("[a-f0-9]{64}", sha), "Pinned SHA256 required.")
        require(type(max_package_bytes) is int and max_package_bytes > 0 and
                type(max_block_samples) is int and max_block_samples > 0, "Explicit positive limits required.")
        path = Path(path).absolute()
        self.root = path.parent.resolve(strict=True)
        self.path = self.root / path.name
        self.manifest, actual, snap = read_json(self.root, path.name)
        require(actual == sha, "Handoff SHA256 mismatch.")
        self.sha, self.kind = sha, kind
        version_key, request_name, command = KINDS[kind]
        m = self.manifest
        require(isinstance(m, dict) and m.get(version_key) == "0.1", "Unsupported handoff kind/version.")
        require(m.get("dtype") == "float64", "Handoff dtype conflicts with supported float64 contract.")
        require(m.get("detection_status") == "not_run" and m.get("can_detect") is False,
                "Only data-only packets with unchanged historical detection status are supported.")
        self.snapshots = {path.name: snap}
        self.index = {}
        self.bytes = snap[2]
        require(isinstance(m.get("artifacts"), list), "Missing package artifact list.")
        for item in m["artifacts"]:
            name = item["path"]
            require(name not in self.index and name != path.name, "Duplicate or self-referencing artifact.")
            require(type(item.get("size_bytes")) is int and item["size_bytes"] > 0 and
                    isinstance(item.get("sha256"), str) and re.fullmatch("[a-f0-9]{64}", item["sha256"]),
                    "Invalid artifact size/hash.")
            with packet_open(self.root, name) as handle:
                st = os.fstat(handle.fileno())
                require(st.st_size == item["size_bytes"], "Artifact size mismatch: " + name)
                self.snapshots[name] = signature(st)
            self.bytes += st.st_size
            require(self.bytes <= max_package_bytes, "Package byte limit exceeded; no partial acceptance.")
            self.index[name] = item
        require(self.bytes <= max_package_bytes, "Package byte limit exceeded.")
        require(request_name in self.index, "Missing fixed receiver request.")
        request, request_sha, _ = read_json(self.root, request_name)
        require(request_sha == self.index[request_name]["sha256"], "Request SHA256 mismatch.")
        block = request["output"]["block_samples"]
        require(type(block) is int and 0 < block <= max_block_samples,
                "Receiver block_samples invalid or exceeds explicit limit; do not rewrite the old request.")
        self.receiver = run_receiver(self.path, sha, command)
        self.unchanged()

    def ref(self, name):
        if name == self.path.name:
            return file_reference(name, self.sha)
        require(name in self.index, "Reference not registered in handoff: " + str(name))
        return file_reference(name, self.index[name]["sha256"])

    def unchanged(self):
        for name, expected in self.snapshots.items():
            with packet_open(self.root, name) as handle:
                require(signature(os.fstat(handle.fileno())) == expected, "Package changed during adaptation: " + name)
        _, sha, _ = read_json(self.root, self.path.name)
        require(sha == self.sha, "Handoff changed during adaptation.")


def map_input(packet, signal_id):
    m, p = packet.manifest, packet.manifest["provenance"]
    require(isinstance(signal_id, str) and signal_id.strip(), "Explicit signal_id required.")
    matches = [(i, s) for i, s in enumerate(m["signals"]) if s["signal_id"] == signal_id]
    require(len(matches) == 1, "signal_id must identify exactly one handed-off signal; no automatic selection.")
    i, s = matches[0]
    main = packet.kind == "beamformed_handoff"
    manifest_ref = packet.ref(packet.path.name)
    evidence_base = "sha256:" + packet.sha + "#"
    source_map = {}
    unknowns = []

    def evidence(pointer):
        return evidence_base + pointer

    def bind(field, pointers, rule="copy verified source value"):
        source_map[field] = {"source_pointers": [evidence(x) for x in pointers], "rule": rule}

    def unknown(field, why, question):
        unknowns.append({"field": field, "reason": why, "question": question,
                         "affected_actions": ["dependent_detection_or_association"]})

    def status(value, state, pointer):
        return {"status": state, "value": value, "evidence": evidence(pointer)}

    base = "/signals/" + str(i)
    config_name = "source_config.json" if main else m["source_configuration"]
    original = p.get("original_source_sample_range")
    if original is None:
        unknown("/payload/time_mapping/source_sample_zero", "No explicit original source sample range.",
                "需要回到原始样本索引时，请补充映射；不能用中间文件索引代替。")
    time = {"sample_zero_offset_seconds": p["first_sample_offset_seconds"],
            "time_reference": canonical(p["time_reference"]),
            "source_sample_zero": original[0] if original is not None else None,
            "evidence": evidence("/provenance")}

    if main:
        validity = {"status": "known", "sample_intervals": p["valid_sample_intervals"],
                    "mask_ref": packet.ref(m["valid_sample_mask"]),
                    "meaning": canonical({"interval_convention": p["interval_convention"],
                                          "validity_limit": p["validity_limit"]}),
                    "evidence": evidence("/provenance/valid_sample_intervals")}
        coverage = {"status": "known", "band_hz": p["frequency_coverage"]["requested_band_hz"],
                    "active_frequency_ref": manifest_ref,
                    "definition": "band_hz is requested_band_hz, not a continuous ideal passband. Exact active bins: "
                                  "/provenance/frequency_coverage/actual_bin_centers_hz in active_frequency_ref.",
                    "evidence": evidence("/provenance/frequency_coverage")}
        direction = {k: p["direction_plan"][k] for k in (
            "parameterization", "angle_unit", "coordinate_frame", "zero_direction", "positive_direction")}
        direction.update(angles_deg=s["direction_deg"], fixed_direction=s["fixed_direction"])
        beam = {"status": "applicable",
                "beamformer_algorithm": status(s["algorithm"], "known", base + "/algorithm"),
                "beam_id": status(s["beam_id"], "known", base + "/beam_id"),
                "direction": status(direction, "known", "/provenance/direction_plan"),
                "source_result": packet.ref("source_result.json"),
                "source_column": s["source_column"], "scan_column": s["scan_column"]}
    else:
        valid = p["validity"]
        validity = {"status": valid["status"], "sample_intervals": valid["sample_intervals"],
                    "mask_ref": packet.ref(m["valid_sample_mask"]) if m["valid_sample_mask"] is not None else None,
                    "meaning": canonical({"interval_convention": p["interval_convention"],
                                          "upstream_validity": valid}),
                    "evidence": evidence("/provenance/validity")}
        band = p["frequency_coverage"]
        coverage = {"status": band["status"], "band_hz": band["band_hz"], "active_frequency_ref": None,
                    "definition": "Copied bypass frequency coverage; no discrete active-bin list supplied.",
                    "evidence": evidence("/provenance/frequency_coverage")}
        beam = {"status": "not_applicable"}
        if m["data_role"] == "beamformed":
            beam = {"status": "applicable",
                    "beamformer_algorithm": status(s["algorithm"], s["algorithm_status"], base + "/algorithm"),
                    "beam_id": status(None, "unknown", base + "/channel_id"),
                    "direction": status(s["direction"], s["direction_status"], base + "/direction"),
                    "source_result": None, "source_column": s["source_column"], "scan_column": None}
            unknown("/payload/beam_source/beam_id", "Bypass channel_id is not an authenticated upstream beam_id.",
                    "需要跨包波束对应时，请提供原波束身份；不能把通道标签冒充原 beam_id。")
            for key in ("beamformer_algorithm", "direction"):
                if beam[key]["status"] == "unknown":
                    unknown("/payload/beam_source/" + key, "Upstream explicitly records unknown.",
                            "涉及此信息的检测或方向比较应如何处理？请先明确，不补默认值。")
    for key, val in (("validity", validity), ("frequency_coverage", coverage)):
        if val["status"] == "unknown":
            unknown("/payload/" + key, "Upstream explicitly records unknown.",
                    "依赖此信息的计算要采用什么处理决定？确认前不计算，不将未知改成已知。")

    units_known = p["units"] != "unknown"
    units = {"status": "known" if units_known else "unknown", "value": p["units"] if units_known else None,
             "amplitude_convention": p["amplitude_convention"], "evidence": evidence("/provenance/units")}
    if not units_known:
        unknown("/payload/units", "Upstream units are unknown.", "是否仅做不依赖绝对单位的工作？不能标为 Pa 或声压级。")

    history = p["processing_history"]
    steps = [section + "[" + str(j) + "]:" + canonical(step)
             for section in ("upstream", "this_run") for j, step in enumerate(history[section])]
    limits = []
    for parent, obj, names in (("", m, ("limits", "transformations", "source_verification_scope")),
                              ("/provenance", p, ("limitations", "validation_status", "validity_limit",
                               "upstream_inspection", "limitations_acknowledgement", "unknown_metadata_policy"))):
        for name in names:
            if name in obj:
                limits.append(parent + "/" + name + ":" + canonical(obj[name]))
    limits += ["Adapter verifies package consistency, not physical truth, calibration, synchronization or target identity.",
               "Relative references are anchored at the explicitly supplied handoff packet directory.",
               "Original source paths in evidence are not opened or asserted available."]
    for item in unknowns:
        limits.append(item["field"] + ":" + item["reason"])

    refs = [manifest_ref]
    # Complete metadata objects remain inspectable; do not flatten away evidence.
    for name in sorted(packet.index):
        if name.endswith(".json"):
            refs.append(packet.ref(name))
    payload = {"source_package": {"manifest": manifest_ref, "package_kind": packet.kind,
                                 "contract_version": m[KINDS[packet.kind][0]]},
               "signal_id": s["signal_id"], "data_role": m["data_role"],
               "waveform": {"file_ref": packet.ref(s["path"]), "dtype": "float64",
                            "shape": s["shape"], "axes": ["sample", "signal"], "sample_count": s["shape"][0]},
               "sample_rate_hz": p["sample_rate_hz"], "time_mapping": time,
               "validity": validity, "units": units, "frequency_coverage": coverage,
               "processing_history": {"steps": steps, "source_configuration": packet.ref(config_name)},
               "beam_source": beam, "limitations": limits, "provenance": refs}
    bind("/payload/source_package", ["/" + KINDS[packet.kind][0]], "explicit kind + pinned original manifest; no migration")
    bind("/payload/signal_id", [base + "/signal_id"])
    bind("/payload/data_role", ["/data_role"])
    bind("/payload/waveform", [base, "/artifacts"], "verified float64 [N,1]; semantic axis label only, no data transformation")
    for field in ("sample_rate_hz", "validity", "units", "frequency_coverage", "processing_history"):
        pointer = "/provenance/" + ("valid_sample_intervals" if field == "validity" and main else field)
        bind("/payload/" + field, [pointer], "copy state/value; indexed canonical JSON preserves structured evidence")
    bind("/payload/time_mapping", ["/provenance/time_reference", "/provenance/first_sample_offset_seconds",
                                  "/provenance/original_source_sample_range"],
         "canonical JSON time reference; absent original range remains unknown, no intermediate-index fallback")
    bind("/payload/beam_source", [base, "/provenance/direction_plan"] if main else [base],
         "preserve algorithm/direction/columns; bypass does not fabricate beam_id, scan_column or source_result")
    bind("/payload/limitations", ["/limits", "/provenance"], "preserve restrictions and explicit adapter boundaries")
    bind("/payload/provenance", ["/artifacts"], "pinned manifest plus all verified JSON artifacts, not external originals")
    doc = {"schema_version": "0.1.0", "record_type": "SignalInput", "document_status": "specified",
           "payload": payload, "unresolved_items": []}
    checked = contracts.validate_document(doc, "SignalInput")
    require(checked["valid"], "Mapped source does not satisfy SignalInput; no repair: " + str(checked["errors"][:10]))
    return doc, source_map, unknowns


def adapt(path, sha, kind, signal_id, *, max_package_bytes, max_block_samples):
    packet = Packet(path, sha, kind, max_package_bytes, max_block_samples)
    document, mapping, unknowns = map_input(packet, signal_id)
    packet.unchanged()
    return {"adapter_version": VERSION, "adapter_status": "verified", "can_execute": False,
            "detection_status": "not_run", "authority_verified": False, "signal_input": document,
            "field_mapping": mapping, "unknown_items": unknowns,
            "verified_package_bytes": packet.bytes,
            "checked_scope": "whole_handoff_receiver_checks_then_one_explicit_signal_mapping",
            "limitations": ["This is not detection readiness or scientific acceptance.",
                            "No immutable snapshot or authenticated user-consent guarantee.",
                            "Byte limit covers unique package files, not repeated I/O or OS peak memory."],
            "package_snapshots": {k: list(v) for k, v in packet.snapshots.items()}}


def differences(expected, actual, path=""):
    """Compare every field, including unknown states, evidence, ordering and envelope."""
    result = []
    if isinstance(expected, dict) and isinstance(actual, dict):
        for key in sorted(set(expected) | set(actual)):
            pointer = path + "/" + key.replace("~", "~0").replace("/", "~1")
            if key not in expected or key not in actual:
                result.append({"field": pointer, "reason": "missing_or_extra_field"})
            else:
                result.extend(differences(expected[key], actual[key], pointer))
    elif isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            result.append({"field": path, "reason": "list_length_mismatch"})
        for i, (a, b) in enumerate(zip(expected, actual)):
            result.extend(differences(a, b, path + "/" + str(i)))
    elif (type(expected) is bool) != (type(actual) is bool) or expected != actual:
        result.append({"field": path, "reason": "source_value_mismatch", "expected": expected, "actual": actual})
    return result


def check_document(document, handoff, *, max_package_bytes, max_block_samples):
    checked = contracts.validate_document(document, "SignalInput")
    require(checked["valid"] and document["document_status"] == "specified", "Specified valid SignalInput required.")
    p = document["payload"]
    result = adapt(handoff, p["source_package"]["manifest"]["sha256"], p["source_package"]["package_kind"],
                   p["signal_id"], max_package_bytes=max_package_bytes, max_block_samples=max_block_samples)
    diffs = differences(result.pop("signal_input"), document)
    result.update(adapter_status="mismatch" if diffs else "verified", differences=diffs)
    return result


def write_input(document, output, handoff):
    output = Path(output).absolute()
    parent = output.parent.resolve(strict=True)
    root = Path(handoff).absolute().parent.resolve(strict=True)
    require(parent != root and root not in parent.parents, "Output must be outside the readonly handoff directory.")
    with (parent / output.name).open("x", encoding="utf-8") as handle:
        json.dump(document, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("adapt", "check"):
        sub = commands.add_parser(name)
        sub.add_argument("--handoff", required=True, type=Path)
        sub.add_argument("--max-package-bytes", required=True, type=int)
        sub.add_argument("--max-block-samples", required=True, type=int)
        if name == "adapt":
            sub.add_argument("--sha256", required=True)
            sub.add_argument("--kind", choices=tuple(KINDS), required=True)
            sub.add_argument("--signal-id", required=True)
            sub.add_argument("--out", type=Path)
        else:
            sub.add_argument("input", type=Path)
    args = parser.parse_args()
    try:
        options = {"max_package_bytes": args.max_package_bytes, "max_block_samples": args.max_block_samples}
        if args.command == "adapt":
            report = adapt(args.handoff, args.sha256, args.kind, args.signal_id, **options)
            if args.out:
                write_input(report["signal_input"], args.out, args.handoff)
                report["saved_input"] = str(args.out.absolute())
        else:
            doc, sha, _ = read_json(args.input.absolute().parent.resolve(strict=True), args.input.name)
            report = check_document(doc, args.handoff, **options)
            _, after, _ = read_json(args.input.absolute().parent.resolve(strict=True), args.input.name)
            require(sha == after, "SignalInput changed during verification.")
        print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
        return 0 if report["adapter_status"] == "verified" else 1
    except Exception as exc:
        print(json.dumps({"adapter_status": "blocked", "can_execute": False, "detection_status": "not_run",
                          "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    sys.exit(main())
