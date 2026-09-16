export const itemTypeLabels: Record<string, string> = {
  material: '原材料', semi_finished: '半成品', unit: '单元', machine: '整机',
}

export const statusLabels: Record<string, string> = {
  active: '在用', trial: '试制', disabled: '停用',
}

export const sourceLabels: Record<string, string> = {
  purchased: '外购', outsourced: '外协', self_made: '自制',
}

export const roleLabels: Record<string, string> = {
  dev: '研发', product: '生产', guest: '访客', admin: '管理员', maintainer: '维护员', viewer: '查看者',
}

export const actionLabels: Record<string, string> = {
  create: '新建', update: '修改', add: '新增组成', delete: '删除', soft_delete: '软删除',
  restore: '恢复', reorder: '调整顺序', copy: '复制', preview: '预览', commit: '提交',
  replace: '替换', adjust: '调整数量', bulk_maintenance: '批量维护', backup: '备份',
  initial_migration: '初始化迁移', merge_quantity: '合并数量', alternative_select: '切换选配',
  promote: '转为正式导入', migrate_change_note: '迁移历史说明',
  rewire_unofficial_material: '改接未正式物料引用', mark_unofficial_material: '标记未正式导入',
  v1_1_upgrade: 'V1.1 数据升级', v1_1_1_upgrade: 'V1.1.1 数据升级',
  migrate_unofficial_material_v1_1_1: '迁移未正式物料', normalize_key_component_code: '规范化关键器件码',
  backfill_machine_model: '根据整机名称初始化机型',
  archive_after_promotion: '转正式后封存来源',
  configure: '配置选配', migrate_v1_2: 'V1.2 数据初始化', seed_v1_2_demo: '初始化路径选配示例',
  production_rebuild: '生产数据重建', migrate_quantity: '迁移数量调整',
}

export const entityLabels: Record<string, string> = {
  item: '物料', bom_line: 'BOM 组成', bom: 'BOM', user: '账户', code_rule: '编码规则',
  path_alternative: '路径选配',
  code_rules: '编码规则', alternative_group: '替代组', material_promotion_link: '转正式关联', import_batch: '导入批次', import_row: '导入预览行', database: '数据库',
}

export function displayLabel(value?: string | null): string {
  if (!value) return '—'
  return itemTypeLabels[value] || statusLabels[value] || sourceLabels[value] || roleLabels[value] || actionLabels[value] || entityLabels[value] || value
}
