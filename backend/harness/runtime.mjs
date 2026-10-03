import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { DeepSeekHarness } from '@deepseek-ai/dsh-sdk-client'
import { prepareHarnessHome } from '../integrations.js'
import { skillDirectories } from './skills.mjs'

export const backendDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
export const workspaceRoot = path.resolve(backendDir, '..')

/** 执行环境统一指向本项目 .venv；不自动回退到系统 Python。 */
export function pythonEnvironment(root = workspaceRoot, baseEnv = process.env) {
  const inherited = { ...baseEnv }
  // 外部 Python 路径不能覆盖项目的解释器与依赖解析。
  delete inherited.PYTHONHOME
  delete inherited.PYTHONPATH
  const venv = path.join(root, '.venv')
  const bin = path.join(venv, process.platform === 'win32' ? 'Scripts' : 'bin')
  const python = path.join(bin, process.platform === 'win32' ? 'python.exe' : 'python')
  if (!fs.existsSync(path.join(venv, 'pyvenv.cfg'))) throw new Error('缺少项目 Python 虚拟环境，请先运行 ./setup-python.sh')
  fs.accessSync(python, fs.constants.X_OK)
  const cache = path.join(root, '.run', 'harness-runtime')
  fs.mkdirSync(cache, { recursive: true })
  return {
    python,
    env: {
      ...inherited,
      PATH: bin + path.delimiter + (baseEnv.PATH || ''),
      VIRTUAL_ENV: venv,
      HARNESS_PYTHON: python,
      HARNESS_SKILL_DIRS: JSON.stringify(skillDirectories(root)),
      PYTHONNOUSERSITE: '1',
      PYTHONUNBUFFERED: '1',
      MPLBACKEND: 'Agg',
      MPLCONFIGDIR: path.join(cache, 'matplotlib'),
      XDG_CACHE_HOME: path.join(cache, 'cache'),
    },
  }
}

/** 独立于门户与知识库的 SDK 入口。调用方持有生命周期，结束时必须 close()。 */
export function createProjectHarness({ home = path.join(backendDir, '.runtime', 'harness-home') } = {}) {
  const { env } = pythonEnvironment()
  const patch = prepareHarnessHome(home, backendDir, { profile: 'harness' })
  return new DeepSeekHarness({
    profile: 'harness', cwd: workspaceRoot, processCwd: workspaceRoot,
    dshHome: home, patches: [patch], env,
    provider: process.env.LLM_PROVIDER || 'aliyun',
    model: process.env.LLM_MODEL || 'qwen3.8-flash',
    maxTokens: Number(process.env.LLM_MAX_TOKENS) || 8192,
    ...(process.env.LLM_REASONING_EFFORT ? { reasoningEffort: process.env.LLM_REASONING_EFFORT } : {}),
  })
}
