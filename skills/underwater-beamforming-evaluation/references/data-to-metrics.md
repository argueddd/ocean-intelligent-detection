# Data-to-Metrics Guide

Use this guide to decide how to evaluate different underwater beamforming data products. Start with the strongest data type available, then choose only metrics supported by the data and metadata.

## Priority Order

1. Start with `P(theta)` spatial spectra because they are the easiest to standardize and automate.
2. Add DOA estimate sequences when truth or reference bearings are available.
3. Add `P(f, theta)` frequency-bearing matrices for broadband or line-spectrum evidence.
4. Add `P(t, theta)` or BTR matrices for moving targets and long-duration displays.
5. Add beamformed time-domain signals for SNR/SINR, suppression, and distortion.
6. Add beam output spectra or PSDs for target line enhancement and interference suppression.
7. Treat images as qualitative unless axis ticks and color bars support defensible approximate extraction.

## Common Metadata

Ask for or infer these before computing metrics:

- Array: geometry, element count, element spacing, calibration state.
- Axes: bearing/angle axis, frequency axis, time/frame axis.
- Units: degree/radian, Hz/kHz, seconds/frame index, dB/power/amplitude.
- Scenario: far-field/near-field, narrowband/broadband, target count, interference, multipath/reverberation.
- Truth/reference: true target bearings, target track, interference bearing, clean/noise segments, target/noise bands.
- Processing: algorithm name, preprocessing, snapshot count, diagonal loading/regularization, broadband fusion method.

If a required item is absent, state what cannot be computed and downgrade to the nearest valid qualitative or relative metric.

## Quick Selection Table

| Data type | Main metrics | Required metadata | Automation level |
|---|---|---|---|
| `P(theta)` spatial spectrum | peak bearing, HPBW, PSL, MSR, false peaks, DOA error | bearing axis, scale, optional truth | high |
| DOA estimates | error, MAE, RMSE, bias, variance, detection/miss/false alarm | estimates, truth/reference, association rule | high |
| `P(f, theta)` frequency-bearing matrix | per-frequency peak, frequency consistency, broadband peak, band MSR, false peaks | frequency axis, bearing axis, scale, fusion rule | medium-high |
| `P(t, theta)` / BTR matrix | track continuity, smoothness, ridge contrast, false tracks, frame error | time axis, bearing axis, optional truth track | medium |
| Beamformed time signal | output power, SNR/SINR, suppression, distortion, correlation | sampling rate, target/noise/interference segments | medium |
| Beam output spectrum/PSD | target-band energy, band SNR, line enhancement, interference attenuation | frequency axis, target/noise/interference bands | medium-high |
| `P(t, f)` time-frequency matrix | target-line continuity, time-varying SNR, frequency drift, baseline improvement | time axis, frequency axis, target/noise bands | medium-high |
| Result image | mainlobe, sidelobes, false peaks, BTR readability, plot quality | readable axes/color bar for semi-quantitative use | low |
| Comparison table | ranking, normalized score, tradeoff analysis | metric direction, comparable conditions | medium |

## `P(theta)` Spatial Spectrum

Script command: `scripts/beamforming_metrics.py spectrum`.

### Input Definition

- Required: bearing axis `theta`, spectrum `P(theta)`.
- Optional: true bearing `theta_true`, target count, mainlobe exclusion angle, false-peak threshold.
- Preferred units: `theta` in degrees; spectrum scale explicitly labeled as `dB`, `power`, or `amplitude`.

### Computable Metrics

| Metric | Requires truth | Calculation |
|---|---|---|
| Peak bearing | no | `theta[argmax(P)]` after scale normalization |
| Bearing error | yes | circular absolute difference between peak/associated estimate and truth |
| MAE/RMSE | yes | aggregate angular errors across trials, frames, or targets |
| HPBW | no | angular width where main peak drops by 3 dB |
| PSL | no | maximum sidelobe level relative to main peak |
| MSR | no | main peak level minus largest sidelobe level |
| False peak count | optional | non-target/local peaks above a relative threshold |
| Dynamic range | no | main peak level minus background floor or displayed floor |

### Calculation Steps

1. Confirm the spectrum scale. Use dB for peak/drop reporting, but convert dB to linear power before any mean, sum, or energy integration.
2. Detect local peaks and identify the main peak or target-associated peaks.
3. Define the mainlobe region by a local-minimum search or a fixed exclusion angle.
4. Compute HPBW from the `-3 dB` crossing around the main peak.
5. Compute PSL/MSR from peaks outside the mainlobe region.
6. If truth exists, associate peaks to truth bearings and compute angular error, MAE, and RMSE.

### Notes

- For a single target, the global maximum can usually be treated as the estimated bearing.
- For multiple targets, detect multiple peaks and associate them to truth bearings before computing errors.
- A lower sidelobe result is not automatically better if the peak is biased, broadened, or unstable.

## DOA Estimate Sequence

Script command: `scripts/beamforming_metrics.py doa`.

### Input Definition

- Required: estimated bearings `theta_hat`.
- Required for accuracy: truth/reference bearings `theta_true`.
- Optional: time/frame index, confidence, target ID, detection threshold, valid search sector.

### Computable Metrics

| Metric | Requires truth | Calculation |
|---|---|---|
| Angular error | yes | circular signed or absolute difference |
| MAE | yes | mean absolute angular error |
| RMSE | yes | root mean square angular error |
| Bias | yes | mean signed angular error |
| Error standard deviation | yes | standard deviation after circular wrapping |
| Detection probability | yes | detected true targets divided by expected true targets |
| Miss rate | yes | missed true targets divided by expected true targets |
| False alarm rate | yes/annotation | non-associated estimates per frame/trial/search sector |
| Track continuity | optional truth | valid associated detections divided by frames |

### Calculation Steps

1. Normalize bearings to a consistent angular range, such as `[-180, 180)` or `[0, 360)`.
2. Match estimates to truth with a gated one-to-one maximum-cardinality/minimum-total-error assignment. A greedy nearest-pair rule can lose otherwise valid matches.
3. Count unmatched truths as misses and unmatched estimates as false alarms.
4. Compute error statistics on matched pairs only.
5. For time series, compute continuity and track break counts after association.

### Notes

- Do not compare sorted estimate lists directly in multi-target cases; always perform association.
- If no truth exists, report stability and continuity rather than MAE/RMSE.
- In the script's default CSV/NPY format, rows are frames/trials and columns are detections or targets. Use blank/NaN cells for missing estimates or missing truth entries.

## `P(f, theta)` Frequency-Bearing Matrix

Script command: `scripts/beamforming_metrics.py freq-bearing`.

### Input Definition

- Required: frequency axis `f`, bearing axis `theta`, matrix `P(f, theta)`.
- Optional: target frequency band, known target lines, true bearing, interference bearing.
- Convention: last axis should be bearing if passed to generic spectrum tooling.

### Computable Metrics

| Metric | Requires truth | Calculation |
|---|---|---|
| Per-frequency peak bearing | no | `argmax_theta P(f_i, theta)` for each frequency bin |
| Frequency bearing consistency | optional | dispersion of peak bearings across target band |
| Broadband fused peak | no | reduce over selected frequency band, then evaluate as `P(theta)` |
| Band MSR/PSL | no | sidelobe metrics on fused spectrum or per frequency |
| Target-line enhancement | target band | energy at target band and bearing versus local background |
| Frequency-dependent bias | yes | per-frequency peak error against truth bearing |
| False peak density | optional | number of strong non-target peaks per frequency or band |

### Calculation Steps

1. Select the frequency range used for evaluation.
2. State the broadband reduction rule: max, mean, sum, weighted integration, or selected bins.
3. Compute per-frequency peak bearings in the target band.
4. Compute bearing consistency using standard deviation or median absolute deviation.
5. Fuse the band to `P(theta)` and compute peak, HPBW, PSL, MSR, and false peaks.
6. If truth exists, compute per-frequency and fused-spectrum DOA error.

### Notes

- Never collapse `P(f, theta)` without stating the frequency range and reduction method.
- Max reduction can emphasize sparse target lines but may also preserve random false peaks.
- Mean/sum reduction can be more stable but may smear narrowband target evidence.
- In the script's default format, rows are frequency bins and columns are bearings. The default fusion is `power-sum`; use `db-max` when the goal is to highlight sparse line-spectrum evidence.

## `P(t, theta)` or BTR Matrix

Script command: `scripts/beamforming_metrics.py btr`.

### Input Definition

- Required: time/frame axis `t`, bearing axis `theta`, matrix `P(t, theta)`.
- Optional: true target track, expected maneuver, target count, detection threshold.
- Script convention: rows are time frames and columns are bearings. `truth_track.csv` uses one row per frame; the first finite value is used as the first-version single-target truth.
- Image-only BTR should be treated under the image section unless matrix values are available.

### Computable Metrics

| Metric | Requires truth | Calculation |
|---|---|---|
| Frame peak bearing | no | peak bearing per frame |
| Track continuity | optional | valid target ridge frames divided by total frames |
| Track smoothness | no | frame-to-frame bearing change after ridge association |
| Track break count | optional | number of gaps longer than a chosen frame threshold |
| Ridge contrast | no | ridge level relative to local bearing background |
| Frame-wise bearing error | yes | associated peak/track versus truth track |
| False-track count | annotation/logic | persistent ridges not associated with expected track |
| Strong secondary peak fraction | no | frames where a strong non-primary peak competes with the selected ridge |
| Reinitialization count | no | no-truth ridge extraction count of jumps beyond the maximum allowed frame-to-frame motion |

### Calculation Steps

1. Convert the BTR matrix to dB if needed.
2. Detect per-frame local peaks and keep up to `top-k` candidates within `relative-threshold-db` of the frame maximum.
3. If a truth track exists, use truth-guided mode: search within `truth ± gate-deg`, require the ridge level to be within the relative threshold, and compute frame-wise errors.
4. If no truth track exists, use ridge-extraction mode: link candidates with the `max-jump-deg` motion constraint and reinitialize when no candidate satisfies the jump constraint.
5. Compute continuity, break count, maximum gap length, jump statistics, ridge contrast, and strong secondary peak fraction.
6. If a truth track exists, compute MAE/RMSE, bias, miss frames, and track continuity. If no truth exists, do not report accuracy metrics.

### Notes

- BTR evaluation is often semi-automatic because ridge extraction and target association can be ambiguous.
- A visually continuous false ridge can be worse than scattered weak sidelobes in engineering use.
- For moving platforms, check whether apparent bearing drift is physical motion or array/heading error.
- Default script parameters are `gate-deg=5`, `top-k=3`, `relative-threshold-db=12`, `max-jump-deg=5`, and `background-exclusion-deg=5`. Tune them to frame rate, expected target motion, and array angular resolution.
- First-version script behavior is intentionally single-main-track oriented; complex multi-target BTR identity tracking should be treated as a later extension.

## Beamformed Time-Domain Signal

Script command: `scripts/beamforming_metrics.py signal`.

### Input Definition

- Required: beam output signal `y(t)`.
- Required for time metrics: sampling rate `fs`.
- Required for SNR/SINR: target/noise/interference segments or reference signals.
- Optional: input channel/reference signal, target beam, interference beam, clean signal.
- Script convention: input may be 1D `[samples]` or 2D `[samples, columns]`; use `--column` for 2D data. Time segments use seconds formatted as `start:end`.

### Computable Metrics

| Metric | Requires reference/labels | Calculation |
|---|---|---|
| RMS, peak, crest factor | no | global amplitude and power descriptors |
| Output power | no | mean squared amplitude over selected segment |
| Segment energy ratio | segment labels | target-segment power versus noise-segment power |
| Output SNR | target/noise labels | target power divided by noise power |
| SNR improvement | input SNR | output SNR minus input SNR in dB |
| Output SINR | target/interference/noise labels | target power divided by interference-plus-noise power |
| Interference suppression | interference reference/segment | interference power before versus after beamforming |
| Waveform distortion | clean/reference signal | correlation, normalized MSE, or spectral distortion |

### Calculation Steps

1. Define analysis windows: target, noise, and interference segments.
2. Remove DC and apply consistent filtering/windowing if appropriate.
3. Compute power or PSD in the same bandwidth for all compared signals.
4. Compute SNR/SINR only when segment labels or references make the decomposition defensible.
5. Compare target preservation and interference suppression together.
6. If a clean/reference signal exists, compute correlation and normalized MSE.

### Notes

- Without target/noise labels, report output level and qualitative enhancement, not rigorous SNR.
- Adaptive beamforming may suppress interference while distorting target waveforms; evaluate both.
- Default script behavior uses `--detrend mean`. First-version signal metrics do not automatically filter, detect segments, compute STFT, or handle complex-valued samples.
- Without a baseline, do not report SNR improvement or interference suppression. Without a reference signal, do not report waveform distortion.

## Beam Output Spectrum or PSD

Script command: `scripts/beamforming_metrics.py spectrum-output`.

### Input Definition

- Required: frequency axis `f`, spectrum/PSD `Y(f)`.
- Required for band metrics: target band and noise/reference band.
- Optional: interference band, input spectrum, baseline beamformer spectrum.
- Script convention: input may be 1D `[frequency]` or 2D `[frequency, columns]`; use `--column` for 2D data. Frequency bands use `low:high`.

### Computable Metrics

| Metric | Requires band labels | Calculation |
|---|---|---|
| Global peak and dynamic range | no | peak frequency/level and peak-to-floor difference |
| Target-band energy | target band | sum/mean PSD over target band |
| Noise-band energy | noise band | sum/mean PSD over noise band |
| Band SNR | target and noise bands | target-band power versus noise-band power |
| Line enhancement | baseline/input | target-line level after versus before beamforming |
| Interference attenuation | interference band/reference | interference-band power reduction |
| Background floor reduction | baseline/input | median or percentile floor change |

### Calculation Steps

1. Confirm whether the spectrum is amplitude, power, PSD, or dB.
2. Define target, noise, and interference bands.
3. Integrate or average power over the selected bands.
4. Compare against input, baseline, or a non-target beam when available.
5. Report line enhancement and background change separately.

### Notes

- A narrow target line should not be evaluated with an overly wide target band unless justified.
- Use identical windows, FFT length, averaging, and frequency bands for algorithm comparisons.
- If input is in dB, convert to linear power before frequency-band integration. Do not average dB values as band energy.
- First-version spectrum metrics support one target band, one noise band, and one interference band.

## `P(t, f)` Time-Frequency Matrix

Script command: `scripts/beamforming_metrics.py time-frequency`.

### Input Definition

- Required: time axis `t`, frequency axis `f`, matrix `P(t, f)`.
- Required for line metrics: target frequency band.
- Optional: noise/reference band, interference band, baseline time-frequency matrix.
- Script convention: rows are time frames and columns are frequency bins. First-version support is 2D only, not `P(t, f, beam)` or `P(t, f, theta)`.

### Computable Metrics

| Metric | Requires band labels | Calculation |
|---|---|---|
| Target-band power statistics | target band | mean/median/p10/std of per-frame target-band power |
| Time-varying SNR | target and noise bands | per-frame target-band power minus noise-band power |
| Line presence fraction | target band | frames where target peak exceeds local floor by threshold |
| Line break count | target band | interruptions in target-line presence |
| Maximum line gap length | target band | longest consecutive missing interval |
| Dominant frequency drift | target band | target-band peak frequency over frames where line is present |
| Interference attenuation | baseline and interference band | baseline interference-band power minus output interference-band power |
| Baseline improvement | baseline | target enhancement, noise-floor reduction, SNR improvement |

### Calculation Steps

1. Convert `P(t, f)` to dB for peak/floor operations and to linear power for band integration.
2. For each frame, integrate target/noise/interference bands in linear power.
3. Compute per-frame time-frequency SNR when both target and noise bands exist.
4. Detect target-line presence when the target-band peak exceeds the selected noise/background floor by `presence-threshold-db`.
5. Compute line continuity, break count, maximum gap length, dominant frequency statistics, and baseline improvements if a baseline matrix is provided.

### Notes

- Default script threshold is `presence-threshold-db=6`.
- Without a target band, do not run time-frequency metrics. Without a noise band, do not report strict time-varying SNR.
- Dominant frequency statistics should only use frames where the target line is present.
- First-version time-frequency metrics do not compute STFT from time-domain signals and do not support multi-target or multi-band line tracking.

## Result Images

### Input Definition

- Includes spatial spectrum screenshots, frequency-bearing images, BTR images, and paper figures.
- Required for semi-quantitative reading: clear axis labels, ticks, color bar, and sufficient resolution.

### Valid Evaluation

- Mainlobe clarity and location.
- Apparent sidelobe level and false peaks.
- Peak separation and multi-target visibility.
- BTR ridge continuity, false tracks, and background suppression.
- Figure readability, dynamic range consistency, and whether the visual evidence supports the claim.

### Invalid or Risky Evaluation

- Do not report exact HPBW, PSL, RMSE, SNR, or SINR from a low-resolution image.
- Do not assume color values are linear or comparable across figures unless the color bars match.
- Do not compare visual brightness across subplots with different normalization.

## Multi-Algorithm Comparison Tables

Script command: `scripts/beamforming_metrics.py compare`.

### Input Definition

- Required: algorithms, metrics, values, and whether each metric is higher-better or lower-better.
- Required for fairness: same data, array, SNR, snapshots, frequency band, preprocessing, and target/interference conditions.
- Script input uses two CSV files:
  - `metrics.csv`: contains `algorithm`, optional `scenario`, and one column per metric.
  - `metric_spec.csv`: contains `metric`, `display_name`, `direction`, `weight`, `acceptable_min`, `acceptable_max`, `critical`, and `category`.
- First-version `direction` supports `higher` and `lower`.

Example `metrics.csv`:

```csv
algorithm,scenario,doa_rmse_deg,track_continuity,msr_db,band_snr_db,false_alarm_rate,runtime_ms
CBF,low_snr,3.2,0.82,8.1,12.5,0.12,8
MVDR,low_snr,1.7,0.76,15.3,19.8,0.18,24
Sparse,low_snr,1.2,0.88,18.5,21.1,0.08,130
```

Example `metric_spec.csv`:

```csv
metric,display_name,direction,weight,acceptable_min,acceptable_max,critical,category
doa_rmse_deg,方位RMSE,lower,0.25,,2.0,true,accuracy
track_continuity,轨迹连续性,higher,0.20,0.85,,true,tracking
msr_db,主旁瓣比,higher,0.15,12,,false,sidelobe
band_snr_db,频带SNR,higher,0.15,15,,false,output
false_alarm_rate,虚警率,lower,0.15,,0.10,true,false_alarm
runtime_ms,运行时间,lower,0.10,,50,false,engineering
```

### Computable Metrics

- Absolute ranking per metric.
- Normalized score when metric directions are known.
- Pareto tradeoff: accuracy versus robustness, sidelobe suppression versus target preservation, performance versus runtime.
- Missing-evidence analysis.
- Paper relative score: weighted normalized score across available metrics.
- Paper evidence-adjusted score: `relative_score * evidence_completeness`, used for default paper ranking to avoid rewarding incomplete evidence.
- Engineering acceptance score: passed threshold weight divided by required threshold weight.
- Critical failures and critical missing evidence.

### Calculation Steps

1. Validate comparability of experimental conditions.
2. Mark each metric direction: lower-better or higher-better.
3. Rank algorithms per metric.
4. In `paper` mode, normalize each metric within the current table, compute weighted relative scores, and rank by evidence-adjusted score.
5. In `engineering` mode, compare each metric to project thresholds and apply the critical one-vote veto rule.
6. In `dual` mode, report both paper-style ranking and engineering acceptance decisions.
7. Identify tradeoffs rather than forcing a single winner when metrics conflict.

### Notes

- A method with best RMSE may still be unacceptable if false alarms, runtime, or robustness fail.
- A method with high output gain may be suppressing or distorting target content; check target preservation.
- `critical=true` means the metric is an engineering key metric. If any critical metric fails, the algorithm decision must be `不通过`; the combined score cannot offset the critical failure.
- If a critical metric is missing or lacks an engineering threshold, the decision should be `信息不足`, not `通过`.
- If any metric with an explicit engineering threshold is missing its measured value, the decision is also `信息不足`; do not pass on the remaining metrics alone.
- Paper relative scores are comparative within the provided table. They are not absolute engineering pass/fail scores. When evidence is missing, use the evidence-adjusted score for ranking.
- Use `scripts/beamforming_metrics.py plot-compare --compare-json compare_result.json --output-dir figures` to generate first-version PNG charts from `compare` JSON output.
- First-version comparison plotting generates paper evidence-adjusted score bars, engineering acceptance score bars, engineering pass/fail heatmap, and per-metric ranking bars.
- Use `scripts/beamforming_metrics.py plot-pareto --metrics metrics.csv --spec metric_spec.csv --x runtime_ms --y doa_rmse_deg --output figures/pareto_runtime_vs_rmse.png` to generate a two-metric Pareto tradeoff plot plus a same-name JSON summary.
- Pareto plots use `direction` from `metric_spec.csv` to determine which direction is better. A point is on the Pareto front if no other algorithm is no worse on both selected metrics and strictly better on at least one.
- Use `scripts/beamforming_metrics.py plot-scenario-curves --metrics metrics.csv --spec metric_spec.csv --x snr_db --y doa_rmse_deg --output figures/rmse_vs_snr.png` to show how one metric changes with a scenario variable for each algorithm.
- Scenario curves are intended for robustness and operating-boundary analysis. Common x columns include `snr_db`, `snapshots`, `target_sep_deg`, `array_error`, `sound_speed_error`, `sea_state`, or `range_m`.
- For numeric x columns, points are sorted by value. For categorical x columns, use `--x-order calm,moderate,rough` when the natural order is not alphabetical. Repeated rows for the same algorithm and x value are aggregated by `mean` by default; use `--aggregate median|min|max` when needed.
- Use `scripts/beamforming_metrics.py plot-radar --metrics metrics.csv --spec metric_spec.csv --scenario low_snr --include-metrics doa_rmse_deg,track_continuity,msr_db,band_snr_db,false_alarm_rate,runtime_ms --output figures/radar_low_snr.png` to generate a normalized multi-metric radar chart plus a same-name JSON summary.
- Radar charts use direction-aware min-max normalization within the filtered table. A value of `1.0` means best among the plotted candidates for that metric, not an absolute engineering pass.
- Radar charts are useful for showing algorithm profile shape across accuracy, tracking, sidelobe control, output gain, false alarms, and runtime. Keep the plotted algorithms and metrics limited enough for readability; use `--include-metrics` and `--max-candidates` when the table is large.
- Missing metric values are recorded in the JSON summary and plotted as `0` for visual completeness. Treat low evidence completeness as a warning, not as a precise performance penalty.
- Radar scores must not override `critical=true` engineering one-vote veto decisions. Use the radar chart for profile communication, and use `compare` engineering output for pass/fail.

## What Not to Compute Without Support

- DOA RMSE without truth/reference bearings.
- Detection probability without expected target events.
- False alarm rate without a detection definition or search region.
- SNR/SINR without target/noise/interference separation.
- Time-frequency SNR without target and noise frequency bands.
- Engineering pass/fail without project thresholds or clearly stated recommended thresholds.
- Exact numeric metrics from images without reliable axis/color extraction.
