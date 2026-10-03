import argparse
import hashlib
import json
from pathlib import Path
import sys
import numpy as np
import yaml

parser = argparse.ArgumentParser()
parser.add_argument('--input', required=True)
parser.add_argument('--output', required=True)
parser.add_argument('--sample-rate', type=float)
parser.add_argument('--metadata')
args = parser.parse_args()
if args.metadata and args.sample_rate is None:
    metadata = yaml.safe_load(Path(args.metadata).read_text()) or {}
    args.sample_rate = metadata.get('sample_rate_hz')
if args.sample_rate is not None and args.sample_rate <= 0:
    parser.error('sample rate must be positive')
source = Path(args.input).resolve()
data = np.loadtxt(source, delimiter=',', ndmin=2)
constant = []
for channel in range(data.shape[1]):
    values = data[:, channel]
    finite = values[np.isfinite(values)]
    if finite.size and np.ptp(finite) <= 1e-12:
        constant.append(channel)
report = {
    'skill': 'harness-probe-data-health',
    'python_executable': sys.executable,
    'input_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
    'shape': list(data.shape),
    'non_finite_count': int(np.count_nonzero(~np.isfinite(data))),
    'constant_channels': constant,
    'sample_rate_hz': args.sample_rate,
    'missing_parameters': [] if args.sample_rate is not None else ['sample_rate_hz'],
}
output = Path(args.output)
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
print(json.dumps(report, ensure_ascii=False))
