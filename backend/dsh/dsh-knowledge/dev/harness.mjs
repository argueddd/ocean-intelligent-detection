/**
 * dsh-knowledge v2 · 契约测试 harness。
 *
 * 每个 dev/contract-*.mjs 用 makeRunner 收集结果、用 makeStack 装配被测栈：
 *  - makeStack 每次调用都新建临时数据目录 + 假引擎，测试之间零共享状态；
 *    可传 { dir, engine } 复用目录/引擎模拟"重启"（同盘重建组件）。
 *  - KB_DATA_DIR 必须在模块加载前设置——curator/analyze 在工厂调用时读它，
 *    动态 import 保证时序。
 *
 * 运行：node dev/contract-intent.mjs（单个）或 node dev/run-tests.mjs（全部）。
 */

import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

export function sleep(ms) { return new Promise((r) => setTimeout(r, ms)) }

export function makeRunner(label) {
  const results = []
  async function check(name, fn) {
    try {
      await fn()
      results.push(['PASS', name])
    } catch (e) {
      results.push(['FAIL', name + ' :: ' + (e && e.message ? e.message : e)])
    }
  }
  function finish() {
    let failed = 0
    console.log('\n===== ' + label + ' =====')
    for (const [s, n] of results) {
      if (s === 'FAIL') failed++
      console.log(' ' + s + '  ' + n)
    }
    console.log(failed ? ' ' + failed + ' FAILED' : ' all passed')
    return failed
  }
  return { check, finish }
}

/**
 * 装配 v2 全栈（假引擎）。返回 { tmp, engine, registry, curator, intents, reconciler, kb, lib }。
 * opts.dir / opts.engine 复用已有目录与引擎（重启模拟）。
 */
export async function makeStack(opts = {}) {
  const dir = opts.dir || fs.mkdtempSync(path.join(os.tmpdir(), 'kb-contract-'))
  process.env.KB_DATA_DIR = dir
  delete process.env.KB_RAG_STORAGE

  const lib = {
    fakeEngine: (await import('../lib/fake-engine.js')).createFakeEngine,
    registry: (await import('../lib/registry.js')).createRegistry,
    curator: (await import('../lib/curator.js')).createCurator,
    intents: (await import('../lib/intent.js')).createIntentLedger,
    reconciler: (await import('../lib/reconciler.js')).createReconciler,
    service: (await import('../lib/service.js')).createKnowledgeService,
    store: await import('../lib/store.js'),
    enginePort: await import('../lib/engine-port.js'),
  }

  const engine = opts.engine || lib.fakeEngine()
  const registry = lib.registry({ dir })
  const curator = lib.curator({ registry })
  const intents = lib.intents({
    dir: path.join(dir, 'intents'),
    engine, registry,
    logger: () => {},
    pollMs: 60 * 60 * 1000, // 手动 tickNow 驱动，不用定时器
    verifyDelayMs: 10,
    trackTimeoutMs: 60 * 1000,
    maxAttempts: 3,
  })
  const reconciler = lib.reconciler({ engine, registry, intents, logger: () => {} })
  const kb = lib.service({ engine, registry, intents, curator, logger: () => {} })
  return { tmp: dir, dir, engine, registry, curator, intents, reconciler, kb, lib }
}

/** 断言辅助 */
export function ok(cond, msg) { if (!cond) throw new Error(msg || 'assertion failed') }
export function eq(a, b, msg) {
  if (a !== b) throw new Error((msg || 'eq') + ': expected ' + JSON.stringify(b) + ', got ' + JSON.stringify(a))
}
export async function throws(fn, match, msg) {
  let err = null
  try { await fn() } catch (e) { err = e }
  if (!err) throw new Error((msg || 'throws') + ': no error thrown')
  if (match && !match.test(String(err && err.message))) {
    throw new Error((msg || 'throws') + ': error "' + err.message + '" does not match ' + match)
  }
  return err
}
