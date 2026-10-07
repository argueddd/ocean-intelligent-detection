# Underwater Beamforming Evaluation Scenarios

Use this guide to choose the right evaluation emphasis.

## Paper Evaluation

Purpose: decide whether experiments support a research claim.

Emphasize:

- Fair comparison against CBF, MVDR/Capon, MUSIC/ESPRIT, sparse reconstruction, or relevant modern baselines.
- Consistent array geometry, preprocessing, SNR, snapshots, bandwidth, and target/interference conditions.
- Ablations for key modules or parameters.
- Curves versus SNR, snapshot count, target separation, and mismatch.
- Statistical repeatability across Monte Carlo trials or independent data segments.
- Clear figures with readable axes, color bars, units, and comparable dynamic ranges.
- Failure cases and applicability boundaries.

Common weaknesses:

- Only showing one favorable example.
- Comparing algorithms under unequal assumptions.
- Reporting high peak values without DOA error or sidelobe metrics.
- Omitting runtime or parameter sensitivity for complex methods.

## Engineering Acceptance

Purpose: decide whether an algorithm/system is deployable.

Emphasize:

- Explicit pass/fail thresholds supplied by the project.
- Stable operation on representative measured data, not only ideal simulation.
- Missed detection, false alarm, false track, and track fragmentation.
- Robustness to array calibration error, platform motion, sound-speed mismatch, multipath, reverberation, and colored noise.
- Real-time throughput, memory, latency, and batch-processing reliability.
- Parameter sensitivity and ease of field tuning.
- Failure mode logging and interpretability for operators.

If thresholds are missing, propose candidate thresholds but label them as recommendations.

## Far-Field Narrowband

Usually evaluate DOA error, HPBW, PSL/MSR, resolution, and array gain. Ensure the steering vector and angular grid match the array geometry.

## Broadband or Frequency-Bearing Results

Evaluate per-frequency consistency, broadband fusion method, target frequency-line enhancement, frequency-dependent bias, and whether wideband processing preserves coherent target evidence.

Avoid collapsing `P(f, theta)` without saying whether the reduction is max, mean, sum, weighted integration, or selected frequency band.

## BTR and Moving Targets

Evaluate ridge continuity, target-track smoothness, false tracks, background suppression, and alignment with expected motion. Engineering reports should include track breaks and operator-visible artifacts.

## Near-Field or Matched-Field-Like Cases

Do not treat results as pure far-field DOA unless the assumptions justify it. Consider range-bearing ambiguity, environmental mismatch, sound-speed profile sensitivity, and source-depth effects.

## Shallow Water, Multipath, and Reverberation

Expect ghost peaks, broadened mainlobes, ridge splitting, and nonstationary background. Diagnose whether false peaks are consistent with multipath rather than algorithmic improvement.

## Towed Arrays and Moving Platforms

Check array shape uncertainty, heading error, flow noise, platform motion, temporal nonstationarity, and calibration drift. BTR stability can matter more than single-frame peak sharpness.

## Strong Interference and Low SNR

Evaluate SINR improvement, target preservation, interference-null stability, false target generation, and adaptive-beamformer mismatch sensitivity. MVDR-like methods need explicit robustness checks.

## Real Data Without Truth

Use cautious language. Prioritize:

- consistency across time/frequency,
- known source or vessel priors,
- physical plausibility,
- comparison to baseline CBF,
- operator-visible false tracks,
- repeatability across segments.
