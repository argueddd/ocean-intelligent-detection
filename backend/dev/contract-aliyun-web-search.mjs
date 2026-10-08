import assert from 'node:assert/strict'
import fs from 'node:fs'
import http from 'node:http'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { ALIYUN_WEB_SEARCH_PROVIDER_ID, AliyunWebSearchProvider, mapResponsesResult, responsesEndpoint } from '../dsh/harness-web-search/lib/index.js'

const backend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
assert.equal(ALIYUN_WEB_SEARCH_PROVIDER_ID, 'aliyun-bailian')
assert.equal(responsesEndpoint('https://example.cn/compatible-mode/v1/'), 'https://example.cn/compatible-mode/v1/responses')

const normalized = mapResponsesResult({ output: [
  { type: 'web_search_call', action: { sources: [
    { url: 'https://example.com/a', title: '来源 A' },
    { url: 'https://example.com/a', title: '重复来源' },
  ] } },
  { type: 'message', content: [{ type: 'output_text', text: '联网摘要', annotations: [
    { type: 'url_citation', url: 'https://example.com/b', title: '来源 B' },
  ] }] },
] })
assert.equal(normalized.content, '联网摘要')
assert.deepEqual(normalized.sources.map(source => source.url), ['https://example.com/a', 'https://example.com/b'])

let captured
const server = http.createServer(async (request, response) => {
  const chunks = []
  for await (const chunk of request) chunks.push(chunk)
  captured = { method: request.method, url: request.url, authorization: request.headers.authorization, body: JSON.parse(Buffer.concat(chunks).toString('utf8')) }
  response.writeHead(200, { 'content-type': 'application/json' })
  response.end(JSON.stringify({ output: [
    { type: 'web_search_call', action: { sources: [{ url: 'https://help.aliyun.com/example', title: '阿里云文档' }] } },
    { type: 'message', content: [{ type: 'output_text', text: '测试结果', annotations: [] }] },
  ] }))
})
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
try {
  const provider = new AliyunWebSearchProvider(() => ({
    apiKey: 'contract-secret', apiKeyEnv: 'LLM_API_KEY',
    baseURL: `http://127.0.0.1:${server.address().port}/compatible-mode/v1`,
    model: 'qwen3.8-flash', maxTokens: 512,
  }))
  assert.equal(provider.available(), true)
  const result = await provider.search({ query: '阿里云联网搜索', maxResults: 3 })
  assert.equal(result.sources[0].url, 'https://help.aliyun.com/example')
  assert.equal(captured.method, 'POST')
  assert.equal(captured.url, '/compatible-mode/v1/responses')
  assert.equal(captured.authorization, 'Bearer contract-secret')
  assert.equal(captured.body.model, 'qwen3.8-flash')
  assert.deepEqual(captured.body.tools, [{ type: 'web_search' }])
  assert.match(captured.body.input, /阿里云联网搜索/)
} finally {
  await new Promise((resolve, reject) => server.close(error => error ? reject(error) : resolve()))
}

const missingCredential = new AliyunWebSearchProvider(() => ({
  resolveApiKey: async () => undefined, apiKeyEnv: 'LLM_API_KEY',
  baseURL: 'https://example.cn/compatible-mode/v1', model: 'qwen3.8-flash', maxTokens: 512,
}))
await assert.rejects(() => missingCredential.search({ query: 'test' }), error => error?.code === 'WEB_PROVIDER_CREDENTIAL_MISSING' && /LLM_API_KEY/.test(error.message))

const profile = JSON.parse(fs.readFileSync(path.join(backend, 'dsh/home/profiles/harness/package.json'), 'utf8'))
assert.equal(profile.dependencies['ocean-harness-web-search'], 'link:../../../harness-web-search')
assert.ok(profile.dsh.profile.bundles.includes('ocean-harness-web-search'))
const patch = fs.readFileSync(path.join(backend, 'dsh/home/profiles/harness/cordis.patch.yml'), 'utf8')
assert.match(patch, /WEB_SEARCH_PROVIDER[\s\S]*?deepseek-official[\s\S]*?aliyun-bailian/)
assert.doesNotMatch(patch, /id: web-search-deepseek[\s\S]*?disabled: true/)
assert.match(patch, /apiKeyEnv: LLM_API_KEY/)
console.log('Aliyun web-search provider contracts passed.')
