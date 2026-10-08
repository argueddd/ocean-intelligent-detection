import z from '@deepseek-ai/schemastery'
import { credentialRef } from '@deepseek-ai/dsh-credentials'
import { launchEnvironmentOf } from '@deepseek-ai/dsh-launch-environment'
import { WebError } from '@deepseek-ai/dsh-web'

export const name = 'ocean-harness-web-search'
export const inject = ['web']
export const ALIYUN_WEB_SEARCH_PROVIDER_ID = 'aliyun-bailian'

const DEFAULT_API_KEY_ENV = 'LLM_API_KEY'
const DEFAULT_MODEL = 'qwen3.8-flash'
const DEFAULT_MAX_TOKENS = 2048

export const Config = z.object({
  apiKey: z.string().role('secret'),
  apiKeyEnv: z.string().role('credential-ref').default(DEFAULT_API_KEY_ENV),
  baseURL: z.string(),
  model: z.string().default(DEFAULT_MODEL),
  maxTokens: z.number().step(1).min(1).default(DEFAULT_MAX_TOKENS),
})

const cleanText = value => typeof value === 'string' && value.trim() ? value.trim() : undefined
const isAbortError = error => error instanceof DOMException && error.name === 'AbortError'
const aborted = (signal, fallback) => new WebError('阿里云联网搜索已取消', 'WEB_ABORTED', { cause: signal?.aborted ? signal.reason : fallback })

function throwIfAborted(signal) {
  if (signal?.aborted) throw aborted(signal)
}

export function responsesEndpoint(baseURL) {
  const url = new URL(baseURL)
  url.pathname = url.pathname.replace(/\/+$/, '')
  if (!url.pathname.endsWith('/responses')) url.pathname += '/responses'
  return url.toString()
}

function sourceFrom(value) {
  if (typeof value === 'string') return URL.canParse(value) ? { url: value } : undefined
  if (!value || typeof value !== 'object') return undefined
  const citation = value.url_citation && typeof value.url_citation === 'object' ? value.url_citation : value
  const url = cleanText(citation.url)
  if (!url || !URL.canParse(url)) return undefined
  const title = cleanText(citation.title)
  const snippet = cleanText(citation.snippet ?? citation.text ?? citation.description)
  const publishedAt = cleanText(citation.published_at ?? citation.publishedAt ?? citation.date)
  return { url, ...(title ? { title } : {}), ...(snippet ? { snippet } : {}), ...(publishedAt ? { publishedAt } : {}) }
}

function appendSource(target, seen, value) {
  const source = sourceFrom(value)
  if (!source || seen.has(source.url)) return
  seen.add(source.url)
  target.push(source)
}

/** Normalize Bailian Responses output while retaining only provider-supplied citation facts. */
export function mapResponsesResult(response) {
  const sources = []
  const seen = new Set()
  const text = []
  for (const item of Array.isArray(response?.output) ? response.output : []) {
    for (const source of item?.action?.sources ?? []) appendSource(sources, seen, source)
    for (const source of item?.sources ?? []) appendSource(sources, seen, source)
    for (const part of Array.isArray(item?.content) ? item.content : []) {
      const outputText = cleanText(part?.text)
      if (part?.type === 'output_text' && outputText) text.push(outputText)
      for (const annotation of part?.annotations ?? []) appendSource(sources, seen, annotation)
    }
  }
  const topLevelText = cleanText(response?.output_text)
  if (topLevelText && !text.includes(topLevelText)) text.push(topLevelText)
  if (!sources.length) throw new WebError('阿里云百炼未返回联网搜索来源；请确认 WEB_SEARCH_MODEL 支持 Responses API 的 web_search 工具', 'WEB_PROVIDER_ERROR')
  const content = cleanText(text.join('\n\n'))
  return { ...(content ? { content } : {}), sources, truncated: false }
}

export class AliyunWebSearchProvider {
  id = ALIYUN_WEB_SEARCH_PROVIDER_ID

  constructor(resolveOptions) {
    this.resolveOptions = resolveOptions
  }

  available() {
    const options = this.resolveOptions()
    return Boolean(((options.apiKey?.length ?? 0) > 0 || options.resolveApiKey) && URL.canParse(options.baseURL) && cleanText(options.model) && Number.isSafeInteger(options.maxTokens) && options.maxTokens > 0)
  }

  async apiKey(options, signal) {
    throwIfAborted(signal)
    if (cleanText(options.apiKey)) return options.apiKey
    let resolved
    try {
      resolved = await options.resolveApiKey?.()
    } catch (error) {
      if (signal?.aborted || isAbortError(error)) throw aborted(signal, error)
      throw new WebError(`阿里云联网搜索凭据读取失败：${String(error)}`, 'WEB_PROVIDER_ERROR', { cause: error })
    }
    throwIfAborted(signal)
    if (cleanText(resolved)) return resolved
    throw new WebError(`阿里云联网搜索缺少 ${options.apiKeyEnv || DEFAULT_API_KEY_ENV}；它默认与主模型复用同一个密钥`, 'WEB_PROVIDER_CREDENTIAL_MISSING')
  }

  async search(request, signal) {
    const options = this.resolveOptions()
    const apiKey = await this.apiKey(options, signal)
    const endpoint = responsesEndpoint(options.baseURL)
    const body = {
      model: options.model,
      input: `请使用联网搜索查找以下内容，并仅依据搜索结果简洁作答：${request.query}`,
      tools: [{ type: 'web_search' }],
      store: false,
      max_output_tokens: options.maxTokens,
    }
    options.recordRequest?.({ endpoint, model: options.model, query: request.query })
    throwIfAborted(signal)
    let response
    try {
      response = await fetch(endpoint, {
        method: 'POST', redirect: 'error',
        headers: { authorization: `Bearer ${apiKey}`, 'content-type': 'application/json', accept: 'application/json', 'user-agent': 'ocean-intelligent-detection/1.0' },
        body: JSON.stringify(body), ...(signal ? { signal } : {}),
      })
    } catch (error) {
      if (signal?.aborted || isAbortError(error)) throw aborted(signal, error)
      throw new WebError(`阿里云联网搜索请求失败：${String(error)}`, 'WEB_PROVIDER_ERROR', { cause: error })
    }
    if (!response.ok) {
      let detail = ''
      try {
        const parsed = await response.json()
        detail = cleanText(parsed?.error?.message ?? parsed?.message) ?? ''
      } catch (error) {
        if (signal?.aborted || isAbortError(error)) throw aborted(signal, error)
      }
      throw new WebError(`阿里云联网搜索返回 HTTP ${response.status}${detail ? `：${detail}` : ''}`, 'WEB_PROVIDER_ERROR')
    }
    try {
      return mapResponsesResult(await response.json())
    } catch (error) {
      if (signal?.aborted || isAbortError(error)) throw aborted(signal, error)
      if (error instanceof WebError) throw error
      throw new WebError(`阿里云联网搜索响应无法解析：${String(error)}`, 'WEB_PROVIDER_ERROR', { cause: error })
    }
  }
}

function resolveOptions(ctx, config) {
  const apiKeyEnv = credentialRef(config.apiKeyEnv ?? DEFAULT_API_KEY_ENV)
  const literalApiKey = cleanText(config.apiKey)
  return {
    ...(literalApiKey ? { apiKey: literalApiKey } : {}),
    resolveApiKey: async () => {
      const credentials = ctx.get('credentials')
      if (credentials) return (await credentials.resolve(apiKeyEnv))?.value
      return launchEnvironmentOf(ctx).get(apiKeyEnv)?.value
    },
    apiKeyEnv,
    baseURL: config.baseURL ?? launchEnvironmentOf(ctx).get('LLM_BASE_URL')?.value ?? '',
    model: config.model ?? launchEnvironmentOf(ctx).get('WEB_SEARCH_MODEL')?.value ?? launchEnvironmentOf(ctx).get('LLM_MODEL')?.value ?? DEFAULT_MODEL,
    maxTokens: config.maxTokens ?? (Number(launchEnvironmentOf(ctx).get('WEB_SEARCH_MAX_TOKENS')?.value) || DEFAULT_MAX_TOKENS),
    recordRequest: request => ctx.get('agents')?.currentInitiator()?.session.append('web/aliyun-search-request', request),
  }
}

export function apply(ctx, config = {}) {
  ctx.web.registerSearchProvider(new AliyunWebSearchProvider(() => resolveOptions(ctx, config)))
}
