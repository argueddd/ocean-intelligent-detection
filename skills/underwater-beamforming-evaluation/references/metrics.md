# Beamforming Evaluation Metrics

Use these metrics for underwater acoustic beamforming results. Choose only metrics supported by the available data.

## Data and Scale Conventions

- Treat angular quantities as circular values. Wrap bearing error to the smallest absolute angular difference, e.g. `min(|a-b|, 360-|a-b|)`.
- State whether a spectrum is linear power, amplitude, or dB. Convert consistently before comparing sidelobes.
- For 2D matrices such as `P(f, theta)` or `P(t, theta)`, specify the reduction used before reporting 1D spectrum metrics, such as max over frequency, mean over frequency, or per-frame statistics.
- For multi-target evaluation, first associate estimated peaks with truth bearings, then compute errors. V1 uses gated one-to-one maximum-cardinality matching followed by minimum total angular error; do not assume sorted order is correct and do not use greedy nearest-pair matching.

## DOA and Bearing Accuracy

Use when source truth or a trusted reference is available.

- Bearing error: `e_i = wrap_abs(theta_hat_i - theta_true_i)`.
- MAE: mean absolute bearing error.
- RMSE: square root of mean squared bearing error.
- Bias: signed mean angular error when a consistent sign convention is available.
- Standard deviation: spread of bearing error across trials or time.
- Detection probability: detected target count divided by expected target count across trials.
- Miss rate: missed true targets divided by expected true targets.
- False-alarm rate: false detected peaks divided by trials, frames, or search sectors.
- Track continuity: fraction of frames with valid associated target bearing.

## Spatial Spectrum and Frequency-Bearing Metrics

Use for `P(theta)`, `P(f, theta)`, or broadband collapsed spectra.

- Peak bearing: bearing at the maximum spectrum value.
- Half-power beamwidth (HPBW): angular width around the main peak at `peak - 3 dB`.
- Mainlobe width: width between local minima around the main peak, when identifiable.
- Peak sidelobe level (PSL): largest sidelobe level relative to the main peak in dB.
- Main-to-sidelobe ratio (MSR): main peak minus largest sidelobe in dB.
- Integrated sidelobe level (ISL): total sidelobe power relative to mainlobe power.
- False peak count: number of non-target peaks above a defined relative threshold.
- Dynamic range: main peak level minus background or displayed floor.
- Peak-valley separation: for two targets, lower target peak minus valley between peaks.

Important: Low sidelobes are not sufficient if the main peak is biased, broadened, or unstable.

## BTR and Time-Bearing Metrics

Use for bearing-time records and moving-target displays.

- Track continuity: percentage of frames where the target ridge is present.
- Track smoothness: frame-to-frame bearing difference after association.
- Bearing drift: systematic deviation from expected or manually annotated track.
- Ridge contrast: target ridge level relative to local bearing-time background.
- Track fragmentation: number and length of broken segments.
- False-track count: persistent non-target ridges.

When no ground truth exists, emphasize stability, physical plausibility, and consistency with known platform/source motion.

## Beamformed Signal Metrics

Use when time-domain or spectral beam outputs are available.

- Output SNR: target power divided by noise power at beam output.
- SNR improvement: output SNR minus input SNR in dB.
- Output SINR: target power divided by interference-plus-noise power.
- SINR improvement: output SINR minus input SINR in dB.
- Interference suppression ratio: interference power before/after beamforming in the interference sector or frequency band.
- Array gain: output SNR improvement due to coherent summation.
- Directivity index: directional concentration of array response.
- White-noise gain: robustness proxy for beamformer weights; low WNG indicates sensitivity to sensor noise or mismatch.
- Waveform distortion: correlation, spectral distortion, or amplitude/phase distortion relative to a reference waveform.

## Robustness Metrics

Use for simulations, repeated trials, or parameter sweeps.

- Error versus SNR curve.
- Error versus snapshot count curve.
- Resolution success rate versus target separation.
- Performance versus array position error.
- Performance versus sensor amplitude/phase mismatch.
- Performance versus sound-speed mismatch.
- Performance versus diagonal loading or regularization parameter.
- Runtime versus array size, frequency bins, and frame count.

Report both average performance and worst-case degradation when engineering use is relevant.

## Metric Selection Rules

- With truth: prioritize accuracy, RMSE/MAE, detection/miss/false-alarm rates, and resolution success.
- Without truth: prioritize mainlobe/side-lobe structure, track continuity, stability, background suppression, and physical plausibility.
- With only images: report visual evidence and limitations; do not fabricate exact values.
- For paper evaluation: include fairness of comparison, baselines, ablations, and statistical repeatability.
- For engineering acceptance: include thresholds, operating envelope, failure modes, runtime, and calibration sensitivity.
- A thresholded metric with a missing measured value is insufficient evidence, never a pass. A failed `critical=true` metric cannot be offset by a weighted score.
