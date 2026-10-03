/** 调用方拥有 Harness；失败或到期关闭它，避免终态之后仍等不到 idle。 */
export async function runHarnessTask(harness, prompt, { timeoutMs, onNotification } = {}) {
  if (timeoutMs !== undefined && (!Number.isFinite(timeoutMs) || timeoutMs <= 0)) throw new Error('timeoutMs 必须是正数')
  const session = harness.session()
  let terminalFailure, timer
  const stop = (error) => {
    terminalFailure = error
    harness.close().catch(() => {})
  }
  const activity = session.run(prompt, { onNotification(notification) {
    const event = notification.params?.event
    if (notification.params?.sessionId === session.id && event?.type === 'turn/end') {
      const reason = event.data?.reason
      if (['error', 'aborted', 'max-tokens'].includes(reason?.kind)) stop(new Error(reason.error?.message || 'Harness 未完成任务：' + reason.kind))
    }
    onNotification?.(notification)
  } })
  try {
    const result = timeoutMs === undefined ? await activity : await Promise.race([
      activity,
      new Promise((_, reject) => { timer = setTimeout(() => { const error = new Error(`Harness 任务超过 ${timeoutMs}ms`); stop(error); reject(error) }, timeoutMs) }),
    ])
    if (terminalFailure) throw terminalFailure
    return result
  } catch (error) { throw terminalFailure || error }
  finally { clearTimeout(timer) }
}
