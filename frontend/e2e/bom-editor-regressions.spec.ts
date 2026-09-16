import { expect, test, type Page } from '@playwright/test'

async function login(page: Page) {
  await page.goto('/login')
  await page.getByLabel('用户名').fill('admin')
  await page.getByLabel('密码').fill('admin123')
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page.getByRole('heading', { name: '工作台' })).toBeVisible()
}

test('子物料远程搜索不会重新选中旧搜索单元', async ({ page }) => {
  await login(page)
  await page.goto('/items/unit')
  const search = page.getByRole('textbox', { name: /^搜索物料/ })
  await search.fill('03.299')
  await search.press('Enter')
  await expect(page.locator('tr[data-item-code="03.299.02"]')).toBeVisible()
  await search.fill('03.299.01')
  await expect(page.locator('tr[data-item-code="03.299.01"]')).toHaveAttribute('aria-selected', 'true')
  await page.locator('tr[data-item-code="03.299.02"]').click()
  await page.getByRole('button', { name: 'BOM 编辑', exact: true }).click()
  const child = page.getByRole('textbox', { name: /^搜索子物料/ })
  const response = page.waitForResponse(r => r.url().includes('/api/items?') && new URL(r.url()).searchParams.get('q') === '13.3047.0')
  await child.fill('13.3047.0')
  await response
  await expect(child).toHaveValue(/13\.3047\.0/)
  await expect(page.locator('tr[data-item-code="03.299.02"]')).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByTestId('direct-bom-table')).toBeVisible()
  await expect(child).toBeVisible()
})

test('移除最后备选必须保存才生效，保存后未配置且数量不变', async ({ page }) => {
  await login(page)
  const fixture = await page.evaluate(async () => {
    const headers = { Authorization: 'Bearer ' + localStorage.getItem('bom_token'), 'Content-Type': 'application/json' }
    const list = await (await fetch('/api/items?q=03.299.02&limit=10', { headers })).json()
    const owner = list.items.find((i: any) => i.code === '03.299.02')
    const response = await (await fetch(`/api/items/${owner.id}/technical-bom?show_alternatives=true`, { headers })).json()
    const rows = Array.isArray(response) ? response : response.rows
    const row = rows.find((r: any) => r.level === 1 && !r.is_backup_path && r.members.length === 2)
    if (!row) throw new Error('测试库没有双候选直接组成')
    return { owner, row }
  })
  await page.goto(`/items/unit?id=${fixture.owner.id}`)
  await page.getByRole('button', { name: 'BOM 编辑', exact: true }).click()
  const treeRow = page.locator('tr').filter({ has: page.getByRole('button', { name: `快速查看 ${fixture.row.item.code}`, exact: true }) }).filter({ has: page.getByRole('button', { name: '配置选配', exact: true }) }).first()
  await treeRow.getByRole('button', { name: '配置选配' }).click()
  const dialog = page.getByRole('dialog', { name: '路径选配配置' })
  const backup = fixture.row.members.find((m: any) => m.item_id !== fixture.row.item.id)
  await dialog.locator('tr').filter({ hasText: backup.item.code }).getByRole('button', { name: '移除', exact: true }).click()
  await expect(dialog.getByText(/仅剩当前选用项/)).toBeVisible()
  await dialog.getByRole('button', { name: '取消', exact: true }).click()
  await treeRow.getByRole('button', { name: '配置选配' }).click()
  await expect(dialog.locator('tbody tr')).toHaveCount(2)
  await dialog.locator('tr').filter({ hasText: backup.item.code }).getByRole('button', { name: '移除', exact: true }).click()
  await dialog.getByLabel('变更说明').fill('测试删除最后备选')
  await dialog.getByRole('button', { name: '确认保存', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  await expect(treeRow.getByText('未配置', { exact: true })).toBeVisible()
  await expect(page.getByLabel(`${fixture.row.item.code} 数量`, { exact: true })).toHaveValue(fixture.row.quantity)
})
