import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import numpy as np
from scipy import signal

parser = argparse.ArgumentParser()
parser.add_argument('--input', required=True)
parser.add_argument('--output', required=True)
parser.add_argument('--sample-rate', required=True, type=float)
parser.add_argument('--method', required=True, choices=['periodogram', 'welch'])
parser.add_argument('--resolution', type=float, default=1.0)
args = parser.parse_args()
if args.sample_rate <= 0 or args.resolution <= 0:
    parser.error('sample rate and resolution must be positive')
source = Path(args.input).resolve()
data = np.loadtxt(source, delimiter=',', ndmin=2)
if data.shape[1] != 1 or data.shape[0] < 4 or not np.isfinite(data).all():
    parser.error('expected at least 4 finite samples in one channel')
x = data[:, 0]
nperseg = min(x.size, math.ceil(args.sample_rate / args.resolution)) if args.method == 'welch' else x.size
noverlap = nperseg // 2 if args.method == 'welch' else 0
segment_count = 1 + (x.size - nperseg) // (nperseg - noverlap)
if args.method == 'welch':
    frequencies, power = signal.welch(x, fs=args.sample_rate, nperseg=nperseg, noverlap=noverlap)
else:
    frequencies, power = signal.periodogram(x, fs=args.sample_rate)
peaks, _ = signal.find_peaks(power)
top = peaks[np.argsort(power[peaks])[-2:]]
report = {
    'skill': 'harness-probe-spectrum',
    'python_executable': sys.executable,
    'input_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
    'sample_rate_hz': args.sample_rate,
    'sample_count': int(x.size),
    'method': args.method,
    'derived_parameters': {'nperseg': int(nperseg), 'noverlap': int(noverlap), 'segment_count': int(segment_count), 'frequency_resolution_hz': args.sample_rate / nperseg},
    'peak_frequencies_hz': sorted(float(frequencies[i]) for i in top),
}
output = Path(args.output)
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report))
