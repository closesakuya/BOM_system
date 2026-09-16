import { expect, test, type Page } from '@playwright/test'

async function login(page: Page, username: string, password: string) {
  await page.goto('/login')
  await page.getByLabel('用户名').fill(username)
  await page.getByLabel('密码').fill(password)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page.getByRole('heading', { name: '工作台' })).toBeVisible()
}

test('四次需求：生产只维护未正式档案，不能维护 BOM 或转正式', async ({ page }) => {
  await login(page, 'product', 'product123')
  await expect(page.getByRole('link', { name: '账户管理' })).toHaveCount(0)
  await expect(page.getByRole('link', { name: '物料导入' })).toHaveCount(0)
  await expect(page.getByRole('link', { name: '批量维护' })).toHaveCount(0)
  await page.getByRole('link', { name: '原材料', exact: true }).click()
  await page.getByTestId('new-item').click()
  const modal = page.locator('form.modal').filter({ has: page.getByRole('heading', { name: '新建原材料' }) })
  await expect(modal.locator('select').first()).toBeDisabled()
  await expect(modal.getByText('复制已有原材料（可选）')).toHaveCount(0)
  await modal.getByLabel('名称', { exact: true }).fill('E2E生产未正式权限验证')
  await modal.getByLabel('已检查并确认可能存在的高度相似物料').check()
  await modal.getByRole('button', { name: '创建物料', exact: true }).click()
  await expect(page.getByTestId('item-detail')).toContainText('E2E生产未正式权限验证')
  await expect(page.getByRole('button', { name: '保存修改', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '转为正式导入' })).toHaveCount(0)
  await page.getByRole('button', { name: 'BOM 编辑', exact: true }).click()
  await expect(page.getByRole('button', { name: '添加组成', exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: '技术 BOM', exact: true }).click()
  await expect(page.getByRole('button', { name: '导出技术 BOM Excel' })).toBeVisible()
  await page.getByRole('link', { name: '整机', exact: true }).click()
  await expect(page.getByTestId('new-item')).toHaveCount(0)
})

test('四次需求：访客浏览保留选配行，但不能导出或写入', async ({ page }) => {
  await login(page, 'guest', 'viewer123')
  const item = await page.evaluate(async () => {
    const r = await fetch('/api/items?q=00.999.01&limit=10', { headers: { Authorization: 'Bearer ' + localStorage.getItem('bom_token') } })
    return (await r.json()).items.find((v: any) => v.code === '00.999.01')
  })
  await page.goto(`/items/machine?id=${item.id}`)
  await page.getByRole('button', { name: '技术 BOM', exact: true }).click()
  await expect(page.getByRole('button', { name: '导出技术 BOM Excel' })).toHaveCount(0)
  await expect(page.getByTestId('new-item')).toHaveCount(0)
  await expect(page.getByTestId('item-detail').getByText('备用选配', { exact: true }).first()).toBeVisible()
  await page.getByRole('button', { name: 'BOM 编辑', exact: true }).click()
  await expect(page.getByRole('button', { name: '添加组成', exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: '查看选配', exact: true }).first().click()
  await expect(page.getByRole('button', { name: '保存配置', exact: true })).toHaveCount(0)
  const result = await page.evaluate(async id => {
    const r = await fetch(`/api/items/${id}/export/technical`, { headers: { Authorization: 'Bearer ' + localStorage.getItem('bom_token') } })
    return r.status
  }, item.id)
  expect(result).toBe(403)
})

test('四次需求：研发可维护业务规则但不能管理账户', async ({ page }) => {
  await login(page, 'dev', 'dev12345')
  await expect(page.getByRole('link', { name: '账户管理' })).toHaveCount(0)
  await expect(page.getByRole('link', { name: '批量维护' })).toBeVisible()
  await page.getByRole('link', { name: '编码规则', exact: true }).click()
  await expect(page.getByRole('heading', { name: '新增规则' })).toBeVisible()
  await page.goto('/users')
  await expect(page.getByRole('heading', { name: '工作台' })).toBeVisible()
})
