/**
 * dsh-knowledge · 图文关联（lib/images.js）契约测试。
 *
 * 覆盖（对照 qa-assistant 参考行为，机制见 docs/重构后功能说明.md）：
 *  - similarityRatio：difflib 口径（标志/徽标 ≥0.75，无关 <0.75）
 *  - resolveFile：.parsed 目录定位（裸名/带前缀）、drawing path 两种形态、
 *    basename 回退、路径穿越拒绝、越界与缺失返回 null
 *  - 通道 1：<drawing/> 占位符原地替换 / 不可定位时移除
 *  - 通道 2：mm-drawing chunk 反查 drawings.json 的三级校验
 *  - 降级：未配置 KB_LIGHTRAG_INPUTS_DIR 或 urlBase 不可用时直通
 *  - toDisplayFile：普通格式原样、soffice 桩转换 + 缓存命中、桩缺失降级
 *
 * 运行：node dev/contract-images.mjs
 */

import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { makeRunner } from './harness.mjs'

const { check, finish } = makeRunner('contract-images')
const here = path.dirname(fileURLToPath(import.meta.url))
const lib = path.join(here, '..', 'lib')
const ASSETS_SUFFIX = '.blocks.assets'
const URL_BASE = 'http://127.0.0.1:3080'

function assert(cond, msg) {
  if (!cond) throw new Error('assert failed: ' + (msg || ''))
}

/** 构建一份 fixture inputs 目录（只含空的 __parsed__）。 */
function makeInputs() {
  const inputs = fs.mkdtempSync(path.join(os.tmpdir(), 'kb-img-inputs-'))
  fs.mkdirSync(path.join(inputs, '__parsed__'))
  return inputs
}

/** 造一个带图片的 .parsed 目录；diskBasename 为磁盘目录基名（含可选前缀）。 */
function makeParsedDoc(inputs, diskBasename, opts = {}) {
  const parsedRoot = path.join(inputs, '__parsed__')
  const parsedDir = path.join(parsedRoot, diskBasename + '.parsed')
  const assets = path.join(parsedDir, diskBasename + ASSETS_SUFFIX)
  fs.mkdirSync(assets, { recursive: true })
  fs.writeFileSync(path.join(assets, '41ad46.jpg'), 'fake-jpg-bytes')
  const hash = opts.hash || '96ce7158aa35e396b6bed335d1baac11'
  const drawings = {
    version: '1.0',
    drawings: {
      ['im-' + hash + '-0001']: {
        id: 'im-' + hash + '-0001',
        format: 'jpg',
        path: diskBasename + ASSETS_SUFFIX + '/41ad46.jpg',
        caption: '',
        llm_analyze_result: { name: opts.vlmName || '内部审计责任追究流程图', type: 'Flowchart', description: '一张流程图' },
      },
    },
  }
  fs.writeFileSync(path.join(parsedDir, diskBasename + '.drawings.json'), JSON.stringify(drawings))
  return { parsedDir, assets }
}

async function main() {
  const { createImageLinker, similarityRatio } = await import(path.join(lib, 'images.js'))

  // ---- similarityRatio（difflib 口径） ----
  await check('similarityRatio：相同/措辞漂移/无关', () => {
    assert(similarityRatio('标志', '标志') === 1, '相同应为 1')
    const drift = similarityRatio('公司标志', '公司徽标')
    assert(drift >= 0.75, '标志/徽标措辞漂移应 ≥0.75，实际 ' + drift)
    assert(similarityRatio('完全不同', '毫不相干啊') < 0.75, '无关应 <0.75')
    assert(similarityRatio('', '') === 1, '空串相等')
  })

  // ---- 未配置 inputs 目录：整体降级 ----
  await check('未配置 KB_LIGHTRAG_INPUTS_DIR 时注入直通', () => {
    const saved = process.env.KB_LIGHTRAG_INPUTS_DIR
    delete process.env.KB_LIGHTRAG_INPUTS_DIR
    try {
      const linker = createImageLinker({ urlBase: () => URL_BASE })
      assert(linker.enabled === false, '未配置应禁用')
      const content = '正文 <drawing path="a.png"/> 尾'
      const out = linker.injectIntoChunk(content, 'doc.docx', 'doc-abc-chunk-000')
      assert(out === content, '直通不改动')
      assert(linker.resolveFile('doc.docx', 'a.png') === null, '解析返回 null')
    } finally {
      if (saved !== undefined) process.env.KB_LIGHTRAG_INPUTS_DIR = saved
    }
  })

  // ---- resolveFile：目录定位与路径形态 ----
  await check('resolveFile：裸名 .parsed + 纯文件名 path', () => {
    const inputs = makeInputs()
    makeParsedDoc(inputs, '内部审计责任追究流程图.pdf')
    const linker = createImageLinker({ inputsDir: inputs, urlBase: () => URL_BASE })
    const hit = linker.resolveFile('内部审计责任追究流程图.pdf', '41ad46.jpg')
    assert(hit && hit.endsWith('41ad46.jpg'), '纯文件名应在 assets 目录命中')
  })

  await check('resolveFile：磁盘目录带类别前缀 + 相对 path', () => {
    const inputs = makeInputs()
    const disk = '风险与合规_审计_内部审计责任追究流程图.pdf'
    const { assets } = makeParsedDoc(inputs, disk)
    const linker = createImageLinker({ inputsDir: inputs, urlBase: () => URL_BASE })
    const rel = disk + ASSETS_SUFFIX + '/41ad46.jpg'
    const hit = linker.resolveFile('内部审计责任追究流程图.pdf', rel)
    assert(hit === path.join(assets, '41ad46.jpg'), '后缀匹配 + 相对路径应命中 assets 内文件')
  })

  await check('resolveFile：path 不带前缀但磁盘目录带 → basename 回退', () => {
    const inputs = makeInputs()
    makeParsedDoc(inputs, '风险与合规_审计_内部审计责任追究流程图.pdf')
    const linker = createImageLinker({ inputsDir: inputs, urlBase: () => URL_BASE })
    // path 带裸 assets 前缀（与磁盘前缀目录不匹配）→ 取文件名到 assets 回退
    const hit = linker.resolveFile('内部审计责任追究流程图.pdf', '内部审计责任追究流程图.pdf' + ASSETS_SUFFIX + '/41ad46.jpg')
    assert(hit && hit.endsWith('41ad46.jpg'), '按 basename 回退应命中')
  })

  await check('resolveFile：路径穿越与非法 path 拒绝', () => {
    const inputs = makeInputs()
    makeParsedDoc(inputs, 'a.docx')
    const linker = createImageLinker({ inputsDir: inputs, urlBase: () => URL_BASE })
    assert(linker.resolveFile('a.docx', '../../../etc/passwd') === null, '穿越拒绝')
    assert(linker.resolveFile('a.docx', '/etc/passwd') === null, '绝对路径拒绝')
    assert(linker.resolveFile('a.docx', 'https://x/1.png') === null, 'http 拒绝')
    assert(linker.resolveFile('不存在.docx', '41ad46.jpg') === null, '未知文档 null')
    assert(linker.resolveFile('a.docx', '没有这张.jpg') === null, '缺文件 null')
  })

  // ---- 通道 1：<drawing/> 占位符替换 ----
  await check('注入通道 1：占位符替换为 Markdown 图片', () => {
    const inputs = makeInputs()
    makeParsedDoc(inputs, 'a.docx')
    const linker = createImageLinker({ inputsDir: inputs, urlBase: () => URL_BASE })
    const content = '第一段 <drawing id="im-1" format="jpg" path="41ad46.jpg" src="" caption="流程图"/> 第二段'
    const out = linker.injectIntoChunk(content, 'a.docx', 'doc-1a2b3c4d5e6f7890abcdef12345678-above-chunk-000')
    assert(!out.includes('<drawing'), '占位符应被替换')
    const m = /!\[流程图\]\(([^)]+)\)/.exec(out)
    assert(m, '应生成带 caption 的图片链接')
    assert(m[1].startsWith(URL_BASE + '/kb/image?'), 'URL 应指向 /kb/image')
    assert(m[1].includes('doc=a.docx') && m[1].includes('path=41ad46.jpg'), 'URL 应携带 doc/path 参数')
    assert(out.includes('第一段') && out.includes('第二段'), '正文保留')
  })

  await check('注入通道 1：不可定位的占位符移除、无 caption 用默认 alt', () => {
    const inputs = makeInputs()
    makeParsedDoc(inputs, 'a.docx')
    const linker = createImageLinker({ inputsDir: inputs, urlBase: () => URL_BASE })
    const out = linker.injectIntoChunk('前 <drawing path="缺图.png"/> 后', 'a.docx', 'doc-x-chunk-000')
    assert(out === '前  后', '不可定位的占位符应删除')
    const out2 = linker.injectIntoChunk('<drawing path="41ad46.jpg"/>', 'a.docx', 'doc-x-chunk-001')
    assert(/!\[原文档图片\]/.test(out2), '无 caption 默认 alt')
  })

  await check('注入直通：urlBase 不可用时保留原文', () => {
    const inputs = makeInputs()
    makeParsedDoc(inputs, 'a.docx')
    const linker = createImageLinker({ inputsDir: inputs, urlBase: () => null })
    const content = '前 <drawing path="41ad46.jpg"/> 后'
    assert(linker.injectIntoChunk(content, 'a.docx', 'doc-x-chunk-000') === content, 'urlBase 为 null 时直通')
  })

  // ---- 通道 2：mm-drawing 反查三级校验 ----
  await check('mm 反查：hash 前缀一致（第 1 级）', () => {
    const inputs = makeInputs()
    makeParsedDoc(inputs, '内部审计责任追究流程图.pdf', { hash: 'aabbccdd00112233445566778899eeff' })
    const linker = createImageLinker({ inputsDir: inputs, urlBase: () => URL_BASE })
    const chunkId = 'doc-aabbccdd00112233445566778899eeff-mm-drawing-000'
    const content = '[Image Name]随便什么名字\n这是一张黑白业务流程图'
    const out = linker.injectIntoChunk(content, '内部审计责任追究流程图.pdf', chunkId)
    assert(out.includes('![随便什么名字](' + URL_BASE + '/kb/image?'), 'hash 命中应追加图片链接')
  })

  await check('mm 反查：名称相等（第 2 级）与相似度（第 3 级）', () => {
    const inputs = makeInputs()
    makeParsedDoc(inputs, 'b.docx', { hash: '11111111111111111111111111111111', vlmName: '公司徽标' })
    const linker = createImageLinker({ inputsDir: inputs, urlBase: () => URL_BASE })
    // chunk 的 doc hash 已轮换（与磁盘 drawings.json 的 id 前缀不一致）
    const rotated = 'doc-22222222222222222222222222222222-mm-drawing-000'
    const eq = linker.injectIntoChunk('[Image Name]公司徽标\n描述', 'b.docx', rotated)
    assert(eq.includes('![公司徽标](' + URL_BASE + '/kb/image?'), '名称相等应命中')
    const sim = linker.injectIntoChunk('[Image Name]公司标志\n描述', 'b.docx', rotated)
    assert(sim.includes('/kb/image?'), '名称相似 ≥0.75 应命中')
    const miss = linker.injectIntoChunk('[Image Name]毫不相干的标题\n描述', 'b.docx', rotated)
    assert(!miss.includes('/kb/image?'), '名称不匹配不应给图')
  })

  await check('mm 反查：索引越界 / 非 mm chunk / drawings.json 缺失', () => {
    const inputs = makeInputs()
    const { parsedDir } = makeParsedDoc(inputs, 'c.docx')
    const linker = createImageLinker({ inputsDir: inputs, urlBase: () => URL_BASE })
    const content = '[Image Name]x\n描述'
    const oob = linker.injectIntoChunk(content, 'c.docx', 'doc-96ce7158aa35e396b6bed335d1baac11-mm-drawing-005')
    assert(!oob.includes('/kb/image?'), '索引越界不给图')
    const plain = linker.injectIntoChunk('普通正文', 'c.docx', 'doc-96ce7158aa35e396b6bed335d1baac11-chunk-000')
    assert(plain === '普通正文', '非 mm chunk 直通')
    fs.rmSync(path.join(parsedDir, 'c.docx.drawings.json'))
    const noJson = linker.injectIntoChunk(content, 'c.docx', 'doc-96ce7158aa35e396b6bed335d1baac11-mm-drawing-000')
    assert(!noJson.includes('/kb/image?'), 'drawings.json 缺失不给图')
  })

  await check('mm 反查：渲染裁剪压成单行的 content 仍能提取图片名', () => {
    const inputs = makeInputs()
    makeParsedDoc(inputs, 'd.docx', { hash: '33333333333333333333333333333333', vlmName: '申告咨询事件工单处理流程图' })
    const linker = createImageLinker({ inputsDir: inputs, urlBase: () => URL_BASE })
    // 渲染路径会把 \s+ 压成单个空格：名称提取若贪婪到行尾会把整段描述吞进图片名
    const collapsed = '[Image Name]申告咨询事件工单处理流程图 [Image Type]Flowchart 该图像是一张跨职能流程图，描绘了多级联动的事件处理机制。'
    const out = linker.injectIntoChunk(collapsed, 'd.docx', 'doc-44444444444444444444444444444444-mm-drawing-000')
    assert(out.includes('![申告咨询事件工单处理流程图](' + URL_BASE + '/kb/image?'), '单行 content 名称提取应止于 [Image Type]')
  })

  // ---- toDisplayFile ----
  await check('toDisplayFile：普通格式原样返回', async () => {
    const inputs = makeInputs()
    const { assets } = makeParsedDoc(inputs, 'a.docx')
    const imgFile = path.join(assets, '41ad46.jpg')
    const linker = createImageLinker({ inputsDir: inputs, urlBase: () => URL_BASE })
    const served = await linker.toDisplayFile(imgFile)
    assert(served.file === imgFile && served.type === 'image/jpeg', 'jpg 原样')
  })

  await check('toDisplayFile：EMF 经 soffice 桩转 PNG 且缓存命中', async () => {
    const inputs = makeInputs()
    const { parsedDir } = makeParsedDoc(inputs, 'a.docx')
    const emf = path.join(parsedDir, 'pic.emf')
    fs.writeFileSync(emf, 'fake-emf')
    // 伪 soffice（POSIX sh）：从参数中取 --outdir 与最后一个位置参数（输入文件）
    const stub = path.join(parsedDir, 'fake-soffice.sh')
    fs.writeFileSync(stub, [
      '#!/bin/sh',
      'out=""',
      'prev=""',
      'n=$#',
      'eval "last=\\${$n}"',
      'for a in "$@"; do',
      '  if [ "$prev" = "--outdir" ]; then out="$a"; fi',
      '  prev="$a"',
      'done',
      'name="$(basename "$last")"',
      'echo fake-png > "$out/${name%.*}.png"',
      'exit 0',
      '',
    ].join('\n'), { mode: 0o755 })
    const cacheDir = fs.mkdtempSync(path.join(os.tmpdir(), 'kb-img-cache-'))
    const linker = createImageLinker({ inputsDir: inputs, urlBase: () => URL_BASE, sofficeBin: stub, cacheDir })
    const r1 = await linker.toDisplayFile(emf)
    assert(r1.type === 'image/png' && r1.file.endsWith('.png'), 'EMF 应转为 PNG')
    assert(fs.readFileSync(r1.file, 'utf8').trim() === 'fake-png', '转换产物来自桩')
    // 第二次命中缓存：删桩后仍返回同一产物，证明没有重新转换
    fs.rmSync(stub)
    const r2 = await linker.toDisplayFile(emf)
    assert(r2.file === r1.file, '缓存命中返回同一路径')
    fs.rmSync(cacheDir, { recursive: true, force: true })
  })

  await check('toDisplayFile：soffice 不可用降级返回原文件', async () => {
    const inputs = makeInputs()
    const { parsedDir } = makeParsedDoc(inputs, 'a.docx')
    const emf = path.join(parsedDir, 'pic.emf')
    fs.writeFileSync(emf, 'fake-emf')
    const cacheDir = fs.mkdtempSync(path.join(os.tmpdir(), 'kb-img-cache-'))
    const linker = createImageLinker({
      inputsDir: inputs, urlBase: () => URL_BASE,
      sofficeBin: path.join(parsedDir, '不存在的soffice'), cacheDir,
    })
    const served = await linker.toDisplayFile(emf)
    assert(served.file === emf && served.type === 'application/octet-stream', '降级原样')
    fs.rmSync(cacheDir, { recursive: true, force: true })
  })

  return finish()
}

main().then((failed) => process.exit(failed ? 1 : 0)).catch((e) => { console.error(e); process.exit(1) })
