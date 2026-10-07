# Line-Spectrum Detection Methods

> 历史方法知识库，不是第一版执行规范。下文 default/mandatory、示例参数、基线与保存建议均只能用于明确请求的研究讨论，不能覆盖本 Skill 的逐项确认、CA/OS 范围和按需保存规则；不自动跟踪、谐波归并或执行 DEMON。第一版方法以 cfar-design.md 为准，效果评价由同级 underwater-line-spectrum-evaluation 负责。

Use this reference when designing, improving, implementing, or debugging underwater acoustic line-spectrum detection methods. Keep the method discussion tied to the user's input type, objective, and evaluation target.

## Method Design Entry Point

Before choosing an algorithm, classify the task along five axes:

- Input representation: raw waveform, beamformed waveform, PSD, LOFAR/time-frequency matrix, DEMON spectrum, detected peak table, or paper figure.
- Target pattern: isolated tonal, multiple independent tonals, harmonic family, drifting ridge, intermittent line, weak line under strong background, or modulation line.
- Main objective: weak-line detection, low false alarm, frequency accuracy, track continuity, harmonic identification, paper comparison, or online deployment.
- Scene constraints: sample rate, data duration, search band, expected frequency drift, line spacing, colored noise, platform motion, interference, and truth availability.
- Operating constraints: latency, memory, threshold stability, manual tuning allowance, and acceptable missed detection or false alarm risk.

Do not start from a fashionable method. Start from the failure mode the detector must survive.

## Recommended Method Pipeline

Use this default pipeline unless the user's data or code already fixes some stages:

1. Preprocess signal or spectrum.
2. Estimate PSD or time-frequency representation.
3. Estimate local background or noise floor.
4. Enhance candidate line features if needed.
5. Detect line candidates with a threshold or score.
6. Associate candidates across time or harmonic order when relevant.
7. Suppress duplicates and edge artifacts.
8. Output detections with frequency, time, score, confidence, and method settings.

For engineering work, preserve intermediate products: PSD/LOFAR matrix, noise floor, threshold curve, raw candidates, final candidates, and rejected candidates. These are often more useful for debugging than the final line list.

## Signal And Spectrum Conventions

Check these before method design or code review:

- Frequency axis must be in Hz, not FFT-bin index.
- State whether the spectrum is one-sided or two-sided.
- State whether the level is amplitude, power, PSD, normalized display intensity, or dB.
- For dB spectra, subtraction corresponds to a ratio. For linear spectra, use division or log conversion.
- LOFAR/time-frequency matrices should state row/column meaning, frame hop, window length, and frequency grid.
- DEMON results should state the demodulation band, envelope extraction method, and modulation-frequency axis.

Frequency-grid spacing:

```text
df = fs / nfft
```

Physical resolvability is controlled mainly by observation length, window shape, SNR, and smoothing. Zero-padding gives a denser display grid but does not create independent frequency resolution.

## Preprocessing

Use preprocessing to make the spectrum and threshold meaningful:

- Remove DC and slow trends before FFT/STFT.
- Use bandpass filtering when the search band is known; keep filter transition bands away from expected lines.
- Segment data with a window suited to the task: Hann/Hamming for general PSD, flat-top for amplitude accuracy, longer windows for close-line separation.
- Use overlap for smoother time updates, but do not count overlapped frames as fully independent evidence.
- Normalize consistently across frames if comparing LOFAR intensity over time.
- For array or beamformed output, record beam direction and beamformer settings because spatial processing can change line salience.

Avoid these preprocessing errors:

- Filtering out target harmonics while removing "background."
- Comparing PSD values from different window normalizations as absolute improvements.
- Estimating a single global noise floor over a wide colored underwater spectrum.
- Applying a detector tuned for direct tonal lines to DEMON modulation lines without changing interpretation.

## Spectral Estimation

Choose the spectrum estimator before tuning threshold parameters.

| Estimator | Use when | Strength | Risk |
|---|---|---|---|
| FFT periodogram | Simple baseline, fixed short records | Fast and transparent | High variance and leakage |
| Welch PSD | Stable or slowly varying lines | Lower variance, good engineering baseline | Averaging can smear intermittent lines |
| Multitaper PSD | Weak lines in colored noise | Lower variance and leakage | Too much smoothing can merge close lines |
| STFT/LOFAR | Time-varying or drifting lines | Shows continuity and drift | Time-frequency resolution tradeoff |
| DEMON | Envelope modulation or propeller signatures | Reveals modulation/harmonic structure | Not direct acoustic tonal frequency |
| AR/Burg | Short records or exploratory high resolution | Sharp peaks with limited data | Model order sensitive, spurious peaks |
| MUSIC/ESPRIT-like spectral methods | Few sinusoids, high SNR, valid model | High resolution | Fragile under colored noise and mismatch |

Selection rules:

- Use Welch + local adaptive threshold as the first baseline for most PSD tasks.
- Use STFT/LOFAR when line continuity or drift matters more than a single average spectrum.
- Use multitaper when leakage or estimator variance hides weak lines.
- Use AR/subspace methods as supporting evidence unless model assumptions are clearly valid.
- Use DEMON only for envelope/modulation analysis, not as a replacement for direct tonal PSD.

## Background And Noise-Floor Estimation

Most underwater line detection fails because the background model is wrong. Choose the local background estimator deliberately.

Common options:

- Rolling median: robust and simple for colored noise with sparse lines.
- Rolling percentile: useful when many bins are contaminated; lower percentiles can follow the floor.
- Moving average: acceptable only when training bins are mostly noise.
- Morphological opening: useful for estimating a slowly varying background under narrow peaks.
- CFAR training cells: useful when a controlled false-alarm behavior is required.
- Long-term background model: useful for online monitoring, but must adapt slowly enough not to absorb persistent target lines.

Guard/training-cell logic:

- Guard cells should cover the mainlobe and leakage skirt of a true line.
- Training cells should be local enough to follow colored noise but far enough not to include target energy.
- At band edges, use asymmetric or clipped windows and mark edge detections as lower confidence.
- Strong neighboring tonals can contaminate training cells; prefer ordered-statistic or percentile methods.

## Single-Spectrum Detection

Use for PSD vectors, averaged spectra, or each frame of a time-frequency matrix.

### Local Peak Detection

Use as the mandatory simple baseline:

1. Find local maxima in the search band.
2. Estimate local background around each candidate.
3. Compute candidate salience, such as line SNR or prominence.
4. Apply minimum salience and minimum peak-distance rules.
5. Suppress duplicate peaks caused by leakage skirts.

Good for interpretability and quick sanity checks. Not enough by itself when the noise floor changes rapidly.

### Adaptive Thresholding

Use when background varies with frequency:

```text
candidate_score_db = peak_level_db - local_noise_floor_db
detect if candidate_score_db >= threshold_db
```

Recommended first values for exploration:

- Threshold: 5 to 8 dB for visible moderate-SNR lines.
- Guard width: at least the visible mainlobe half-width.
- Training width: wide enough for stable median/percentile estimates, but not so wide that background slope dominates.

Tune these using a validation set or threshold sweep when possible.

### CFAR

Use CFAR when false-alarm control is a priority.

- CA-CFAR: simple average of training cells. Works in homogeneous noise.
- OS-CFAR: ordered statistic. Better under interfering lines and nonhomogeneous backgrounds.
- GO-CFAR/SO-CFAR: compare left and right training windows. Useful near clutter or spectral steps.

Use guard cells around the test bin and exclude known persistent interference if justified. In line-rich spectra, OS-CFAR or percentile CFAR is usually safer than CA-CFAR.

### Morphological Or Top-Hat Detection

Use when narrow line features sit on a slowly varying broadband background:

1. Estimate background using morphological opening or median filtering.
2. Subtract background to obtain a residual spectrum.
3. Detect residual peaks with a local threshold.

This is useful for LOFAR-like images and display enhancement, but the structuring-element width must be wider than the expected line width and narrower than broad background changes.

### Sparse Or Parametric Detection

Use only when the assumptions are credible:

- Sparse recovery or basis pursuit: useful for off-grid or close tonal components, but sensitive to dictionary design and regularization.
- AR/Burg peak picking: useful for short data exploratory analysis, but requires model-order checks.
- MUSIC/ESPRIT-style estimators: useful for few sinusoids under good SNR and model fit; weak for colored, nonstationary sea data unless prewhitened and validated.

Always compare against Welch or multitaper baselines.

## Time-Frequency Ridge Detection

Use for LOFAR matrices, STFT magnitude/power, or framewise PSD sequences.

### Framewise Detection Plus Linking

Use when lines are visible and drift is modest:

1. Detect peaks in each frame.
2. Link peaks between adjacent frames within a frequency gate.
3. Score tracks by average salience, continuity, and duration.
4. Reject tracks shorter than the minimum meaningful duration.

This is the best first engineering baseline because it is debuggable.

### Dynamic Programming Or Viterbi

Use for weak, intermittent, or drifting lines:

```text
cost = -line_salience + smoothness_penalty + gap_penalty
```

Design choices:

- Frequency-transition gate should reflect expected Doppler drift and `df`.
- Gap penalty controls whether the tracker bridges weak frames or fragments.
- Smoothness penalty should suppress random jumps but allow realistic maneuvers.
- Multiple tracks require duplicate suppression or iterative track removal.

### Hough Or Radon Transform

Use when ridges are approximately straight lines over time:

- Good for constant drift-rate lines.
- Less suitable for curved, maneuvering, or intermittent tracks.
- Can create false positives when many unrelated peaks align by chance.

### Connected Components And Morphology

Use for visible ridge extraction after thresholding:

- Good for measuring line duration, fragmentation, and visual continuity.
- Sensitive to threshold and image smoothing.
- Should not replace frequency-error evaluation when truth tracks exist.

## Harmonic And Comb Detection

Use harmonic logic when detected lines are expected to share a fundamental frequency.

Workflow:

1. Generate candidate fundamentals from expected shaft/blade-rate ranges or pairwise line differences.
2. Predict harmonic frequencies `k * f0` inside the search band.
3. Match detected peaks to expected harmonic positions with an order-dependent tolerance.
4. Score each candidate by harmonic coverage, salience, spacing error, and missing-harmonic penalty.
5. Report alternative fundamentals when doubled, halved, or aliased solutions are plausible.

Practical cautions:

- Do not require every harmonic to be present; real underwater spectra often have missing or masked harmonics.
- Low-order harmonics should usually carry more weight than weak high-order harmonics.
- In DEMON, harmonic families describe modulation structure; label them separately from direct acoustic tonals.
- Harmonic constraints can reduce false alarms, but they can also force unrelated peaks into a false target identity.

## Line Enhancement Methods

Use enhancement only if it improves detection evidence, not just plot appearance.

- Spectral whitening: removes broadband slope and improves local thresholding.
- Median-background subtraction: highlights narrow peaks in colored noise.
- Time integration: improves stable-line SNR but smears intermittent or drifting lines.
- Noncoherent accumulation: robust to phase variation; useful for long monitoring.
- Drift compensation: align a known or estimated ridge before averaging.
- Beamforming before line detection: improves spatially selective line SNR when target bearing is known or estimated.

Always evaluate enhancement with false-alarm behavior. A prettier LOFAR image is not sufficient evidence.

## Online Detection And Track Management

For real-time systems:

- Use bounded-memory Welch/STFT updates.
- Maintain a rolling background model with controlled adaptation speed.
- Output candidate confidence, not only binary detections.
- Use track initiation, confirmation, maintenance, and deletion logic.
- Separate alert logic from raw line detection to avoid repeated alarms for one persistent line.
- Log rejected candidates and threshold curves for post-run diagnosis.

Common online states:

- Tentative: seen for a few frames but not confirmed.
- Confirmed: exceeds duration/continuity and salience requirements.
- Coasting: temporarily missing but allowed to bridge a short gap.
- Deleted: absent longer than allowed or contradicted by evidence.

## Method Selection Guide

Use this compact guide:

| Scenario | Preferred method | Watch-outs |
|---|---|---|
| Stable tonal, moderate SNR | Welch PSD + local adaptive peak detection | Window leakage, fixed threshold bias |
| Weak tonal in colored noise | Multitaper or Welch + whitening + OS-CFAR | Oversmoothing close lines |
| Drifting LOFAR ridge | STFT + frame peaks + Viterbi/DP linking | Drift gate and gap penalty |
| Intermittent line | STFT + robust tracking with bounded gap bridging | False continuity from excessive bridging |
| Several harmonic lines | Peak detection + harmonic/comb association | False fundamental and missing harmonics |
| Strong interfering tonals | OS-CFAR or percentile floor + duplicate suppression | Contaminated training cells |
| Short data record | Multitaper; AR/Burg only as auxiliary | Spurious parametric peaks |
| DEMON modulation analysis | Envelope extraction + modulation-spectrum harmonic detection | Confusing modulation and direct tonals |
| Online monitoring | Welch/STFT + adaptive background + track management | Threshold drift and repeated alarms |
| Paper comparison | Simple baseline + proposed method + ablation | Unfair preprocessing or search bands |

## Parameter Selection Heuristics

Use these as starting points, then tune with validation data:

- Window length: choose from required `df`; longer windows improve frequency discrimination but reduce time resolution.
- FFT length: use at least the window length; zero-padding is display/interpolation, not real resolution.
- Overlap: 50 percent is a common baseline; higher overlap gives smoother display but more correlated frames.
- Local threshold: start around 5 to 8 dB above local floor for visible lines, then sweep.
- Frequency gate: at least one to two bins for grid detections; wider if Doppler or estimator jitter is expected.
- Minimum track length: set from required persistence, not arbitrary frame count.
- Gap allowance: allow short gaps for weak lines, but cap it to avoid false continuity.
- Harmonic tolerance: combine bin width, expected Doppler, and order-dependent error.

When the user provides project thresholds, use them over these heuristics.

## Baselines And Ablations

For experiments and papers, require at least:

- Baseline 1: Welch PSD + local adaptive peak detection.
- Baseline 2: CFAR or percentile-threshold method.
- If tracking is claimed: framewise peak linking baseline.
- If harmonic identification is claimed: peak-only baseline plus harmonic association ablation.
- If robustness is claimed: tests over SNR, drift rate, window length, and interference density.

Ablate separately:

- preprocessing or whitening
- spectrum estimator
- thresholding rule
- tracking/linking rule
- harmonic constraint
- post-processing and duplicate suppression

## Runnable Baseline Script

Use `scripts/line_spectrum_methods.py` for deterministic baseline methods before implementing complex or paper-specific algorithms.

Available commands:

- `synth`: generate synthetic tonal, harmonic, and drifting-line signals with optional truth files.
- `welch-detect`: compute Welch PSD from a raw waveform, then run local adaptive peak detection.
- `psd-detect`: run local background peak detection on an existing PSD or spectrum vector.
- `psd-cfar`: run CA/OS/GO/SO-CFAR on an existing PSD or spectrum vector.
- `lofar-detect`: run framewise line-candidate detection on a LOFAR/time-frequency matrix.
- `ridge-track`: greedily link framewise candidates into interpretable frequency-time tracks.
- `harmonic-assoc`: associate detected peaks with candidate fundamentals and harmonic families.

Example workflow:

```bash
python scripts/line_spectrum_methods.py synth --output signal.csv --fs 2000 --duration-s 10 --lines 137:1,275:0.6 --snr-db 0 --truth-lines-csv truth.csv
python scripts/line_spectrum_methods.py welch-detect --signal signal.csv --signal-column amplitude --fs 2000 --nperseg 1024 --noverlap 512 --band 50:500 --detections-csv detections.csv --psd-csv psd_table.csv --freqs-csv freqs.csv --spectrum-csv psd_db.csv
```

These are historical detection examples, not an authorized workflow. Existing-result evaluation belongs to underwater-line-spectrum-evaluation; do not run the old metrics psd/lofar commands as evaluation-only, since they re-detect and lack the new evidence gates.

## Debugging Checklist

When code or results look wrong, check:

- Spectrum axis: Hz, bin index, one-sided/two-sided, FFT shift, and sample-rate consistency.
- PSD scale: dB, linear power, amplitude, log amplitude, or normalized image intensity.
- Window normalization: affects absolute PSD level and cross-method comparison.
- Threshold scale: dB thresholds should subtract dB levels; linear thresholds should use ratios or converted dB.
- Time-frequency orientation: matrix rows are time or frequency; transposed LOFAR matrices are common.
- Search band: false alarms outside the evaluated band should not be mixed into band-limited metrics.
- Edge handling: local noise windows near band edges can bias detections.
- Peak association: one truth line should not match multiple detections unless duplicate detections are intentionally reported.
- Harmonic labeling: direct tonals and DEMON modulation lines should not share one label set without explanation.
- Interpolation claims: sub-bin estimates require interpolation or parametric estimation and should be reported separately from grid-bin detections.

## Output Recommendations

For method-design answers, include:

1. Recommended pipeline.
2. Why this pipeline matches the data and objective.
3. Key parameters and first-pass values.
4. Failure modes the method addresses.
5. Metrics needed to validate it.
6. Baselines or ablations for comparison.

For code-debugging answers, include:

1. Data shape and axis checks.
2. Scale and normalization checks.
3. Threshold and noise-floor checks.
4. Candidate association and duplicate suppression checks.
5. Minimal reproducible test or synthetic signal suggestion.
