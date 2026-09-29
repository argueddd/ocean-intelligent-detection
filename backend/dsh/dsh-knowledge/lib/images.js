/**
 * dsh-knowledge · 图文关联（原图定位、chunk 注入与展示转换）。
 *
 * LightRAG 多模态解析后图片与 chunk 的关联只有两条通道（对照 qa-assistant
 * 参考实现，机制详见 docs/重构后功能说明.md）：
 *  1. 普通 chunk：content 里的自闭合 <drawing path="..."/> 占位符标注
 *     "图在哪"，可定位到图片文件时原地替换为 Markdown 图片链接；
 *  2. mm chunk（chunk id 形如 doc-<hash>-mm-drawing-<NNN>）：content 是
 *     VLM 写的图片语义描述，不带占位符，按末尾序号反查 .drawings.json
 *     拿到图片路径后追加图片链接。
 *
 * 反查三级校验（文档重解析会轮换 doc id 并覆盖 .parsed，chunk hash 与
 * 磁盘 drawings.json 常常错位，宁可不给图、不给错图）：
 *  1. hash 前缀一致（最强）；
 *  2. chunk 的 [Image Name] 与条目 VLM 名称归一化后相等；
 *  3. 名称相似度 ≥ 0.75（difflib SequenceMatcher 语义，处理"标志/徽标"
 *     类措辞漂移）。
 *
 * 边界与降级：
 *  - 未配置 KB_LIGHTRAG_INPUTS_DIR（或 urlBase 不可用）时注入直通，
 *    行为与无本模块时一致；
 *  - 解析结果强制约束在 __parsed__ 根目录内，挡住 ../ 路径穿越；
 *  - EMF/WMF 浏览器不可渲染，经 libreoffice headless 转 PNG（缓存
 *    key=路径+mtime），libreoffice 不可用或转换失败时降级返回原文件。
 */

import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import crypto from 'node:crypto'
import { spawn } from 'node:child_process'

/** 自闭合 <drawing .../> 标签（与 qa-assistant/LightRAG 解析规则一致）。 */
const DRAWING_TAG_RE = /<drawing\b([^>]*?)\s*\/>/gi
/** 标签属性对。 */
const TAG_ATTR_RE = /(\w+)\s*=\s*"((?:[^"\\]|\\.)*)"/g
/** .parsed 目录内的图片资源目录后缀。 */
const ASSETS_DIR_SUFFIX = '.blocks.assets'
/** mm-drawing chunk id：末尾三位是 drawings.json "drawings" 字典的插入序号。 */
const MM_DRAWING_CHUNK_RE = /^doc-([0-9a-fA-F]+)-mm-drawing-(\d{3})$/
/**
 * mm-drawing chunk content 首行携带 VLM 识别的图片名。
 * 名称捕获在 [Image Type] 或行尾停止：调用方可能已把多行 content
 * 压成单行（渲染裁剪），贪婪匹配会把整段描述吞进图片名。
 */
const MM_IMAGE_NAME_RE = /^\[Image Name\](.+?)(?=\s*\[Image Type\]|$)/m

/** 图片 MIME（按扩展名）。 */
const IMAGE_MEDIA_TYPES = {
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.gif': 'image/gif',
  '.bmp': 'image/bmp',
  '.webp': 'image/webp',
  '.svg': 'image/svg+xml',
}
/** 浏览器不可原生渲染、需经 libreoffice 转 PNG 的扩展名。 */
const CONVERTIBLE_EXTS = new Set(['.emf', '.wmf'])
/** libreoffice 转换超时与缓存目录（重启可重建）。 */
const CONVERT_TIMEOUT_MS = 60000

/**
 * difflib SequenceMatcher.ratio() 的等价实现（Ratcliff/Obershelp：
 * 递归最长公共子串计入匹配字符 M，ratio = 2M/(len(a)+len(b))）。
 * 三级校验第 3 级的 0.75 阈值按该口径调定，勿换其他相似度度量。
 * @param {string} a - 比较串一。
 * @param {string} b - 比较串二。
 * @returns {number} 0-1 相似度。
 */
export function similarityRatio(a, b) {
  if (!a || !b) return a === b ? 1 : 0
  const matched = (i1, i2, j1, j2) => {
    let best = 0
    let bi = i1
    let bj = j1
    for (let i = i1; i < i2; i++) {
      for (let j = j1; j < j2; j++) {
        let k = 0
        while (i + k < i2 && j + k < j2 && a[i + k] === b[j + k]) k++
        if (k > best) { best = k; bi = i; bj = j }
      }
    }
    if (best <= 0) return 0
    return best + matched(i1, bi, j1, bj) + matched(bi + best, i2, bj + best, j2)
  }
  return (2 * matched(0, a.length, 0, b.length)) / (a.length + b.length)
}

/** resolved 是否落在 root 目录内（防路径穿越的统一判定）。 */
function inside(root, resolved) {
  const rel = path.relative(root, resolved)
  return rel === '' || (rel !== '..' && !rel.startsWith('..' + path.sep) && !path.isAbsolute(rel))
}

/**
 * 创建图文关联器。
 *
 * @param {object} [opts]
 * @param {string|null} [opts.inputsDir] - LightRAG inputs 根目录（含 __parsed__）；
 *   缺省读 KB_LIGHTRAG_INPUTS_DIR，未配置时整体禁用。
 * @param {function():string|null} [opts.urlBase] - 惰性取图片服务的绝对 URL 前缀
 *   （如 http://127.0.0.1:3080）；为 null 时注入直通。渲染期才调用，
 *   避免启动早期 webServer 尚未监听。
 * @param {string} [opts.sofficeBin] - libreoffice 可执行文件，默认 libreoffice。
 * @param {string} [opts.cacheDir] - EMF/WMF 转 PNG 缓存目录，默认系统临时目录。
 * @param {function(string):void} [opts.log] - 诊断日志（转换失败等低频事件）。
 */
export function createImageLinker(opts = {}) {
  const inputsDir = opts.inputsDir !== undefined ? opts.inputsDir : (process.env.KB_LIGHTRAG_INPUTS_DIR || null)
  const urlBaseFn = opts.urlBase || (() => null)
  const sofficeBin = opts.sofficeBin || 'libreoffice'
  const cacheDir = opts.cacheDir || path.join(os.tmpdir(), 'dsh-kb-image-cache')
  const log = opts.log || (() => {})
  const root = inputsDir ? path.resolve(inputsDir, '__parsed__') : null
  const enabled = !!(root && fs.existsSync(root) && fs.statSync(root).isDirectory())

  // .parsed 目录定位缓存（bounded：超限整体清空重建）
  const parsedDirCache = new Map()

  /** 在 __parsed__/ 下定位文档的解析目录（磁盘目录名可能带类别前缀，按后缀匹配）。 */
  function findParsedDir(docFilePath) {
    if (!enabled || !docFilePath) return null
    if (parsedDirCache.has(docFilePath)) return parsedDirCache.get(docFilePath)
    let found = null
    const exact = path.join(root, docFilePath + '.parsed')
    if (fs.existsSync(exact) && fs.statSync(exact).isDirectory()) {
      found = exact
    } else {
      const suffix = '_' + docFilePath + '.parsed'
      let entries = []
      try { entries = fs.readdirSync(root, { withFileTypes: true }) } catch (e) { return null }
      for (const entry of entries) {
        if (!entry.isDirectory() || !entry.name.endsWith(suffix)) continue
        found = path.join(root, entry.name)
        break
      }
    }
    if (parsedDirCache.size > 2048) parsedDirCache.clear()
    parsedDirCache.set(docFilePath, found)
    return found
  }

  /** parsed 目录内唯一的 .blocks.assets 资源目录。 */
  function assetsDirOf(parsedDir) {
    let entries = []
    try { entries = fs.readdirSync(parsedDir, { withFileTypes: true }) } catch (e) { return null }
    for (const entry of entries) {
      if (entry.isDirectory() && entry.name.endsWith(ASSETS_DIR_SUFFIX)) {
        return path.join(parsedDir, entry.name)
      }
    }
    return null
  }

  /** 候选路径可解析为 __parsed__ 内的普通文件才有效。 */
  function fileInside(parsedDir, candidate) {
    let resolved
    try { resolved = path.resolve(candidate) } catch (e) { return null }
    let st = null
    try { st = fs.statSync(resolved) } catch (e) { return null }
    if (!st.isFile() || !inside(root, resolved)) return null
    return resolved
  }

  /**
   * 把 chunk 中的 <drawing path="..."> 解析为磁盘图片文件。
   * path 有两种形态：相对 .parsed 的路径（含 .blocks.assets/）或纯文件名
   * （此时定位 .parsed 下唯一的 assets 目录）。path 不带前缀但磁盘目录带
   * （裸名入库后带前缀重解析）时按文件名回退查找。
   * @returns {string|null} 绝对路径；无法定位为 null。
   */
  function resolveFile(docFilePath, drawingPath) {
    if (!enabled || !drawingPath) return null
    if (/^(https?:)?\/\//i.test(drawingPath) || drawingPath.startsWith('/')) return null
    const parsedDir = findParsedDir(docFilePath)
    if (!parsedDir) return null
    const candidates = []
    if (drawingPath.includes(ASSETS_DIR_SUFFIX)) {
      candidates.push(path.join(parsedDir, drawingPath))
    } else {
      const assets = assetsDirOf(parsedDir)
      if (assets) candidates.push(path.join(assets, drawingPath))
    }
    for (const cand of candidates) {
      const hit = fileInside(parsedDir, cand)
      if (hit) return hit
    }
    // 回退：取文件名部分到 assets 目录内直接查找
    if (drawingPath.includes(ASSETS_DIR_SUFFIX)) {
      const assets = assetsDirOf(parsedDir)
      const basename = drawingPath.split('/').pop()
      if (assets && basename) {
        const hit = fileInside(parsedDir, path.join(assets, basename))
        if (hit) return hit
      }
    }
    return null
  }

  /** 图片服务端点 URL（urlBase 不可用时返回 null）。 */
  function imageUrl(docFilePath, drawingPath) {
    const base = urlBaseFn()
    if (!base) return null
    const qs = new URLSearchParams({ doc: docFilePath, path: drawingPath })
    return base.replace(/\/+$/, '') + '/kb/image?' + qs.toString()
  }

  /** <drawing .../> 标签属性 → dict（键小写）。 */
  function parseDrawingAttrs(attrString) {
    const out = {}
    TAG_ATTR_RE.lastIndex = 0
    let m
    while ((m = TAG_ATTR_RE.exec(attrString)) !== null) out[m[1].toLowerCase()] = m[2]
    return out
  }

  /**
   * mm-drawing chunk → drawings.json 对应条目的图片路径（三级校验）。
   * @param {string} docFilePath - chunk 的 file_path。
   * @param {string} chunkId - chunk 的完整键（引擎 chunk_id，含 -mm-drawing- 段）。
   * @param {string} chunkName - content 首行的 [Image Name] 值（可为空）。
   * @returns {string|null} drawing path；三级都不过为 null。
   */
  function mmDrawingPath(docFilePath, chunkId, chunkName) {
    const m = MM_DRAWING_CHUNK_RE.exec(chunkId || '')
    if (!m) return null
    const docHash = m[1].toLowerCase()
    const idx = Number(m[2])
    const parsedDir = findParsedDir(docFilePath)
    if (!parsedDir) return null
    let drawingsFile = null
    let entries = []
    try { entries = fs.readdirSync(parsedDir, { withFileTypes: true }) } catch (e) { return null }
    for (const entry of entries) {
      if (entry.isFile() && entry.name.endsWith('.drawings.json')) { drawingsFile = path.join(parsedDir, entry.name); break }
    }
    if (!drawingsFile) return null
    let payload = null
    try { payload = JSON.parse(fs.readFileSync(drawingsFile, 'utf8')) } catch (e) { return null }
    const items = payload && payload.drawings && typeof payload.drawings === 'object' ? Object.entries(payload.drawings) : null
    if (!items || idx >= items.length) return null
    const [itemId, item] = items[idx]
    if (!item || typeof item !== 'object') return null
    const itemPath = item.path
    if (typeof itemPath !== 'string' || !itemPath) return null
    // 1. hash 前缀一致
    if (itemId.toLowerCase().startsWith('im-' + docHash + '-')) return itemPath
    // 2/3. doc id 已轮换（.parsed 被重解析覆盖）：图片名语义校验
    // （Python casefold 的 JS 等价取 toLowerCase）
    const itemName = String((item.llm_analyze_result || {}).name || '').trim()
    if (!itemName || !chunkName) return null
    const a = chunkName.toLowerCase()
    const b = itemName.toLowerCase()
    if (a === b) return itemPath
    return similarityRatio(a, b) >= 0.75 ? itemPath : null
  }

  /**
   * 注入入口：普通 chunk 的占位符原地替换 + mm chunk 末尾追加。
   * 两条通道互不干扰（mm chunk 无占位符；普通 chunk id 不含 -mm-）。
   * @param {string} content - chunk content（已按渲染预算裁剪）。
   * @param {string} docFilePath - chunk 的 file_path。
   * @param {string} chunkId - chunk 的完整键（引擎 chunk_id）。
   * @returns {string} 注入后的文本；未启用/无 urlBase 时原样返回。
   */
  function injectIntoChunk(content, docFilePath, chunkId) {
    if (!enabled || !urlBaseFn()) return content
    let out = String(content || '')
    if (out.includes('<drawing')) {
      out = out.replace(DRAWING_TAG_RE, (tag, attrs) => {
        const attrMap = parseDrawingAttrs(attrs)
        const dp = attrMap.path || ''
        const url = resolveFile(docFilePath, dp) ? imageUrl(docFilePath, dp) : null
        if (!url) return '' // 定位失败的占位符对模型是噪音
        const alt = (attrMap.caption || '').trim() || '原文档图片'
        return '![' + alt + '](' + url + ')'
      })
    }
    if (chunkId && chunkId.includes('-mm-drawing-')) {
      const nameMatch = MM_IMAGE_NAME_RE.exec(out)
      const chunkName = nameMatch ? nameMatch[1].trim() : ''
      const dp = mmDrawingPath(docFilePath, chunkId, chunkName)
      if (dp && resolveFile(docFilePath, dp)) {
        const alt = (chunkName || '原文档图片').replace(/\[/g, '(').replace(/\]/g, ')')
        out += '\n\n![' + alt + '](' + imageUrl(docFilePath, dp) + ')'
      }
    }
    return out
  }

  // ---- EMF/WMF 转 PNG（缓存 + 并发去重） ----
  const inFlight = new Map()

  /** 缓存键：文件路径 + mtime + size（源文件变化自动失效）。 */
  function cacheKeyOf(file) {
    const st = fs.statSync(file)
    return crypto.createHash('sha1').update(file + '|' + st.mtimeMs + '|' + st.size).digest('hex')
  }

  /**
   * 单次 libreoffice 转换（独立临时 profile 防并发实例冲突）。
   * @returns {Promise<string|null>} 转换后的 PNG 路径；失败为 null。
   */
  function convertOnce(emfFile, key) {
    return new Promise((resolve) => {
      const workdir = fs.mkdtempSync(path.join(cacheDir, 'conv-'))
      const profileDir = path.join(workdir, 'profile')
      const outDir = path.join(workdir, 'out')
      fs.mkdirSync(outDir, { recursive: true })
      const child = spawn(sofficeBin, [
        '--headless',
        '-env:UserInstallation=file://' + profileDir,
        '--convert-to', 'png',
        '--outdir', outDir,
        emfFile,
      ], { stdio: 'ignore' })
      const timer = setTimeout(() => { try { child.kill('SIGKILL') } catch (e) { /* 已退出 */ } }, CONVERT_TIMEOUT_MS)
      child.on('error', () => { clearTimeout(timer); cleanup(workdir); resolve(null) })
      child.on('close', (code) => {
        clearTimeout(timer)
        const converted = path.join(outDir, path.basename(emfFile, path.extname(emfFile)) + '.png')
        try {
          if (code === 0 && fs.existsSync(converted) && fs.statSync(converted).isFile()) {
            const cached = path.join(cacheDir, key + '.png')
            fs.renameSync(converted, cached)
            cleanup(workdir)
            resolve(cached)
            return
          }
        } catch (e) { log('image convert settle failed: ' + (e && e.message ? e.message : e)) }
        cleanup(workdir)
        resolve(null)
      })
    })
  }

  function cleanup(dir) {
    try { fs.rmSync(dir, { recursive: true, force: true }) } catch (e) { /* 临时目录尽力清理 */ }
  }

  /**
   * 取可展示的文件：EMF/WMF 经 libreoffice 转 PNG（带缓存、并发去重），
   * 其余格式原样返回。libreoffice 不可用/转换失败降级返回原文件
   * （浏览器 <img> 渲染失败由前端回退 alt 文本）。
   * @param {string} file - resolveFile 的结果。
   * @returns {Promise<{file: string, type: string}>} 展示文件与 MIME。
   */
  async function toDisplayFile(file) {
    const ext = path.extname(file).toLowerCase()
    const type = IMAGE_MEDIA_TYPES[ext] || 'application/octet-stream'
    if (!CONVERTIBLE_EXTS.has(ext)) return { file, type }
    try {
      if (!fs.existsSync(cacheDir)) fs.mkdirSync(cacheDir, { recursive: true })
      const key = cacheKeyOf(file)
      const cached = path.join(cacheDir, key + '.png')
      if (fs.existsSync(cached) && fs.statSync(cached).isFile()) return { file: cached, type: 'image/png' }
      let pending = inFlight.get(key)
      if (!pending) {
        pending = convertOnce(file, key).finally(() => { inFlight.delete(key) })
        inFlight.set(key, pending)
      }
      const converted = await pending
      if (converted) return { file: converted, type: 'image/png' }
    } catch (e) {
      log('image convert failed: ' + (e && e.message ? e.message : e))
    }
    return { file, type }
  }

  return { enabled, resolveFile, imageUrl, injectIntoChunk, toDisplayFile }
}
