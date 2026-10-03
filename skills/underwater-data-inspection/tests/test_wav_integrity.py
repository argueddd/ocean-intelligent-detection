"""RIFF boundaries and PCM frame integrity, without private wave attributes."""
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import wave
import numpy as np
from scipy.io import wavfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from acoustic_inspection.pipeline import execute
from acoustic_inspection.readers import probe


def chunk(tag, data, pad=True):
    return tag + struct.pack('<I', len(data)) + data + (b'\0' if pad and len(data) % 2 else b'')


def fmt(channels=2, width=2, block_align=None):
    frame = channels * width
    return struct.pack('<HHIIHH', 1, channels, 1000, 1000 * frame,
                       frame if block_align is None else block_align, width * 8)


def riff(*chunks):
    body = b'WAVE' + b''.join(chunks)
    return b'RIFF' + struct.pack('<I', len(body)) + body


class WavIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='wav-integrity-')
        self.root = Path(self.temp.name)
        self.serial = 0

    def tearDown(self):
        self.temp.cleanup()

    def run_bytes(self, payload):
        self.serial += 1
        source = self.root / f'input{self.serial}.wav'
        source.write_bytes(payload)
        out = self.root / f'out{self.serial}'
        result = execute(source, out, {})
        return source, out, result

    def blocked(self, result, code):
        self.assertEqual(result['status'], 'needs_input', result['issues'])
        self.assertIn(code, [i['code'] for i in result['issues']])
        self.assertNotIn('dataset', result)
        self.assertNotIn('quality', result)
        checks = {c['id']: c for c in result['checks']}
        self.assertEqual(checks['probe.container']['status'], 'blocked')
        self.assertEqual(checks['reading.samples']['status'], 'blocked')

    def test_partial_stereo_frame_is_rejected_instead_of_dropping_samples(self):
        _, _, result = self.run_bytes(riff(chunk(b'fmt ', fmt()),
                                          chunk(b'data', np.arange(129, dtype='<i2').tobytes())))
        self.blocked(result, 'wav_partial_frame')

    def test_single_byte_tail_is_rejected_for_pcm16(self):
        _, _, result = self.run_bytes(riff(chunk(b'fmt ', fmt(channels=1)),
                                          chunk(b'data', b'\0' * 33)))
        self.blocked(result, 'wav_partial_frame')

    def test_truncated_declared_data_is_rejected_during_probe(self):
        valid = riff(chunk(b'fmt ', fmt()), chunk(b'data', b'\0' * 256))
        source, _, result = self.run_bytes(valid[:-4])
        self.blocked(result, 'truncated_wav')
        with self.assertRaisesRegex(ValueError, 'WAV|RIFF'):
            probe(source)

    def test_truncated_unknown_chunk_is_not_hidden_after_valid_audio(self):
        payload = riff(chunk(b'fmt ', fmt()), chunk(b'data', b'\0' * 256),
                       b'JUNK' + struct.pack('<I', 12) + b'1234')
        _, _, result = self.run_bytes(payload)
        self.blocked(result, 'truncated_wav')

    def test_chunk_header_must_be_complete_within_riff(self):
        payload = riff(chunk(b'fmt ', fmt()), chunk(b'data', b'\0' * 256), b'JU')
        _, _, result = self.run_bytes(payload)
        self.blocked(result, 'truncated_wav')

    def test_inconsistent_pcm_block_alignment_is_rejected(self):
        _, _, result = self.run_bytes(riff(chunk(b'fmt ', fmt(block_align=2)),
                                          chunk(b'data', b'\0' * 256)))
        self.blocked(result, 'invalid_wav_frame')

    def test_duplicate_data_chunks_do_not_hide_extra_audio(self):
        _, _, result = self.run_bytes(riff(chunk(b'fmt ', fmt()),
                                          chunk(b'data', b'\0' * 256), chunk(b'data', b'\0' * 256)))
        self.blocked(result, 'unsupported_wav')

    def test_nonstandard_pcm_bit_depth_is_not_rounded_up(self):
        header = struct.pack('<HHIIHH', 1, 2, 1000, 4000, 4, 15)
        _, _, result = self.run_bytes(riff(chunk(b'fmt ', header), chunk(b'data', b'\0' * 256)))
        self.blocked(result, 'unsupported_wav')

    def test_zero_sample_rate_is_rejected_during_probe(self):
        header = struct.pack('<HHIIHH', 1, 2, 0, 0, 4, 16)
        _, _, result = self.run_bytes(riff(chunk(b'fmt ', header), chunk(b'data', b'\0' * 256)))
        self.blocked(result, 'invalid_wav_header')

    def test_byte_rate_conflict_is_not_silently_ignored(self):
        header = struct.pack('<HHIIHH', 1, 2, 1000, 1, 4, 16)
        _, _, result = self.run_bytes(riff(chunk(b'fmt ', header), chunk(b'data', b'\0' * 256)))
        self.blocked(result, 'invalid_wav_header')

    def test_pcm_format_extension_remains_supported(self):
        header = fmt() + struct.pack('<H', 0)
        _, _, result = self.run_bytes(riff(chunk(b'fmt ', header), chunk(b'data', b'\0' * 256)))
        self.assertEqual(result['status'], 'completed', result['issues'])
        layout = result['probe']['wav_layout']
        self.assertEqual(layout['bits_per_sample'], 16)
        self.assertEqual(layout['sample_rate_hz'], 1000)
        self.assertEqual(layout['byte_rate'], 4000)

    @unittest.skipIf(sys.version_info < (3, 12), 'stdlib wave supports PCM extensible from Python 3.12')
    def test_pcm_extensible_format_remains_supported(self):
        header = struct.pack('<HHIIHH', 0xfffe, 2, 1000, 4000, 4, 16)
        pcm_guid = bytes.fromhex('0100000000001000800000aa00389b71')
        header += struct.pack('<HHI', 22, 16, 3) + pcm_guid
        _, _, result = self.run_bytes(riff(chunk(b'fmt ', header), chunk(b'data', b'\0' * 256)))
        self.assertEqual(result['status'], 'completed', result['issues'])
        self.assertEqual(result['dataset']['original_dtype'], 'int16')
        self.assertEqual(result['probe']['wav_layout']['audio_format_code'], 0xfffe)

    def test_unknown_chunks_and_odd_padding_preserve_pcm_values(self):
        x = np.arange(128, dtype='<i2').reshape(64, 2)
        payload = riff(chunk(b'JUNK', b'abc'), chunk(b'fmt ', fmt()), chunk(b'LIST', b'INFOabc'),
                       chunk(b'data', x.tobytes()), chunk(b'abcd', b'hello'))
        _, _, result = self.run_bytes(payload)
        self.assertEqual(result['status'], 'completed', result['issues'])
        self.assertEqual(result['dataset']['original_shape'], [64, 2])
        self.assertEqual(result['quality']['channels'][1]['mean'], float(x[:, 1].mean()))

    def test_standard_wave_and_scipy_pcm_writers_remain_supported(self):
        for dtype, width in [('uint8', 1), ('int16', 2), ('int32', 4)]:
            for channels in [1, 2]:
                for writer in ['wave', 'scipy']:
                    with self.subTest(dtype=dtype, channels=channels, writer=writer):
                        self.serial += 1
                        x = np.arange(33 * channels, dtype=dtype).reshape(33, channels)
                        source = self.root / f'writer{self.serial}.wav'
                        if writer == 'scipy':
                            wavfile.write(source, 1000, x[:, 0] if channels == 1 else x)
                        else:
                            with wave.open(str(source), 'wb') as handle:
                                handle.setnchannels(channels)
                                handle.setsampwidth(width)
                                handle.setframerate(1000)
                                handle.writeframes(x.astype(np.dtype(dtype).newbyteorder('<')).tobytes())
                        result = execute(source, self.root / f'writer-out{self.serial}', {})
                        self.assertEqual(result['status'], 'completed', result['issues'])
                        self.assertEqual(result['dataset']['original_shape'], [33, channels])
                        for ch in range(channels):
                            self.assertEqual(result['quality']['channels'][ch]['sample_count'], 33)
                            self.assertEqual(result['quality']['channels'][ch]['mean'], float(x[:, ch].mean()))


if __name__ == '__main__':
    unittest.main()
