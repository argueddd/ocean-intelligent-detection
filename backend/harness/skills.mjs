import path from 'node:path'
import { Context } from '@deepseek-ai/cordis'
import { SkillRegistry } from '@deepseek-ai/dsh-skill'
import { FileSystemSkillProvider } from '@deepseek-ai/dsh-skill-filesystem'

export function skillDirectories(root) {
  return ['skills', '.agents/skills', '.dsh/skills'].map((dir) => path.join(root, dir))
}

/** 读取 SDK 的真实目录，不启动模型或另外维护注册表。 */
export async function listProjectSkills(root) {
  const ctx = new Context()
  new SkillRegistry(ctx)
  let provider
  const unregister = ctx.skills.registerProvider((control) => {
    provider = new FileSystemSkillProvider(ctx, control, {
      includeDefaultRoots: false, customSkillDirs: skillDirectories(root), watch: false,
    })
    return provider
  })
  try { return (await ctx.skills.snapshot({ cwd: root })).skills }
  finally { await provider.dispose(); unregister() }
}
