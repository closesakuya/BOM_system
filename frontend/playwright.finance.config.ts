import { defineConfig } from '@playwright/test'
import os from 'node:os'
import path from 'node:path'

process.env.NO_PROXY = '127.0.0.1,localhost'
process.env.no_proxy = '127.0.0.1,localhost'

export default defineConfig({
  testDir: './e2e', testMatch: 'finance-permissions.spec.ts', workers: 1,
  outputDir: path.join(os.tmpdir(), 'bom-finance-ui-results'), reporter: 'list',
  use: { baseURL: 'http://127.0.0.1:5183', launchOptions: {
    executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe',
    args: ['--no-proxy-server'],
  } },
  webServer: { command: 'npx vite preview --host 127.0.0.1 --port 5183 --strictPort',
    url: 'http://127.0.0.1:5183', reuseExistingServer: false },
})
