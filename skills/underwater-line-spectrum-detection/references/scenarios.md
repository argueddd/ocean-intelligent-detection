# Underwater Acoustic Scenarios

> 场景解释与历史研究建议，不是执行指令、默认方法或验收标准。第一版检测遵守 cfar-design.md 的已确认范围；评价与比较遵守同级 underwater-line-spectrum-evaluation。以下补算、轨迹/谐波/DEMON、试验及调参建议不能自动执行，也不能把其他声源的真实线谱直接判作通用检测误报。

Use this reference when interpreting line-spectrum results in realistic underwater signal-processing settings.

## Common Line-Spectrum Sources

- Ship-radiated tonal lines: machinery, shaft, gear, motor, pump, and structural vibration components.
- Harmonic families: shaft-rate or blade-rate related lines and their multiples.
- DEMON modulation lines: envelope modulation caused by cavitation or propeller effects; these are modulation frequencies, not necessarily direct acoustic tonal frequencies.
- Platform self-noise: own-ship machinery, flow noise, electrical interference, and sensor artifacts.
- Environmental or biological narrowband interference: may mimic stable lines.

## Scenario Effects

Colored ambient noise:

- Global thresholds are unreliable.
- Use local noise estimation, whitening, or CFAR.
- Report the search band because false alarms depend strongly on bandwidth.

Shallow-water multipath and reverberation:

- Can smear or modulate line energy.
- Can create time-varying salience unrelated to detector quality.
- Time continuity should be interpreted with propagation context.

Platform motion and Doppler:

- Stable machinery lines may drift in received frequency.
- Ridge tracking needs a realistic drift gate.
- Overly strict frequency gates undercount correct detections.

Short data or low update latency:

- Frequency resolution and estimator variance become limiting.
- Multitaper or model-based spectra can help but may introduce assumptions.
- Do not claim close-line separation below effective resolution.

Strong tonal interference:

- CA-CFAR training windows can be contaminated.
- OS-CFAR, percentile floors, or explicit interference masking may be safer.
- False fundamental errors are common in harmonic association.

Array or beamformed output:

- Beamforming can improve line SNR but can also distort levels through steering mismatch or adaptive suppression.
- If the input is a beam output, report beam direction and beamformer settings when possible.
- Combine this skill with beamforming evaluation when spatial selectivity or DOA claims matter.

## LOFAR And DEMON Distinction

LOFAR:

- Usually shows narrowband spectral energy over time.
- Good for tonal detection, frequency drift, and track continuity.
- Metrics focus on line salience, frequency error, and ridge quality.

DEMON:

- Usually shows envelope modulation after bandpass, rectification/envelope extraction, and low-frequency spectral analysis.
- Good for propeller modulation or rotating machinery clues.
- Metrics focus on modulation-line detection and harmonic spacing.

Always state which representation is being evaluated.

## Paper Evaluation Guidance

A convincing paper experiment should include:

- Clear data generation or measurement conditions.
- Same search band and preprocessing for all algorithms.
- Baselines that match the claimed problem: weak-line detection, drifting-line tracking, harmonic association, or real-time detection.
- Quantitative metrics beyond visual plots.
- Parameter sensitivity or threshold sweep.
- Sea-trial or semi-realistic noise tests when claiming underwater robustness.

Weak evidence patterns:

- Only showing one clean LOFAR image.
- Reporting peak height improvement without false-alarm analysis.
- Comparing methods with different smoothing or window lengths.
- Omitting frequency resolution and threshold settings.
- Using simulation only while claiming sea-trial reliability.

## Engineering Acceptance Guidance

Engineering acceptance should answer:

- What line types must be detected?
- What is the search band?
- What false alarm rate is tolerable?
- What detection latency is acceptable?
- What SNR, drift, and nonstationarity ranges must be supported?
- Are thresholds fixed, adaptive, or operator-tuned?
- What happens under missing data, strong interference, or platform self-noise?

Suggested acceptance categories:

- Pass: critical metrics meet thresholds across required scenarios.
- Conditional pass: core detection works, but thresholds, runtime, or robustness need bounded operating conditions.
- Fail: critical false alarm, missed detection, runtime, or robustness metrics fail.
- Inconclusive: metadata, truth, or comparable baselines are insufficient.

Do not convert suggested thresholds into final pass/fail criteria unless the user or project specification approves them.
