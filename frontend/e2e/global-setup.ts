import { execFileSync } from 'node:child_process'
import { copyFileSync, existsSync, rmSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

export default async function globalSetup() {
  const here = path.dirname(fileURLToPath(import.meta.url))
  const root = path.resolve(here, '..', '..')
  const source = path.join(root, 'runtime', 'bom_v1.db')
  const target = path.join(root, 'runtime', 'e2e.db')
  if (!existsSync(source)) throw new Error(`初始数据库不存在：${source}`)
  if (existsSync(target)) rmSync(target)
  for (const suffix of ['-wal', '-shm']) {
    if (existsSync(target + suffix)) rmSync(target + suffix)
  }
  copyFileSync(source, target)
  execFileSync(path.join(root, '.venv', 'Scripts', 'python.exe'), [path.join(root, 'backend', 'tests', 'create_e2e_fixture.py')], { stdio: 'inherit' })
}
