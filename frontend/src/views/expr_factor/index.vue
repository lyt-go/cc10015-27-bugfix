<template>
  <section class="page" data-module="expr_factor">
    <header class="page-head">
      <div>
        <h2>实验因子管理</h2>
        <p class="page-desc">维护因子配置的输入、执行约束与结果记录，为实验因子提供可验证的数据工程流程。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" data-testid="open-create" type="button" @click="openCreate">登记因子配置</button>
        <button class="btn" data-testid="export" type="button" @click="exportRows">导出实验因子清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :data-testid="`filter-${field}`" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" data-testid="query" type="submit">查询</button>
      <button class="btn ghost" data-testid="reset" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)" :data-testid="`row-${row.id}`" :data-status="String(row.status)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              :data-testid="`action-${row.id}-${action}`"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无实验因子数据，可先登记因子配置</td>
        </tr>
      </tbody>
    </table>

    <section class="alloc-panel" data-testid="alloc-panel">
      <header class="page-head">
        <div>
          <h3>因子约束分配表</h3>
          <p class="page-desc">读取因子配置与实验分流比例，校验互斥与空值边界后生成；冲突与空层级不会进入有效分配，被拒绝的组合逐项列出。</p>
        </div>
        <div class="page-actions alloc-actions">
          <label class="inline-field">
            <span>口径版本</span>
            <input v-model="allocVersion" data-testid="alloc-version" placeholder="如 V027" />
          </label>
          <button class="btn primary" data-testid="alloc-generate" type="button" :disabled="allocating" @click="generateAlloc(false)">
            {{ allocating ? '生成中…' : '生成分配表' }}
          </button>
          <button class="btn" data-testid="alloc-resume" type="button" :disabled="allocating" @click="generateAlloc(true)">续跑未完成</button>
        </div>
      </header>

      <div class="stat-row">
        <article v-for="item in allocStats" :key="item.label" class="stat-card">
          <span class="stat-label">{{ item.label }}</span>
          <strong class="stat-value">{{ item.value }}</strong>
        </article>
      </div>

      <p v-if="allocMessage" class="alloc-message" data-testid="alloc-message">{{ allocMessage }}</p>

      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in allocColumns" :key="column">{{ column }}</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in allocRows"
            :key="String(row.id)"
            :data-testid="`alloc-row-${row.id}`"
            :data-status="String(row.组合状态)"
            :class="{ 'alloc-rejected': row.组合状态 === '已拒绝' }"
          >
            <td v-for="column in allocColumns" :key="column">{{ formatAllocCell(row, column) }}</td>
            <td class="row-actions">
              <button class="link" type="button" :data-testid="`alloc-detail-${row.id}`" @click="openAllocDetail(row)">查看</button>
            </td>
          </tr>
          <tr v-if="!allocRows.length">
            <td :colspan="allocColumns.length + 1" class="empty-state" data-testid="alloc-empty">{{ allocEmptyMessage }}</td>
          </tr>
        </tbody>
      </table>

      <footer class="page-foot">
        <span>共 {{ allocTotal }} 条分配组合</span>
        <span v-if="allocError" class="error-text" data-testid="alloc-error">{{ allocError }}</span>
      </footer>
    </section>

    <div v-if="allocDetail" class="modal-backdrop" data-testid="alloc-detail-modal" @click.self="allocDetail = null">
      <div class="modal">
        <h3>分配组合详情</h3>
        <dl class="alloc-detail-list">
          <template v-for="field in allocDetailFields" :key="field">
            <dt>{{ field }}</dt>
            <dd :data-testid="`alloc-detail-field-${field}`">{{ formatAllocCell(allocDetail, field) }}</dd>
          </template>
        </dl>
        <div class="page-actions">
          <button class="btn" type="button" data-testid="alloc-detail-close" @click="allocDetail = null">关闭</button>
        </div>
      </div>
    </div>

    <div v-if="showCreate" class="modal-backdrop" data-testid="create-modal">
      <form class="modal" @submit.prevent="submitCreate">
        <h3>登记因子配置</h3>
        <label v-for="field in columns" :key="field" class="create-field">
          <span>{{ field }}</span>
          <input v-model="createValues[field]" :data-testid="`create-${field}`" required />
        </label>
        <div class="page-actions">
          <button class="btn" type="button" @click="showCreate = false">取消</button>
          <button class="btn primary" data-testid="submit-create" type="submit" :disabled="creating">
            {{ creating ? '提交中…' : '确认登记' }}
          </button>
        </div>
      </form>
    </div>

    <footer class="page-foot">
      <span>共 {{ total }} 条实验因子记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>
type AllocRow = Record<string, string | number | string[] | null>

const ENDPOINT = '/api/expr_factor'
const ALLOC_ENDPOINT = '/api/expr_factor/allocation'
const columns = ["因子编号", "因子名称", "因子层级", "取值集合", "分配比例", "互斥规则", "关联实验", "生效批次"]
const actions = ["提交校验", "标记生效", "停用因子"]
const statuses = ["草稿", "待校验", "已生效", "已停用"]
const metricNames = ["因子配置总数", "待校验因子", "已生效因子"]
const allocColumns = ["分配编号", "口径版本", "关联实验", "因子编号", "因子名称", "因子层级", "互斥规则", "分配比例", "组合状态", "拒绝原因", "缺失字段"]
const allocDetailFields = ["分配编号", "口径版本", "关联实验", "实验分流比例", "指标口径", "因子编号", "因子名称", "因子层级", "互斥规则", "取值集合", "分配比例", "组合状态", "拒绝原因", "缺失字段"]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
const showCreate = ref(false)
const creating = ref(false)
const createValues = ref<Record<string, string>>({})
const allocRows = ref<AllocRow[]>([])
const allocTotal = ref(0)
const allocVersion = ref('V027')
const allocMessage = ref('')
const allocError = ref('')
const allocEmptyMessage = ref('暂无因子约束分配数据，可点击「生成分配表」创建')
const allocating = ref(false)
const allocDetail = ref<AllocRow | null>(null)
const stats = computed(() => [
  { label: metricNames[0], value: total.value },
  { label: metricNames[1], value: rows.value.filter((row) => row.status === statuses[1]).length },
  { label: metricNames[2], value: rows.value.filter((row) => row.status === statuses[statuses.length - 1]).length },
])
const allocStats = computed(() => [
  { label: '分配组合总数', value: allocTotal.value },
  { label: '有效组合', value: allocRows.value.filter((row) => row.组合状态 === '有效').length },
  { label: '已拒绝组合', value: allocRows.value.filter((row) => row.组合状态 === '已拒绝').length },
  { label: '缺失层级因子', value: allocRows.value.filter((row) => asList(row.缺失字段).includes('因子层级')).length },
])

function asList(value: unknown): string[] {
  return Array.isArray(value) ? value.map(String) : []
}

function formatAllocCell(row: AllocRow, column: string): string {
  const value = row[column]
  if (Array.isArray(value)) return value.length ? value.join('、') : '—'
  if (value === null || value === undefined || value === '') return '—'
  return String(value)
}

function resetFilters() {
  filters.value = {}
  void reload()
}

async function exportRows() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value).toString()
  try {
    const response = await request(`${ENDPOINT}/export?${query}`)
    if (!response.ok) throw new Error('导出失败，请稍后重试')
    const url = URL.createObjectURL(await response.blob())
    const link = document.createElement('a')
    link.href = url
    link.download = 'expr_factor.csv'
    link.click()
    URL.revokeObjectURL(url)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '导出失败'
  }
}

function openCreate() {
  createValues.value = Object.fromEntries(columns.map((field) => [field, '']))
  errorMessage.value = ''
  showCreate.value = true
}

async function submitCreate() {
  creating.value = true
  errorMessage.value = ''
  try {
    const response = await request(ENDPOINT, {
      method: 'POST', body: JSON.stringify(createValues.value),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) throw new Error(payload.message || '登记失败')
    showCreate.value = false
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '登记失败'
  } finally {
    creating.value = false
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    if (!response.ok) {
      throw new Error('实验因子动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '实验因子操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('因子配置列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '实验因子列表读取失败'
  }
}

async function reloadAlloc() {
  allocError.value = ''
  const query = new URLSearchParams({ version: allocVersion.value }).toString()
  try {
    const response = await request(`${ALLOC_ENDPOINT}?${query}`)
    if (!response.ok) throw new Error('分配表读取失败')
    const payload = await response.json()
    allocRows.value = payload.items ?? []
    allocTotal.value = payload.total ?? allocRows.value.length
    allocEmptyMessage.value = payload.message || '暂无因子约束分配数据，可点击「生成分配表」创建'
  } catch (error) {
    allocError.value = error instanceof Error ? error.message : '分配表读取失败'
  }
}

async function generateAlloc(resume: boolean) {
  allocating.value = true
  allocMessage.value = ''
  allocError.value = ''
  try {
    const response = await request(`${ALLOC_ENDPOINT}/generate`, {
      method: 'POST',
      body: JSON.stringify({ 口径版本: allocVersion.value, 模式: resume ? '续跑' : '全量' }),
    })
    const payload = await response.json()
    if (!response.ok) throw new Error(payload.message || '分配表生成失败')
    allocMessage.value = payload.message || ''
    if (!payload.ok) {
      allocError.value = `${payload.message || '分配中断'}，可重试或续跑`
    }
    await reloadAlloc()
  } catch (error) {
    allocError.value = error instanceof Error ? error.message : '分配表生成失败，可重试'
  } finally {
    allocating.value = false
  }
}

async function openAllocDetail(row: AllocRow) {
  allocError.value = ''
  try {
    const response = await request(`${ALLOC_ENDPOINT}/${row.id}`)
    if (!response.ok) throw new Error('分配详情读取失败')
    allocDetail.value = await response.json()
  } catch (error) {
    allocError.value = error instanceof Error ? error.message : '分配详情读取失败'
  }
}

onMounted(() => {
  void reload()
  void reloadAlloc()
})
</script>
