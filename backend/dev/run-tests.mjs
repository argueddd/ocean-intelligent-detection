/** 全部本地契约测试：不调用模型，不连接真实知识库。 */
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

const suites = [
  ['dsh/dsh-knowledge/dev/run-tests.mjs', []],
  ['dev/contract-approval.mjs', []],
  ['dev/contract-chat.mjs', []],
  ['dev/contract-artifacts.mjs', []],
  ['dev/contract-stream.mjs', []],
  ['dev/contract-control.mjs', []],
  ['dev/contract-control-profile.mjs', []],
  ['dev/contract-image-input.mjs', []],
  ['dev/contract-harness.mjs', []],
  ['dev/contract-model-options.mjs', []],
  ['dev/contract-aliyun-web-search.mjs', []],
  ['dev/contract-skills.mjs', []],
  ['dev/contract-harness-skill-router.mjs', []],
  ['dev/contract-execution.mjs', []],
  ['dev/contract-bootstrap.py', ['-I'], process.env.PYTHON_TEST_BIN || 'python3'],
  ['dev/contract-underwater-sandbox.mjs', []],
  ['dev/contract-vision.mjs', []],
]
let failed = 0
for (const [file, flags, interpreter = process.execPath] of suites) {
  const result = spawnSync(interpreter, [...flags, fileURLToPath(new URL('../' + file, import.meta.url))], { stdio: 'inherit' })
  if (result.status !== 0) failed++
}
if (failed) process.exitCode = 1
else console.log('\nAll knowledge, approval, chat, stream and harness contract tests passed.')
