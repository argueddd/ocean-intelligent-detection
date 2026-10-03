export function canSendChat({ isThinking = false, cancellationState = "idle", attachmentReading = false, hasContent = false, hasAttachment = false }) {
  return !isThinking && cancellationState === "idle" && !attachmentReading && (hasContent || hasAttachment);
}

/** A cancelled call has no successful result. Preserve completed, failed and partial calls. */
export function interruptPendingSteps(items, state) {
  return items.map((item) => {
    if ((item.role === "tool" || item.kind === "tool") && ["running", "cancelling", "stop-unconfirmed"].includes(item.status))
      return { ...item, status: state, detail: state === "interrupted" ? "此步骤已中断，未取得完成结果。" : state === "stop-unconfirmed" ? "停止尚未确认，任务可能仍在执行。" : "正在等待服务端停止此步骤。" };
    return item;
  });
}
