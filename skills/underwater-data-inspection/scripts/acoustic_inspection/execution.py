"""CLI preparation over the public pipeline; no waveform or metadata inference."""
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import uuid

from .pipeline import clean, execute, exit_code, validate_config
from .readers import InputRequired, probe

EXTENSIONS = {".npy", ".npz", ".mat", ".h5", ".hdf5", ".wav", ".sio"}


def volume_name(value):
    return re.sub(r"[\s_-]+", "", value.casefold())


def resolve_input(value, volumes=Path("/Volumes")):
    """Prefer real paths; a missing absolute mount alias must match exactly once."""
    original = str(value)
    requested = Path(value).expanduser()
    if requested.exists():
        return requested.resolve(strict=True), dict(requested=original,
            resolved=str(requested.resolve(strict=True)), method="existing_path")
    matches = []
    if requested.is_absolute() and len(requested.parts) >= 2 and volumes.is_dir():
        alias = requested.parts[1]
        for mount in volumes.iterdir():
            if mount.is_dir() and volume_name(mount.name) == volume_name(alias):
                candidate = mount.joinpath(*requested.parts[2:])
                if candidate.exists():
                    matches.append(candidate.resolve(strict=True))
    matches = sorted(set(matches))
    if len(matches) != 1:
        raise InputRequired("ambiguous_input_path" if matches else "input_path_not_found",
            f"Cannot resolve input path {original!r}; matching existing paths: {[str(p) for p in matches]}.")
    return matches[0], dict(requested=original, resolved=str(matches[0]),
                            method="unique_volume_alias")


def select_file(directory, relative):
    selection = Path(relative)
    if selection.is_absolute():
        raise InputRequired("invalid_file_selection", "--file must be relative to the input directory.")
    try:
        target = (directory/selection).resolve(strict=True)
    except OSError as e:
        raise InputRequired("file_selection_not_found", f"Selected file does not exist: {relative}.") from e
    if not target.is_relative_to(directory):
        raise InputRequired("invalid_file_selection", "--file escapes the input directory, including through a symbolic link.")
    if not target.is_file():
        raise InputRequired("invalid_file_selection", "--file must identify a regular data file.")
    return target


def directory_inventory(directory):
    """Inspect headers in this directory and its conventional Data child only."""
    folders = [directory] + sorted(p for p in directory.iterdir()
        if p.is_dir() and p.name.casefold() == "data" and p.resolve().is_relative_to(directory))
    files = sorted({p for folder in folders for p in folder.iterdir()
                    if p.is_file() and p.suffix.casefold() in EXTENSIONS})
    candidates = []
    for p in files[:100]:
        item = dict(file=str(p.relative_to(directory)))
        if not p.resolve().is_relative_to(directory):
            item.update(status="blocked", issue="Data link escapes the selected directory.")
        else:
            try:
                info = probe(p)
                item.update(status="structure_probed", format=info["format"], fields=info["fields"])
            except (InputRequired, OSError, ValueError) as e:
                item.update(status="blocked", issue=str(e), code=getattr(e, "code", type(e).__name__))
        candidates.append(item)
    configs = sorted(str(p.relative_to(directory)) for p in directory.iterdir()
                     if p.is_file() and p.suffix.casefold() == ".json")
    return dict(candidates=candidates, configuration_files=configs,
        inventory_scope="input directory and immediate Data child; headers only",
        candidate_count=len(files), candidates_truncated=len(files) > 100,
        sample_checks_performed=False)


def explicit_config_path(value, directory):
    requested = Path(value).expanduser()
    options = [requested] if requested.is_absolute() else [Path.cwd()/requested, directory/requested]
    matches = sorted({p.resolve(strict=True) for p in options if p.is_file()})
    if len(matches) != 1:
        raise InputRequired("ambiguous_config_path" if matches else "config_path_not_found",
            f"Explicit configuration {str(value)!r} has {len(matches)} matching files: {[str(p) for p in matches]}.")
    return matches[0]


def summary_for_stdout(output):
    """The stored summary stays portable; stdout links identify actual artifacts."""
    text = (output/"summary.md").read_text(encoding="utf-8")
    def target(match):
        value = match.group(1)
        if value.startswith(("http://", "https://", "#", "/")):
            return match.group(0)
        path = str((output/value).resolve())
        return f"](<{path}>)" if " " in path else f"]({path})"
    return re.sub(r"\]\(([^)]+)\)", target, text)


def numeric_summary(result):
    """Summarize already computed channel statistics, retaining unavailable values."""
    if result.get("results_valid") is False:
        return dict(status="invalidated")
    quality = result.get("quality")
    if not quality or not quality.get("channels"):
        return dict(status="not_run")
    rows = clean(quality["channels"])
    missing = {}
    def values(key, nested=False):
        found = []
        for row in rows:
            value = row.get(key)
            if nested:
                value = value.get("length") if isinstance(value, dict) else None
            if type(value) in (int, float) and math.isfinite(value):
                found.append(value)
            else:
                missing.setdefault(key, []).append(row.get("channel_index"))
        return found

    def total(key):
        found = values(key)
        return sum(found) if len(found) == len(rows) else None

    def span(key):
        found = values(key)
        return [min(found), max(found)] if found else None

    def longest(key):
        found = values(key, nested=True)
        return max(found) if len(found) == len(rows) else None

    summary = dict(status="computed", channel_count=len(rows),
        coverage=quality.get("coverage"),
        sample_count_total=total("sample_count"),
        finite_count_total=total("finite_count"),
        zero_count_total=total("zero_count"),
        nan_count_total=total("nan_count"),
        positive_inf_count_total=total("positive_inf_count"),
        negative_inf_count_total=total("negative_inf_count"),
        mean_range=span("mean"), std_population_range=span("std_population"),
        rms_range=span("rms"), minimum_range=span("minimum"), maximum_range=span("maximum"),
        longest_constant_run_max_samples=longest("longest_constant_run"),
        longest_zero_run_max_samples=longest("longest_zero_run"))
    std = summary["std_population_range"]
    ratio = std[1]/std[0] if std and std[0] > 0 and "std_population" not in missing else None
    summary["std_max_min_ratio"] = ratio if ratio is not None and math.isfinite(ratio) else None
    summary["unavailable_channel_fields"] = missing
    return summary


def existing_figure_paths(output, result):
    """Return every declared figure that exists, without listing or analyzing data."""
    names = result.get("analysis", {}).get("artifacts", [])
    extensions = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
    paths = []
    for name in names:
        path = (output/name).resolve()
        if path.suffix.casefold() in extensions and path.is_relative_to(output) and path.is_file():
            if str(path) not in paths:
                paths.append(str(path))
    return paths


def execute_request(args, parse_json):
    resolution = None
    try:
        selected, resolution = resolve_input(args.file)
        directory = selected if selected.is_dir() else selected.parent
        if selected.is_dir():
            if args.selected_file is None:
                return dict(status="needs_input", path_resolution=resolution,
                    issue="Select a relative --file; directory discovery has not checked waveform samples.",
                    **directory_inventory(selected)), 2
            selected = select_file(selected, args.selected_file)
        elif args.selected_file is not None:
            raise InputRequired("invalid_file_selection", "--file is only valid with a directory input.")
        if not selected.is_file():
            raise InputRequired("invalid_input", "Input must be a regular file or directory.")
        if args.config:
            config_path = explicit_config_path(args.config, directory)
            config = parse_json(config_path.read_text(encoding="utf-8"))
            config_source = str(config_path)
        elif args.config_json is not None:
            config = parse_json(args.config_json)
            config_source = "explicit CLI --config-json supplied for this request"
        else:
            raise InputRequired("config_required", "Supply --config or --config-json; no discovered configuration is applied automatically.")
        validate_config(config)
        output = (args.out if args.out is not None else Path.cwd()/".run"/
            ("inspection-"+datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")+"-"+uuid.uuid4().hex[:8])).resolve()
        result = execute(selected, output, config, config_source=config_source)
        resolution["selected_file"] = str(selected)
        result["input_resolution"] = resolution
        # Keep the path transformation alongside the existing numeric evidence.
        (output/"result.json").write_text(json.dumps(clean(result), ensure_ascii=False,
            indent=2, allow_nan=False)+"\n", encoding="utf-8")
        return dict(status=result["status"], path_resolution=resolution,
            result=str(output/"result.json"), summary_file=str(output/"summary.md"),
            summary=summary_for_stdout(output), numeric_summary=numeric_summary(result),
            figure_paths=existing_figure_paths(output, result), issues=result["issues"]), exit_code(result)
    except InputRequired as e:
        return dict(status="needs_input", path_resolution=resolution,
                    issues=[dict(code=e.code, message=str(e))]), 2
    except (OSError, ValueError) as e:
        return dict(status="failed", path_resolution=resolution,
                    error=str(e)), 1
