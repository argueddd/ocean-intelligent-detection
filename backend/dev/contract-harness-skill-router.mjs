import assert from 'node:assert/strict'
import test from 'node:test'
import { requestsLineSpectrumDetection } from '../dsh/harness-skill-router/lib/index.js'

test('routes detector-output creation to the missing detector capability', () => {
  for (const prompt of [
    '从波束 PSD 执行线谱检测并生成候选和逐帧 ledger',
    '运行谱线检测，产出门限和帧账本',
    '请创建线谱候选',
  ]) assert.equal(requestsLineSpectrumDetection(prompt), true, prompt)
})

test('does not intercept evaluation or unrelated spectrum work', () => {
  for (const prompt of [
    '评价已有完整 DetectionResult 的检出率和频率误差',
    '评估现有检测结果，不重新检测',
    '检查原始 WAV 的 PSD 和时频图',
    '把 DetectionTrackingHandoff 候选关联成轨迹',
    'dtype 是什么意思？',
  ]) assert.equal(requestsLineSpectrumDetection(prompt), false, prompt)
})
