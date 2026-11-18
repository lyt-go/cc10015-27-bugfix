<template>
  <section class="page" data-module="metric_def">
    <header class="page-head">
      <div>
        <h2>指标定义管理</h2>
        <p class="page-desc">维护指标定义的输入、执行约束与结果记录，为指标定义提供可验证的数据工程流程。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" data-testid="open-create" type="button" @click="openCreate">登记指标定义</button>
        <button class="btn" data-testid="export" type="button" @click="exportRows">导出指标定义清单</button>
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
          <td :colspan="columns.length + 1" class="empty-state">暂无指标定义数据，可先登记指标定义</td>
        </tr>
      </tbody>
    </table>

    <section class="check-panel" data-testid="factor-layer-panel">
      <header class="page-head">
        <div>
          <h3>因子层完整性核对</h3>
          <p class="page-desc">跨模块联动：读取因子约束分配表中的指标口径，逐实验核对因子层是否完整。</p>
        </div>
        <div class="page-actions check-actions">
          <label class="inline-field">
            <span>口径版本</span>
            <input v-model="checkVersion" data-testid="check-version" placeholder="如 V027" />
          </label>
          <button class="btn primary" data-testid="run-factor-check" type="button" :disabled="checking" @click="runFactorCheck">
            {{ checking ? '核对中…' : '核对因子层' }}
          </button>
        </div>
      </header>
      <p v-if="checkMessage" class="check-message" data-testid="check-message">{{ checkMessage }}</p>
      <table v-if="checkRows.length" class="data-table">
        <thead>
          <tr>
            <th v-for="column in checkColumns" :key="column">{{ column }}</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in checkRows"
            :key="row.关联实验"
            :data-testid="`check-row-${row.关联实验}`"
            :class="{ 'check-incomplete': !row.完整 }"
          >
            <td>{{ row.关联实验 }}</td>
            <td>{{ row.组合数 }}</td>
            <td>{{ row.有效组合 }}</td>
            <td>{{ row.已拒绝 }}</td>
            <td>{{ row.缺失层级因子.length ? row.缺失层级因子.join('、') : '—' }}</td>
            <td>{{ row.指标口径 || '—' }}</td>
            <td>{{ row.完整 ? '完整' : '不完整' }}</td>
          </tr>
        </tbody>
      </table>
      <p v-if="checkError" class="error-text" data-testid="check-error">{{ checkError }}</p>
    </section>

    <div v-if="showCreate" class="modal-backdrop" data-testid="create-modal">
      <form class="modal" @submit.prevent="submitCreate">
        <h3>登记指标定义</h3>
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
      <span>共 {{ total }} 条指标定义记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

interface FactorLayerRow {
  关联实验: string
  组合数: number
  有效组合: number
  已拒绝: number
  缺失层级因子: string[]
  指标口径: string
  完整: boolean
}

const ENDPOINT = '/api/metric_def'
const columns = ["指标编号", "指标名称", "计算公式", "统计粒度", "时间窗口", "基准取值", "精度位数", "口径版本"]
const actions = ["提交校验", "标记生效", "标记废弃"]
const statuses = ["草稿", "待校验", "已生效", "已废弃"]
const metricNames = ["指标定义总数", "待校验指标", "已生效指标"]
const checkColumns = ["关联实验", "组合数", "有效组合", "已拒绝", "缺失层级因子", "指标口径", "结论"]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
const showCreate = ref(false)
const creating = ref(false)
const createValues = ref<Record<string, string>>({})
const checkVersion = ref('V027')
const checkRows = ref<FactorLayerRow[]>([])
const checkMessage = ref('')
const checkError = ref('')
const checking = ref(false)
const stats = computed(() => [
  { label: metricNames[0], value: total.value },
  { label: metricNames[1], value: rows.value.filter((row) => row.status === statuses[1]).length },
  { label: metricNames[2], value: rows.value.filter((row) => row.status === statuses[statuses.length - 1]).length },
])

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
    link.download = 'metric_def.csv'
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
      throw new Error('指标定义动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '指标定义操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('指标定义列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '指标定义列表读取失败'
  }
}

async function runFactorCheck() {
  checking.value = true
  checkMessage.value = ''
  checkError.value = ''
  try {
    const query = new URLSearchParams({ version: checkVersion.value }).toString()
    const response = await request(`${ENDPOINT}/factor_layer_check?${query}`)
    if (!response.ok) throw new Error('因子层核对失败，请稍后重试')
    const payload = await response.json()
    checkRows.value = payload.experiments ?? []
    checkMessage.value = payload.message || ''
  } catch (error) {
    checkError.value = error instanceof Error ? error.message : '因子层核对失败，请稍后重试'
  } finally {
    checking.value = false
  }
}

onMounted(reload)
</script>
