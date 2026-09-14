import { defineConfig } from '@playwright/test'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const root = path.resolve(here, '..')
process.env.NO_PROXY = '127.0.0.1,localhost'
process.env.no_proxy = '127.0.0.1,localhost'

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  expect: { timeout: 30_000 },
  workers: 1,
  fullyParallel: false,
  reporter: [['list'], ['html', { outputFolder: 'playwright-report', open: 'never' }]],
  use: {
    baseURL: 'http://127.0.0.1:8010',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    launchOptions: {
      executablePath: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
      args: ['--no-proxy-server', '--proxy-server=direct://', '--proxy-bypass-list=*'],
    },
  },
  webServer: {
    command: '.\\.venv\\Scripts\\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8010',
    cwd: root,
    url: 'http://127.0.0.1:8010/api/health',
    reuseExistingServer: false,
    timeout: 120_000,
    env: {
      BOM_DATABASE_URL: `sqlite:///${path.join(root, 'runtime', 'e2e.db').replaceAll('\\', '/')}`,
      BOM_BACKUP_DIR: path.join(root, 'runtime', 'e2e-backups'),
      NO_PROXY: '127.0.0.1,localhost', no_proxy: '127.0.0.1,localhost',
    },
  },
})
