import { test, expect } from '@playwright/test'

test('财务仅五个菜单、全只读、技术与生产BOM导出', async ({ page }) => {
  const item = { id: 1, code: '10.8841.0', name: '权限测试原材料', item_type: 'material',
    unit: 'pcs', status: 'active', source_type: 'purchased', is_formally_imported: true,
    requires_assembly: false, components: [] }
  await page.addInitScript(() => {
    localStorage.setItem('bom_token', 'mock-finance')
    localStorage.setItem('bom_user', JSON.stringify({ id: 2, username: 'finance', display_name: '财务', role: 'finance', active: true }))
  })
  // All API calls are mocked: this test never connects to a database.
  await page.route('**/api/**', async route => {
    const pathname = new URL(route.request().url()).pathname
    const data = pathname === '/api/items' ? { total: 1, items: [item] }
      : pathname === '/api/items/1' ? item : []
    await route.fulfill({ json: data })
  })
  await page.goto('/')
  await expect(page).toHaveURL(/\/items\/material$/)
  await expect(page.getByRole('navigation').getByRole('link')).toHaveText(['原材料', '半成品', '单元', '整机', '变更日志'])
  const expandedWidth = (await page.locator('main').boundingBox())!.width
  await page.getByRole('button', { name: '收起菜单', exact: true }).click()
  await expect(page.getByRole('navigation')).toBeHidden()
  expect((await page.locator('main').boundingBox())!.width).toBeGreaterThan(expandedWidth + 150)
  await page.reload()
  await expect(page.getByRole('button', { name: '展开菜单', exact: true })).toHaveAttribute('aria-expanded', 'false')
  await page.getByRole('button', { name: '展开菜单', exact: true }).click()
  await expect(page.getByRole('navigation').getByRole('link')).toHaveCount(5)
  for (const url of ['/users', '/rules', '/compare', '/imports', '/maintenance', '/alternatives']) {
    await page.goto(url)
    await expect(page).toHaveURL(/\/items\/material$/)
  }
  await page.getByTestId('item-list-table').getByText(item.code).click()
  const detail = page.getByTestId('item-detail')
  await expect(detail.getByLabel('名称', { exact: true })).toHaveAttribute('readonly', '')
  await expect(page.getByTestId('new-item')).toHaveCount(0)
  await expect(page.getByRole('button', { name: '保存修改', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: /导出.*基本信息/ })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '批量导出技术 BOM ZIP', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '批量导出生产 BOM ZIP', exact: true })).toBeVisible()
  await detail.getByRole('button', { name: 'BOM 编辑', exact: true }).click()
  await expect(page.getByRole('button', { name: '添加组成', exact: true })).toHaveCount(0)
  await detail.getByRole('button', { name: '技术 BOM', exact: true }).click()
  await expect(page.getByRole('button', { name: '导出技术 BOM Excel', exact: true })).toBeVisible()
  await detail.getByRole('button', { name: '生产 BOM', exact: true }).click()
  await expect(page.getByRole('button', { name: '导出生产 BOM Excel', exact: true })).toBeVisible()
  await page.getByRole('link', { name: '变更日志', exact: true }).click()
  await expect(page.getByRole('button', { name: '导出日志', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '创建数据库备份', exact: true })).toHaveCount(0)
})
