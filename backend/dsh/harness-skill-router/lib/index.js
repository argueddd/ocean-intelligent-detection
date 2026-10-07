import { createUserMessage } from '@deepseek-ai/dsh-llm'

export const name = 'ocean-harness-skill-router'
export const inject = ['skills']

const DETECTOR_SKILL = 'underwater-line-spectrum-detection'

/** Match creation of detector outputs, while leaving result evaluation to its own Skill. */
export function requestsLineSpectrumDetection(text) {
  if (typeof text !== 'string' || !text.trim()) return false
  const hasDetectionResult = /(?:已有|现有|完整|提供|输入|读取|评价|评估)[^。；\n]{0,24}(?:DetectionResult|检测结果)/iu.test(text)
  if (hasDetectionResult) return false
  return /(?:线谱|谱线)[^。；\n]{0,24}(?:检测|检出|提取|候选|门限|ledger|帧账本)/iu.test(text)
    || /(?:执行|运行|生成|产出|创建)[^。；\n]{0,24}(?:线谱检测|谱线检测|候选|ledger|帧账本)/iu.test(text)
}

function directUserText(messages) {
  return messages
    .filter(message => message.source?.kind === 'user')
    .flatMap(message => message.content || [])
    .filter(block => block?.type === 'text')
    .map(block => block.text)
    .join('\n')
}

export function apply(ctx) {
  ctx.on('agent/pre-step', async ({ agent, messages, signal }, next) => {
    const decision = await next()
    if (decision.kind === 'reject') return decision
    const request = directUserText(messages)
    if (!requestsLineSpectrumDetection(request)) return decision
    signal.throwIfAborted()
    const available = await ctx.skills.list({ cwd: agent.session.header.cwd, signal, scope: agent })
    if (available.some(skill => skill.name === DETECTOR_SKILL)) return decision
    return {
      ...decision,
      messages: [...decision.messages, createUserMessage({
        content: [{
          type: 'text',
          text: '<runtime_capability_route status="unavailable" capability="underwater-line-spectrum-detection">\n'
            + '当前 Skill 目录没有线谱检测执行能力。本轮直接简短说明该能力缺口及影响；不要调用 skill 工具加载数据体检、波束评价、线谱评价或轨迹 Skill 来重复检查边界。\n'
            + '</runtime_capability_route>',
        }],
        source: { kind: 'plugin', plugin: name, form: 'capability-route', capability: DETECTOR_SKILL },
      })],
    }
  })
}
