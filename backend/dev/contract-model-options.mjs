/** Exercise the installed SDK adapter and its native provider wire without any remote requests. */
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'
import sharp from 'sharp'
import { apply } from '@deepseek-ai/dsh-llm-pi-ai'
import { createUserMessage } from '@deepseek-ai/dsh-llm'
import { createLaunchEnvironmentSnapshot } from '@deepseek-ai/dsh-launch-environment'
import { prepareHarnessHome, modelReasoningConfig, analyzeImageAttachments } from '../integrations.js'

const mockBase = 'https://sdk-model-options.invalid/v1'

async function fixture(t, variables = {}) {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'ocean-model-options-'))
  const profile = path.join(root, 'dsh/home/profiles/harness')
  await fs.mkdir(profile, { recursive: true })
  await fs.writeFile(path.join(profile, 'package.json'), JSON.stringify({ dependencies: {} }))
  const names = ['LLM_PROVIDER', 'LLM_MODEL', 'LLM_BASE_URL', 'LLM_THINKING', 'VLM_MODEL', 'VLM_BASE_URL', 'VLM_REASONING_EFFORT']
  const previous = Object.fromEntries(names.map(name => [name, process.env[name]]))
  for (const name of names) delete process.env[name]
  Object.assign(process.env, { LLM_BASE_URL: mockBase, VLM_BASE_URL: mockBase, ...variables })
  t.after(async () => {
    for (const name of names) {
      if (previous[name] === undefined) delete process.env[name]
      else process.env[name] = previous[name]
    }
    await fs.rm(root, { recursive: true, force: true })
  })
  const home = path.join(root, 'runtime')
  prepareHarnessHome(home, root, { profile: 'harness' })
  const settings = JSON.parse(await fs.readFile(path.join(home, 'settings.yaml'), 'utf8'))
  const providers = settings['llm-pi-ai'].providers
  let adapter
  apply({
    get(name) {
      if (name === 'credentials') return { resolve: async () => ({ value: 'unused-mock-api-key' }) }
      if (name === 'launchEnvironment') return createLaunchEnvironmentSnapshot([{ source: 'process', values: {} }])
    },
    inject() {},
    logger: { warn() {}, error() {} },
    llm: {
      registerConfigurableProviders: () => ({ replace() {} }),
      registerModelDiscovery() {},
      registerAdapter(_routes, value) { adapter = value; return { replace() {} } },
    },
  }, { providers })
  assert.ok(adapter)
  return { root, settings, providers, adapter }
}

function mockTransport(t) {
  const previous = globalThis.fetch
  const requests = []
  globalThis.fetch = async (input, init) => {
    const url = typeof input === 'string' ? input : String(input.url || input)
    assert.equal(url, mockBase + '/chat/completions', 'only the isolated mock endpoint may be requested')
    requests.push(JSON.parse(init.body))
    const chunk = { id: 'mock-completion', object: 'chat.completion.chunk', created: 0, model: requests.at(-1).model,
      choices: [{ index: 0, delta: { role: 'assistant', content: '模拟答复' }, finish_reason: 'stop' }],
      usage: { prompt_tokens: 10, completion_tokens: 4, total_tokens: 14 } }
    return new Response('data: ' + JSON.stringify(chunk) + '\n\ndata: [DONE]\n\n', {
      status: 200, headers: { 'content-type': 'text/event-stream' },
    })
  }
  t.after(() => { globalThis.fetch = previous })
  return requests
}

async function request(f, route = 'aliyun', reasoningEffort) {
  const model = f.providers[route].models[0].id
  const chunks = []
  for await (const chunk of f.adapter.stream({
    provider: route, model, maxTokens: 8192,
    ...(reasoningEffort === undefined ? {} : { reasoningEffort }),
    messages: [createUserMessage({ content: [{ type: 'text', text: '你好' }], source: { kind: 'human' } })],
  })) chunks.push(chunk)
  assert.equal(chunks.findLast(chunk => chunk.type === 'finish')?.reason.kind, 'stop')
  assert.ok(chunks.some(chunk => chunk.type === 'text-delta' && chunk.text === '模拟答复'))
}

test('default Qwen text route sends explicit enable_thinking=false through the native SDK', async t => {
  const f = await fixture(t)
  const requests = mockTransport(t)
  await request(f)
  assert.equal(requests.length, 1)
  assert.equal(requests[0].model, 'qwen3.8-flash')
  assert.equal(requests[0].enable_thinking, false)
  assert.ok(!('reasoning_effort' in requests[0]))
  assert.ok(!('extra_body' in requests[0]))
})

test('explicit LLM_THINKING=true enables Qwen while SDK off still disables it', async t => {
  const f = await fixture(t, { LLM_THINKING: 'true' })
  const requests = mockTransport(t)
  await request(f)
  await request(f, 'aliyun', 'off')
  assert.deepEqual(requests.map(body => body.enable_thinking), [true, false])
})

test('a native SDK low override enables thinking when the default is off', async t => {
  const f = await fixture(t, { LLM_THINKING: 'false' })
  const requests = mockTransport(t)
  await request(f, 'aliyun', 'low')
  assert.equal(requests[0].enable_thinking, true)
  assert.ok(!('reasoning_effort' in requests[0]))
})

test('default Omni route disables thinking using reasoning_effort=none, never enable_thinking', async t => {
  const f = await fixture(t)
  const requests = mockTransport(t)
  await request(f, 'aliyun-vision')
  assert.equal(requests[0].model, 'qwen3.8-omni-flash')
  assert.equal(requests[0].reasoning_effort, 'none')
  assert.ok(!('enable_thinking' in requests[0]))
  assert.ok(!('extra_body' in requests[0]))
})

test('explicit Omni xhigh and SDK off use the model-specific wire values', async t => {
  const f = await fixture(t, { VLM_REASONING_EFFORT: 'xhigh' })
  const requests = mockTransport(t)
  await request(f, 'aliyun-vision')
  await request(f, 'aliyun-vision', 'off')
  assert.deepEqual(requests.map(body => body.reasoning_effort), ['xhigh', 'none'])
  assert.ok(requests.every(body => !('enable_thinking' in body)))
})

test('using Omni on the main route still applies LLM_THINKING with Omni wire semantics', async t => {
  const f = await fixture(t, { LLM_MODEL: 'qwen3.8-omni-flash', LLM_THINKING: 'true' })
  const requests = mockTransport(t)
  await request(f)
  assert.equal(requests[0].reasoning_effort, 'xhigh')
  assert.ok(!('enable_thinking' in requests[0]))
})

test('unsupported SDK effort fails before any provider request', async t => {
  const f = await fixture(t)
  const requests = mockTransport(t)
  await assert.rejects(async () => {
    for await (const _ of f.adapter.stream({ provider: 'aliyun', model: 'qwen3.8-flash', reasoningEffort: 'high', messages: [] })) {}
  }, { code: 'UNSUPPORTED_REASONING_EFFORT' })
  assert.equal(requests.length, 0)
})

test('invalid public thinking settings fail clearly instead of silently ignoring intent', async t => {
  await t.test('invalid text setting', async t => {
    await assert.rejects(fixture(t, { LLM_THINKING: 'sometimes' }), /LLM_THINKING/)
  })
  await t.test('invalid Omni setting', async t => {
    await assert.rejects(fixture(t, { VLM_REASONING_EFFORT: 'low' }), /VLM_REASONING_EFFORT/)
  })
})

test('unrecognized model families retain their existing generic declaration', () => {
  assert.deepEqual(modelReasoningConfig('custom-text-model'), {
    reasoningEfforts: false, compat: { supportsReasoningEffort: false },
  })
})

test('legacy attachment vision call also sends the correct Omni thinking switch', async t => {
  const f = await fixture(t)
  const previous = process.env.VLM_API_KEY
  process.env.VLM_API_KEY = 'unused-mock-api-key'
  t.after(() => { if (previous === undefined) delete process.env.VLM_API_KEY; else process.env.VLM_API_KEY = previous })
  const image = path.join(f.root, 'image.png')
  await fs.writeFile(image, await sharp({ create: { width: 8, height: 4, channels: 3, background: '#ffffff' } }).png().toBuffer())
  const previousFetch = globalThis.fetch
  let body
  globalThis.fetch = async (url, init) => {
    assert.equal(url, mockBase + '/chat/completions')
    body = JSON.parse(init.body)
    return Response.json({ choices: [{ message: { content: '模拟图片观察' } }] })
  }
  t.after(() => { globalThis.fetch = previousFetch })
  const answer = await analyzeImageAttachments([image], '检查图表')
  assert.ok(answer.includes('模拟图片观察'))
  assert.equal(body.reasoning_effort, 'none')
  assert.ok(!('enable_thinking' in body))
})
