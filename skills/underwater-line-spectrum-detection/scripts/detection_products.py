"""Public result mapping and opt-in in-memory products. No file writes here."""
import hashlib
import html
import io
import json
import numpy as np
from cfar_registry import envelope, VERSION, PRODUCTS


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()


def reference(name, raw, *, saved=True):
    return {"location": {"kind": "package_relative" if saved else "external_reference", "path": name},
            "sha256": hashlib.sha256(raw).hexdigest(), "availability": "available"}


def quality():
    return {"status": "not_evaluated", "summary": "Detection execution, not target truth or performance acceptance.",
            "evidence_refs": []}


def measurement(name, value, unit, definition):
    return {"name": name, "definition_id": "cfar-v1/" + name, "definition_version": VERSION,
            "value": float(value), "unit": unit, "scale": "linear", "interpretation": definition,
            "probability_meaning": "not_probability", "calibration_evidence": None}


def public_task(task, inp, output):
    units = inp["units"]
    unit = f"({units['value']})^2/Hz" if units["status"] == "known" else "unknown_input_unit_squared/Hz"
    candidates = []
    for i, v in enumerate(output["candidates"]):
        candidates.append({"candidate_id": f"candidate_{hashlib.sha256(task['task_id'].encode()).hexdigest()[:16]}_{i:08d}", "task_id": task["task_id"],
            "input_ref": task["input_ref"],
            "frequency": {"kind": "point", "value_hz": v["frequency_hz"],
                "estimation_definition": "Highest PSD bin in contiguous exceedance group; ties choose lower frequency.",
                "grid_index": v["bin"]},
            "analysis_support": {"sample_intervals": v["sample_intervals"], "time_reference": task["scope"]["time_reference"]},
            "event_extent": {"status": "not_estimated", "interval_seconds": None, "definition": None},
            "decision": {"summary": "Strict PSD > alpha*background; retained by explicitly selected group filters.",
                         "evidence_refs": []},
            "measurements": [measurement(name, v[name], unit if name in ("power", "background", "threshold") else
                    ("Hz" if name == "group_width_hz" else "dimensionless"), definition)
                for name, definition in (("power", "One-sided PSD at selected FFT bin."),
                    ("background", "CA reference mean or one-based OS reference statistic, not physical noise truth."),
                    ("threshold", "alpha times background, in PSD units."),
                    ("ratio", "PSD/background statistic, not calibrated SNR or probability."),
                    ("group_width_hz", "Number of contiguous above-threshold bins times bin spacing, not physical linewidth."))],
            "quality_flags": ["not_target_truth", "nearby_lines_may_merge"] + (
                ["validity_unverified"] if inp["validity"]["status"] != "known" else []),
            "extensions": {"cfar_v1": {k: v[k] for k in ("row", "group_bins", "tied_maximum_bins",
                                                        "plateau_extent_bins", "plateau_is_contiguous")}}})
    limitations = ["No target identification, tracking, truth matching or performance acceptance.",
        "No joint event-probability guarantee across tasks, signals or algorithms.",
        "Nearby lines may merge; bin precision and group width are not physical linewidth resolution.",
        "Analysis support is not event duration."] + inp["limitations"]
    if inp["validity"]["status"] != "known":
        limitations.append("Validity remains unknown; analyzed only under the recorded user decision.")
    if task["resolved_parameters"]["threshold"]["route"] == "theory":
        limitations.append("Nominal event bound requires the stated exponential cell model; not an observed field guarantee.")
    else:
        limitations.append("Calibration is conditional on asserted H0 representativeness/independence and matching processing.")
    return {"task_id": task["task_id"], "input_ref": task["input_ref"], "detector": task["detector"],
        "execution_status": "completed", "reason": None,
        "coverage": {"requested": task["scope"], "processed": output["processed"],
            "excluded": [{"interval": v, "reason": "No complete tested frame covers these samples; see frame ledger."}
                         for v in output["excluded"]]},
        "candidates": candidates, "limitations": list(dict.fromkeys(limitations)),
        "diagnostics": [f"{len(output['rows'])} detection rows; {len(candidates)} candidates (not false alarms)."],
        "artifacts": [], "quality": quality()}


def ledger(output):
    return {k: output[k] for k in ("rows", "frame_ledger", "alpha", "coefficient", "tests_per_event",
                                  "p_cell", "excluded_frequency_bins")}


def minimum_ledger(output):
    value = {k: output[k] for k in ("frame_ledger", "alpha", "coefficient", "tests_per_event",
                                    "p_cell", "excluded_frequency_bins")}
    value["eligible_frequency_bins"] = output["cut_bins"].tolist()
    value["rows"] = [{
        "row": row["row"], "sample_intervals": row["sample_intervals"], "status": row["status"],
        "tested_bin_count": len(row["tested_bins"]), "zero_background_bins": row["zero_background_bins"],
        "candidate_count": row["candidate_count"], "rejected_group_count": len(row["rejected_groups"]),
        "rejection_reasons": sorted(set(v["reason"] for v in row["rejected_groups"]))
    } for row in output["rows"]]
    value["cell_coverage_definition"] = "Per row: eligible_frequency_bins excluding zero_background_bins. The latter also includes nonfinite backgrounds."
    return value


def render_plots(task, inp, output):
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    display = task["resolved_parameters"]["display"]
    selected = set(task["products"]["compute"])
    result = {}
    freq = output["frequency_hz"]; psd = output["psd"]
    def db(values):
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.clip(10 * np.log10(values / display["db_reference_psd"]), *display["db_limits"])
    def png(fig, name):
        buffer = io.BytesIO(); FigureCanvasAgg(fig).print_png(buffer)
        result[name] = buffer.getvalue(); fig.clear()
    if "spectrum_plot" in selected:
        for row in display["spectrum_rows"]:
            fig = Figure(figsize=(9, 4), dpi=120, layout="constrained"); ax = fig.subplots()
            ax.plot(freq, db(psd[row]), label="PSD")
            for name in ("background", "threshold"):
                full = np.full(len(freq), np.nan)
                good = output["cell_valid"][row]
                full[output["cut_bins"][good]] = output[name][row][good]
                ax.plot(freq, db(full), label=name)
            points = [v for v in output["candidates"] if v["row"] == row]
            ax.scatter([v["frequency_hz"] for v in points], db(np.array([v["power"] for v in points])),
                       marker="x", color="red", label="candidate")
            ax.set(xlim=task["scope"]["search_band_hz"], ylim=display["db_limits"],
                   xlabel="Frequency (Hz)", ylabel="Relative PSD (dB; not SPL)",
                   title=display["title"] + f" | {task['task_id']} | row {row}")
            ax.legend(); ax.grid(alpha=.2)
            png(fig, f"spectrum-row-{row:08d}.png")
    if "time_frequency_plot" in selected:
        fig = Figure(figsize=(9, 5), dpi=120, layout="constrained"); ax = fig.subplots()
        df = freq[1] - freq[0]; edges = np.r_[freq - df / 2, freq[-1] + df / 2]
        fs = inp["sample_rate_hz"]; offset = inp["time_mapping"]["sample_zero_offset_seconds"]
        sp = task["resolved_parameters"]["spectrum"]
        half = min(sp["hop_length"], sp["window_length"]) / (2 * fs)
        centers = []
        for i, row in enumerate(output["rows"]):
            a, b = row["sample_intervals"][0]; t = offset + (a + b - 1) / (2 * fs); centers.append(t)
            artist = ax.pcolormesh(edges, [t-half, t+half], db(psd[i:i+1]), shading="flat",
                vmin=display["db_limits"][0], vmax=display["db_limits"][1], cmap="viridis")
        ax.scatter([v["frequency_hz"] for v in output["candidates"]],
                   [centers[v["row"]] for v in output["candidates"]], marker="x", s=14, c="red")
        ax.set(xlim=task["scope"]["search_band_hz"], xlabel="Frequency (Hz)",
               ylabel="Source-relative window-center time (s)", title=display["title"] + " | " + task["task_id"])
        fig.colorbar(artist, ax=ax, label="Relative PSD (dB; not SPL)")
        png(fig, "time-frequency.png")
    return result


def build_products(task, inp, output, public):
    products = {}
    selected = set(task["products"]["compute"])
    if "candidates" in selected:
        products["candidates"] = {"candidates.json": json_bytes(public["candidates"])}
    if "ledger" in selected:
        products["ledger"] = {"ledger.json": json_bytes(ledger(output))}
    if "spectra" in selected:
        buffer = io.BytesIO()
        # Ragged original supports stay in JSON, never pickle/object arrays.
        np.savez(buffer, frequency_hz=output["frequency_hz"], cut_bins=output["cut_bins"],
                 psd=output["psd"], background=output["background"], threshold=output["threshold"],
                 cell_valid=output["cell_valid"])
        products["spectra"] = {"spectra.npz": buffer.getvalue(),
            "spectra-coordinates.json": json_bytes({"rows": [{"row": v["row"], "sample_intervals": v["sample_intervals"]}
                for v in output["rows"]], "time_mapping": inp["time_mapping"], "sample_rate_hz": inp["sample_rate_hz"],
                "units": inp["units"], "psd_definition": "One-sided input-unit squared per Hz; not SPL."})}
    if selected & {"spectrum_plot", "time_frequency_plot"}:
        images = render_plots(task, inp, output)
        for name in ("spectrum_plot", "time_frequency_plot"):
            if name in selected:
                products[name] = {k: v for k, v in images.items()
                                  if (k == "time-frequency.png") == (name == "time_frequency_plot")}
    if "report" in selected:
        summary = {"task": task["task_id"], "source": task["input_ref"], "beam_source": inp["beam_source"],
            "coverage": public["coverage"], "candidate_count": len(public["candidates"]),
            "candidates": public["candidates"], "limitations": public["limitations"]}
        content = "<!doctype html><meta charset='utf-8'><title>CFAR detection</title><h1>CFAR candidates</h1>"
        content += "<p>Execution evidence only. Candidates are not identified targets or measured false alarms.</p><pre>"
        content += html.escape(json.dumps(summary, ensure_ascii=False, indent=2)) + "</pre>"
        products["report"] = {"report.html": content.encode()}
    return products


def artifact(task, inp, product, ref, status):
    return {"product_id": product, "task_id": task["task_id"], "kind": product,
        "status": status, "file_ref": ref, "definition": PRODUCTS[product][1],
        "axes": ["frequency", "original_sample_support"],
        "coordinates": {"definition": "Native FFT bins and original half-open sample intervals; inspect product manifest.",
                        "evidence_ref": ref},
        "validity_definition": "Full two-sided references and complete frames only; skips retained in ledger.",
        "units": {"status": "unknown", "value": None, "amplitude_convention": "Per-field units in result and coordinates.",
                  "evidence": "Compound product; not a scalar SPL quantity."},
        "provenance_refs": [inp["source_package"]["manifest"], inp["processing_history"]["source_configuration"]],
        "lifecycle": "Durable only with completed package manifest." if status == "saved" else "Current process only; not retained on CLI exit."}

def render_beam_context(beam):
    """Plot selected existing values only; never estimate spectra or choose directions."""
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    cfg = beam["selection"]; display = cfg["display"]
    if not cfg["plot_products"]:
        return {}
    if display is None or set(display) != {"reference_psd", "reference_power", "db_limits", "title"}:
        raise ValueError("Explicit display references, dB limits and title required for existing beam plots.")
    if any(type(display[k]) not in (float, int) or not np.isfinite(display[k]) or display[k] <= 0
           for k in ("reference_psd", "reference_power")):
        raise ValueError("Display references must be positive finite numbers, not inferred shared maxima.")
    limits = display["db_limits"]
    if not isinstance(limits, list) or len(limits) != 2 or not all(type(v) in (int, float) and np.isfinite(v) for v in limits) or not limits[0] < limits[1]:
        raise ValueError("Explicit increasing finite display limits required.")
    images = {}; freq = beam["frequency_hz"]; times = beam["time_seconds"]
    labels = [b["beam_id"] + " " + str(b["direction_deg"]) for b in beam["selected_beams"]]
    def db(value, power=False):
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.clip(10*np.log10(value / display["reference_power" if power else "reference_psd"]), *limits)
    def save(fig, name):
        buffer = io.BytesIO(); FigureCanvasAgg(fig).print_png(buffer)
        images[name] = buffer.getvalue(); fig.clear()
    for product in cfg["plot_products"]:
        values = beam["values"][product]
        if product == "time_frequency":
            settings = beam["metadata"]["spectral_products"]["settings"]
            half = min(settings["hop_samples"], settings["window_samples"]) / (2*beam["metadata"]["sample_rate_hz"])
            df = beam["metadata"]["sample_rate_hz"] / settings["nfft"]
            edges = np.r_[freq-df/2, freq[-1]+df/2]
            for column, label in enumerate(labels):
                fig = Figure(figsize=(9, 5), dpi=120, layout="constrained"); ax = fig.subplots()
                for row, time in enumerate(times):
                    artist = ax.pcolormesh(edges, [time-half, time+half], db(values[row:row+1, :, column]),
                        shading="flat", vmin=limits[0], vmax=limits[1], cmap="viridis")
                ax.set(xlabel="Frequency (Hz)", ylabel="Source-relative time center (s)",
                       title=display["title"]+" | "+label+" | existing time-frequency PSD")
                fig.colorbar(artist, ax=ax, label="Relative PSD (dB; not SPL)")
                save(fig, f"time-frequency-beam-{column:06d}.png")
            continue
        fig = Figure(figsize=(9, 5), dpi=120, layout="constrained"); ax = fig.subplots()
        if product == "psd":
            for column, label in enumerate(labels):
                ax.plot(freq, db(values[:, column]), label=label)
            ax.set(xlabel="Frequency (Hz)", ylabel="Time-mean relative PSD (dB; not SPL)", ylim=limits)
            ax.legend()
        elif product == "btr":
            for column, label in enumerate(labels):
                # Points do not bridge gaps or imply unobserved/interpolated values.
                ax.scatter(times, db(values[:, column], True), s=10, label=label)
            ax.set(xlabel="Source-relative time center (s)", ylabel="Band-integrated power (relative dB; not a single line)", ylim=limits)
            ax.legend()
        elif product == "scan_power":
            ax.bar(np.arange(len(labels)), db(values, True)-limits[0], bottom=limits[0])
            ax.set_xticks(np.arange(len(labels)), labels, rotation=20)
            ax.set(ylabel="Time-mean band power (relative dB)", ylim=limits)
        elif product == "frequency_angle":
            settings = beam["metadata"]["spectral_products"]["settings"]
            df = beam["metadata"]["sample_rate_hz"] / settings["nfft"]
            edges = np.r_[freq-df/2, freq[-1]+df/2]
            artist = ax.pcolormesh(np.arange(len(labels)+1)-.5, edges, db(values),
                shading="flat", vmin=limits[0], vmax=limits[1], cmap="viridis")
            ax.set_xticks(np.arange(len(labels)), labels, rotation=20)
            ax.set(xlabel="Explicit selected beam IDs/directions (categorical; no angle interpolation)", ylabel="Frequency (Hz)")
            fig.colorbar(artist, ax=ax, label="Time-mean relative PSD (dB; not instantaneous)")
        ax.set_title(display["title"]+" | "+cfg["algorithm"]+" | existing "+product)
        save(fig, product+".png")
    return images
