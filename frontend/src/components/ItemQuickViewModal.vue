<script setup lang="ts">
import { ref } from 'vue'
const backgroundPress = ref(false)
import type { Item } from '../api'
import { displayLabel, itemTypeLabels } from '../labels'

type ComponentLine = {
  id: number
  quantity: string
  child: Item
}
type ItemDetail = Item & { components?: ComponentLine[] }

defineProps<{
  item: ItemDetail
  loading?: boolean
  error?: string
  fullHref: string
}>()
defineEmits<{ close: []; openFull: []; preview: [item: Item] }>()

function value(value?: string | null) {
  return value || '—'
}
</script>

<template>
  <div class="modal-mask" @pointerdown="backgroundPress=$event.target===$event.currentTarget" @click.self="backgroundPress&&$emit('close')">
    <section class="modal quick-item-modal" role="dialog" aria-modal="true" :aria-label="`快速查看物料 ${item.code}`">
      <div class="modal-head">
        <div>
          <h2>物料快速查看</h2>
          <p class="subtitle"><span class="tag">{{ itemTypeLabels[item.item_type] }}</span>　<strong>{{ item.code }}</strong></p>
        </div>
        <button type="button" aria-label="关闭物料快速查看" @click="$emit('close')">×</button>
      </div>
      <div v-if="loading" class="notice">正在读取最新物料信息…</div>
      <div v-if="error" class="notice error" role="alert">{{ error }}</div>
      <dl class="quick-item-fields">
        <div><dt>名称</dt><dd>{{ value(item.name) }}</dd></div>
        <div><dt>规格型号</dt><dd>{{ value(item.specification) }}</dd></div>
        <div><dt>单位</dt><dd>{{ value(item.unit) }}</dd></div>
        <div><dt>状态/来源</dt><dd>{{ item.deleted_at ? '已删除' : displayLabel(item.source_type || item.status) }}</dd></div>
        <div><dt>辅助索引码</dt><dd>{{ value(item.auxiliary_code) }}</dd></div>
        <div><dt>材料属性</dt><dd>{{ value(item.material_attribute) }}</dd></div>
        <div v-if="item.item_type==='material'"><dt>正式导入状态</dt><dd><span class="tag" :class="{warn:item.unofficial_status==='pending'}">{{item.is_formally_imported?'正式导入':item.unofficial_status==='archived'?'已转正式（封存）':'待转正式'}}</span></dd></div>
        <div v-if="item.item_type==='material'"><dt>历史物料号</dt><dd>{{ value(item.historical_item_code) }}</dd></div>
        <div v-if="item.item_type==='material'"><dt>关键器件码</dt><dd>{{ value(item.key_component_code) }}</dd></div>
        <div v-if="item.item_type==='material'&&!item.is_formally_imported"><dt>封存状态</dt><dd>{{item.unofficial_status==='archived'?'已转正式（封存）':'待转正式'}}</dd></div>
        <div v-if="item.item_type==='machine'"><dt>机型</dt><dd>{{ value(item.machine_model) }}</dd></div>
        <div><dt>上一版本名称</dt><dd>{{ value(item.previous_version_name) }}</dd></div>
        <div><dt>发票名称</dt><dd>{{ value(item.invoice_name) }}</dd></div>
        <div class="span-2"><dt>备注</dt><dd>{{ value(item.remark) }}</dd></div>
      </dl>
      <template v-if="!loading&&item.components?.length">
        <h3>直接组成</h3>
        <div class="table-wrap quick-item-components">
          <table>
            <thead><tr><th>物料编码</th><th>类型</th><th>名称</th><th>规格型号</th><th>数量</th><th>单位</th></tr></thead>
            <tbody><tr v-for="line in item.components" :key="line.id"><td><button type="button" class="code-link" :aria-label="`快速查看 ${line.child.code}`" @click="$emit('preview',line.child)">{{line.child.code}}</button></td><td>{{itemTypeLabels[line.child.item_type]}}</td><td>{{line.child.name}}</td><td>{{value(line.child.specification)}}</td><td>{{line.quantity}}</td><td>{{line.child.unit}}</td></tr></tbody>
          </table>
        </div>
      </template>
      <div class="actions">
        <button type="button" class="btn secondary" @click="$emit('close')">关闭</button>
        <a class="btn" :href="fullHref" target="_blank" rel="noopener noreferrer" @click="$emit('openFull')">在新标签页打开完整界面</a>
      </div>
    </section>
  </div>
</template>
