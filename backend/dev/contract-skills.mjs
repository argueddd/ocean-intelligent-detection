/** Real SDK skill discovery and watcher contracts; no model or network calls. */
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'
import { Context } from '@deepseek-ai/cordis'
import { SkillRegistry, isModelInvocable, renderSkillContent } from '@deepseek-ai/dsh-skill'
import { FileSystemSkillProvider } from '@deepseek-ai/dsh-skill-filesystem'
import { SystemPrompt } from '@deepseek-ai/dsh-system-prompt'
import { ToolRuntime } from '@deepseek-ai/dsh-tools'
import { apply as applyToolSkill } from '@deepseek-ai/dsh-tool-skill'

function markdown(name, description, body = 'Follow these instructions.', extra = '') {
  return `---\nname: ${name}\ndescription: ${description}\n${extra}---\n${body}\n`
}

async function fixture(t, { existingRoot = true, secondRoot = false } = {}) {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'ocean-skills-contract-'))
  const skillRoot = path.join(root, 'skills')
  const secondSkillRoot = path.join(root, 'secondary-skills')
  if (existingRoot) await fs.mkdir(skillRoot)
  const ctx = new Context()
  const registry = new SkillRegistry(ctx)
  let provider
  const unregister = registry.registerProvider(control => {
    provider = new FileSystemSkillProvider(ctx, control, {
      includeDefaultRoots: false,
      customSkillDirs: secondRoot ? [skillRoot, secondSkillRoot] : [skillRoot],
      dshHome: path.join(root, 'fake-dsh-home'),
      agentsHome: path.join(root, 'fake-agents-home'),
      watch: true,
      watchStabilityThresholdMs: 20,
      watchPollIntervalMs: 20,
    })
    return provider
  })
  let changeNotifications = 0
  ctx.on('skills/change', () => { changeNotifications++ })
  t.after(async () => {
    await provider.dispose()
    unregister()
    await fs.rm(root, { recursive: true, force: true })
  })
  return {
    ctx, registry, provider, root, skillRoot, secondSkillRoot,
    lookup: { cwd: root },
    get changeNotifications() { return changeNotifications },
    async write(relative, content) {
      const destination = path.join(root, relative)
      await fs.mkdir(path.dirname(destination), { recursive: true })
      await fs.writeFile(destination, content)
      return destination
    },
  }
}

async function eventually(predicate) {
  const deadline = Date.now() + 5000
  while (Date.now() < deadline) {
    if (await predicate()) return
    await new Promise(resolve => setTimeout(resolve, 25))
  }
  assert.fail('SDK watcher did not invalidate the existing catalog within 5 seconds')
}

test('project skills/ custom root is discovered without reading project or user default roots', async t => {
  const f = await fixture(t)
  await f.write('.git', '')
  await f.write('skills/data-health/SKILL.md', markdown('data-health', 'Check data quality'))
  await f.write('.dsh/skills/project-default/SKILL.md', markdown('project-default', 'Must stay excluded'))
  await f.write('.agents/skills/project-agents/SKILL.md', markdown('project-agents', 'Must stay excluded'))
  await f.write('fake-dsh-home/skills/user-default/SKILL.md', markdown('user-default', 'Must stay excluded'))
  await f.write('fake-agents-home/skills/user-agents/SKILL.md', markdown('user-agents', 'Must stay excluded'))
  const snapshot = await f.registry.snapshot(f.lookup)
  assert.equal(snapshot.complete, true)
  assert.deepEqual(snapshot.skills.map(skill => skill.name), ['data-health'])
  assert.equal(snapshot.skills[0].source, 'custom')
})

test('an initially missing custom root can appear in the same SDK registry', async t => {
  const f = await fixture(t, { existingRoot: false })
  assert.deepEqual(await f.registry.list(f.lookup), [])
  const changesBefore = f.changeNotifications
  await f.write('skills/added-later/SKILL.md', markdown('added-later', 'Created after discovery'))
  await eventually(async () => (await f.registry.list(f.lookup)).some(skill => skill.name === 'added-later'))
  assert.ok(f.changeNotifications > changesBefore)
})

test('the real skill tool returns the absolute resource directory for relative scripts', async t => {
  const f = await fixture(t)
  new SystemPrompt(f.ctx, {})
  new ToolRuntime(f.ctx)
  applyToolSkill(f.ctx)
  await f.write('skills/spectrum-check/SKILL.md', markdown('spectrum-check', 'Analyze spectrum', 'Run scripts/check.py relative to the base directory.'))
  await f.write('skills/spectrum-check/scripts/check.py', 'print("fixture")\n')
  const tool = f.ctx.tools.get('skill')
  const result = await tool.execute({ name: 'spectrum-check' }, { signal: new AbortController().signal })
  assert.deepEqual(result.resourceBase, { kind: 'directory', path: path.join(f.skillRoot, 'spectrum-check') })
  assert.equal(result.content, 'Run scripts/check.py relative to the base directory.')
  const rendered = renderSkillContent(result)
  assert.ok(rendered.includes(`Base directory for this skill: ${result.resourceBase.path}`))
  assert.ok(rendered.includes('Resolve relative paths mentioned by this skill against the base directory'))
})

test('existing watcher invalidates catalog for added, modified and deleted bundles', async t => {
  const f = await fixture(t)
  assert.deepEqual(await f.registry.list(f.lookup), [])
  let changesBefore = f.changeNotifications
  await f.write('skills/new-bundle/SKILL.md', markdown('new-bundle', 'Version 1', 'Body version 1.'))
  await eventually(async () => (await f.registry.list(f.lookup)).some(skill => skill.name === 'new-bundle'))
  assert.ok(f.changeNotifications > changesBefore)

  changesBefore = f.changeNotifications
  await f.write('skills/new-bundle/SKILL.md', markdown('new-bundle', 'Version 2', 'Body version 2.'))
  await eventually(async () => (await f.registry.list(f.lookup)).find(skill => skill.name === 'new-bundle')?.description === 'Version 2')
  assert.ok(f.changeNotifications > changesBefore)
  assert.equal((await f.registry.get('new-bundle', f.lookup)).content, 'Body version 2.')

  changesBefore = f.changeNotifications
  await fs.rm(path.join(f.skillRoot, 'new-bundle'), { recursive: true })
  await eventually(async () => !(await f.registry.list(f.lookup)).some(skill => skill.name === 'new-bundle'))
  assert.ok(f.changeNotifications > changesBefore)
  assert.equal(await f.registry.get('new-bundle', f.lookup), undefined)
})

test('skill body loads always read current instructions even while catalog is cached', async t => {
  const f = await fixture(t)
  await f.write('skills/body-refresh/SKILL.md', markdown('body-refresh', 'Stable summary', 'Body version 1.'))
  assert.equal((await f.registry.get('body-refresh', f.lookup)).content, 'Body version 1.')
  await f.write('skills/body-refresh/SKILL.md', markdown('body-refresh', 'Stable summary', 'Body version 2.'))
  assert.equal((await f.registry.get('body-refresh', f.lookup)).content, 'Body version 2.')
})

test('invalid metadata and nested bundles are excluded; flat files and invocation policy work', async t => {
  const f = await fixture(t)
  await f.write('skills/flat.md', markdown('flat-skill', 'Valid flat skill'))
  await f.write('skills/nested/wrong-depth/SKILL.md', markdown('wrong-depth', 'Nested skills are not recursively discovered'))
  await f.write('skills/bad-name/SKILL.md', markdown('bad_name', 'Invalid name'))
  await f.write('skills/missing-description/SKILL.md', '---\nname: missing-description\n---\nMissing description.\n')
  await f.write('skills/no-frontmatter/SKILL.md', 'No frontmatter.\n')
  await f.write('skills/bad-invocation/SKILL.md', markdown('bad-invocation', 'Invalid invocation', 'Body.', 'disable-model-invocation: perhaps\n'))
  await f.write('skills/human-only/SKILL.md', markdown('human-only', 'Human invocation only', 'Body.', 'disable-model-invocation: true\n'))
  const catalog = await f.registry.list(f.lookup)
  assert.deepEqual(catalog.map(skill => skill.name), ['flat-skill', 'human-only'])
  assert.deepEqual(catalog.filter(isModelInvocable).map(skill => skill.name), ['flat-skill'])
})

test('same-name skills resolve to the first custom root and its script directory', async t => {
  const f = await fixture(t, { secondRoot: true })
  await f.write('skills/shared/SKILL.md', markdown('shared', 'First custom root', 'First implementation.'))
  await f.write('secondary-skills/shared/SKILL.md', markdown('shared', 'Second custom root', 'Second implementation.'))
  const catalog = await f.registry.list(f.lookup)
  assert.deepEqual(catalog.map(skill => skill.name), ['shared'])
  assert.equal(catalog[0].description, 'First custom root')
  const loaded = await f.registry.get('shared', f.lookup)
  assert.equal(loaded.content, 'First implementation.')
  assert.equal(loaded.resourceBase.path, path.join(f.skillRoot, 'shared'))
})

test('moving a bundle updates its resource directory without restarting the provider', async t => {
  const f = await fixture(t)
  await f.write('skills/original/SKILL.md', markdown('moveable-skill', 'Relocatable scripts'))
  assert.equal((await f.registry.get('moveable-skill', f.lookup)).resourceBase.path, path.join(f.skillRoot, 'original'))
  await fs.rename(path.join(f.skillRoot, 'original'), path.join(f.skillRoot, 'renamed'))
  await eventually(async () => (await f.registry.get('moveable-skill', f.lookup))?.resourceBase.path === path.join(f.skillRoot, 'renamed'))
})
