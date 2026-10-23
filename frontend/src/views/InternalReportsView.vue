<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import SkeletonState from '../components/SkeletonState.vue'
import { currentUser, request } from '../services/http'
import { notifyError, toast } from '../lib/notifications'
import {
  createInternalReport,
  deleteInternalReport,
  downloadInternalReport,
  editInternalReport,
  getInternalReport,
  getReportVersions,
  listInternalReports,
  replaceReportPdf,
  type InternalReport,
  type InternalReportDetail,
  type InternalReportVersion,
} from '../services/internal-reports'

const canManage = computed(() => currentUser.value?.role === 'ANALYST')
const rows = ref<InternalReport[]>([]),
  selected = ref<InternalReportDetail | null>(null)
const versions = ref<InternalReportVersion[]>([])
const busy = ref(false),
  loading = ref(false),
  error = ref(''),
  offset = ref(0)
const formOpen = ref(false),
  title = ref(''),
  corpCode = ref(''),
  publishedAt = ref('')
const file = ref<File | null>(null),
  replacement = ref<File | null>(null)
const companyQuery = ref(''),
  companies = ref<{ corp_code: string; company_name: string }[]>([])
const deleting = ref(false)
let detailSequence = 0
async function perform(action: () => Promise<void>) {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    await action()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '처리하지 못했습니다.'
    notifyError(e)
  } finally {
    busy.value = false
  }
}
async function load() {
  loading.value = true
  try {
    rows.value = await listInternalReports(offset.value)
  } finally {
    loading.value = false
  }
}
async function page(delta: number) {
  await perform(async () => {
    offset.value += delta
    selected.value = null
    formOpen.value = false
    await load()
  })
}
async function open(row: InternalReport) {
  const sequence = ++detailSequence
  await perform(async () => {
    const [detail, history] = await Promise.all([
      getInternalReport(row.id),
      getReportVersions(row.id),
    ])
    if (sequence !== detailSequence) return
    selected.value = detail
    versions.value = history
    formOpen.value = false
    deleting.value = false
    replacement.value = null
  })
}
function newReport() {
  selected.value = null
  title.value = ''
  corpCode.value = ''
  publishedAt.value = ''
  file.value = null
  companies.value = []
  companyQuery.value = ''
  formOpen.value = true
  error.value = ''
}
function edit() {
  if (!selected.value) return
  title.value = selected.value.title
  corpCode.value = selected.value.corp_code
  publishedAt.value = selected.value.published_at
  companies.value = [
    { corp_code: selected.value.corp_code, company_name: selected.value.company_name },
  ]
  formOpen.value = true
}
async function searchCompany() {
  await perform(async () => {
    companies.value = (
      await request<{ items: { corp_code: string; company_name: string }[] }>(
        `/disclosures/companies?query=${encodeURIComponent(companyQuery.value)}`,
      )
    ).items.filter((c) => /^\d{8}$/.test(c.corp_code))
  })
}
function pdf(event: Event, replace = false) {
  const value = (event.target as HTMLInputElement).files?.[0] ?? null
  if (value && (!value.name.toLowerCase().endsWith('.pdf') || value.size > 20 * 1024 * 1024)) {
    error.value = '20 MiB 이하의 PDF를 선택해 주세요.'
    ;(event.target as HTMLInputElement).value = ''
    return
  }
  if (replace) replacement.value = value
  else file.value = value
  error.value = ''
}
async function save() {
  await perform(async () => {
    const metadata = {
      title: title.value.trim(),
      corp_code: corpCode.value,
      published_at: publishedAt.value,
    }
    const row = selected.value
      ? await editInternalReport(selected.value.id, metadata, selected.value.current_version)
      : await createInternalReport(metadata, file.value!)
    formOpen.value = false
    selected.value = await getInternalReport(row.id)
    versions.value = await getReportVersions(row.id)
    await load()
    toast.success('내부 리포트를 저장했습니다.')
  })
}
async function replace() {
  if (!selected.value || !replacement.value) return
  await perform(async () => {
    const row = await replaceReportPdf(
      selected.value!.id,
      replacement.value!,
      selected.value!.current_version,
    )
    selected.value = await getInternalReport(row.id)
    versions.value = await getReportVersions(row.id)
    replacement.value = null
    await load()
    toast.success('새 버전을 저장했습니다.')
  })
}
async function remove() {
  if (!selected.value) return
  await perform(async () => {
    await deleteInternalReport(selected.value!.id)
    selected.value = null
    deleting.value = false
    await load()
    toast.success('내부 리포트를 삭제했습니다.')
  })
}
onMounted(() => perform(load))
</script>
<template>
  <section class="reports-page">
    <header class="reports-heading">
      <div>
        <h1>내부 리포트</h1>
        <p class="muted">
          회사에 축적된 참고 자료입니다. 공시 분석에서 해당 기업과 기준일에 맞는 내용을 자동으로
          참고합니다.
        </p>
      </div>
      <button v-if="canManage" class="button primary" :disabled="busy" @click="newReport">
        리포트 등록
      </button>
    </header>
    <p v-if="!canManage" class="small muted">
      조회 권한 · 내부 리포트를 열람하고 분석에 활용할 수 있습니다.
    </p>
    <p v-if="error" class="field-error" role="alert">{{ error }}</p>
    <div class="reports-columns">
      <section class="surface reports-list" aria-label="내부 리포트 목록" :aria-busy="loading">
        <SkeletonState v-if="loading" variant="internal-report-list" :rows="5" />
        <p v-else-if="!rows.length" class="muted">등록된 내부 리포트가 없습니다.</p>
        <template v-if="!loading">
          <button
            v-for="row in rows"
            :key="row.id"
            class="report-row"
            :class="{ chosen: selected?.id === row.id }"
            :disabled="busy"
            @click="open(row)"
          >
            <strong>{{ row.title }}</strong
            ><span
              >{{ row.company_name }} · {{ row.published_at }} · v{{ row.current_version }}</span
            >
          </button>
        </template>
        <div class="reports-actions">
          <button class="button secondary" :disabled="busy || offset === 0" @click="page(-20)">
            이전</button
          ><span>{{ Math.floor(offset / 20) + 1 }} 페이지</span
          ><button class="button secondary" :disabled="busy || rows.length < 20" @click="page(20)">
            다음
          </button>
        </div>
      </section>
      <section class="surface report-detail">
        <form v-if="formOpen && canManage" @submit.prevent="save">
          <h2>{{ selected ? '리포트 정보 수정' : '내부 리포트 등록' }}</h2>
          <fieldset :disabled="busy">
            <label>제목<input v-model="title" maxlength="500" required /></label>
            <div class="reports-actions">
              <label
                >기업 검색<input
                  v-model="companyQuery"
                  placeholder="기업명 또는 기업코드"
                  maxlength="100" /></label
              ><button type="button" class="button secondary" @click="searchCompany">검색</button>
            </div>
            <label
              >대상 기업<select v-model="corpCode" required>
                <option disabled value="">기업을 선택하세요</option>
                <option v-for="c in companies" :key="c.corp_code" :value="c.corp_code">
                  {{ c.company_name }} ({{ c.corp_code }})
                </option>
              </select></label
            >
            <label>발행일<input v-model="publishedAt" type="date" required /></label>
            <label v-if="!selected"
              >원본 PDF<input
                type="file"
                accept=".pdf,application/pdf"
                required
                @change="pdf($event)"
              /><span class="small muted">최대 20 MiB, 300쪽. 텍스트 추출이 가능한 PDF</span></label
            >
            <div class="reports-actions">
              <button
                class="button primary"
                :disabled="!title.trim() || !corpCode || !publishedAt || (!selected && !file)"
              >
                저장</button
              ><button class="button secondary" type="button" @click="formOpen = false">
                취소
              </button>
            </div>
          </fieldset>
        </form>
        <template v-else-if="selected">
          <h2>{{ selected.title }}</h2>
          <p>
            {{ selected.company_name }} · {{ selected.published_at }} · v{{
              selected.current_version
            }}
          </p>
          <div class="reports-actions">
            <button
              class="button secondary"
              :disabled="busy"
              @click="
                perform(() =>
                  downloadInternalReport(
                    selected!.id,
                    selected!.current_version,
                    selected!.original_filename,
                  ),
                )
              "
            >
              원본 다운로드</button
            ><button v-if="canManage" class="button secondary" :disabled="busy" @click="edit">
              정보 수정</button
            ><button
              v-if="canManage"
              class="button secondary"
              :disabled="busy"
              @click="deleting = true"
            >
              삭제
            </button>
          </div>
          <div v-if="deleting" class="delete-report" role="alert">
            <p>삭제하면 새 분석과 리포트 검색에서 제외됩니다. 기존 분석 결과는 유지됩니다.</p>
            <button class="button primary" :disabled="busy" @click="remove">삭제 확인</button
            ><button class="button secondary" :disabled="busy" @click="deleting = false">
              취소
            </button>
          </div>
          <form v-if="canManage" @submit.prevent="replace">
            <label
              >원본 PDF 교체<input
                :key="selected.id + ':' + selected.current_version"
                type="file"
                accept=".pdf,application/pdf"
                :disabled="busy"
                @change="pdf($event, true)" /></label
            ><button class="button secondary" :disabled="busy || !replacement">새 버전 저장</button>
          </form>
          <details>
            <summary>버전 이력</summary>
            <ul>
              <li v-for="v in versions" :key="v.version">
                v{{ v.version }} · {{ v.title }} · {{ v.published_at }}
                <button
                  class="text-button"
                  :disabled="busy"
                  @click="
                    perform(() =>
                      downloadInternalReport(selected!.id, v.version, v.original_filename),
                    )
                  "
                >
                  PDF 다운로드
                </button>
              </li>
            </ul>
            <button
              v-if="versions.length && versions.length % 20 === 0"
              class="text-button"
              :disabled="busy"
              @click="
                perform(async () => {
                  versions.push(...(await getReportVersions(selected!.id, versions.length)))
                })
              "
            >
              이력 더 보기
            </button>
          </details>
          <h3>추출 본문</h3>
          <pre class="report-text">{{ selected.content }}</pre>
        </template>
        <p v-else class="muted">리포트를 선택해 원문과 버전 정보를 확인하세요.</p>
      </section>
    </div>
  </section>
</template>
<style scoped>
.reports-page {
  padding: 28px;
  max-width: 1400px;
  margin: auto;
}
.reports-heading,
.reports-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.reports-heading {
  margin-bottom: 24px;
}
.reports-columns {
  display: grid;
  grid-template-columns: minmax(260px, 1fr) minmax(0, 2fr);
  gap: 20px;
}
.reports-list,
.report-detail {
  padding: 24px;
  align-self: start;
}
.report-row {
  display: flex;
  flex-direction: column;
  text-align: left;
  width: 100%;
  gap: 8px;
  padding: 18px 8px;
  border: 0;
  border-bottom: 1px solid var(--border, #ddd);
  background: transparent;
  cursor: pointer;
}
.report-row.chosen {
  background: var(--muted, #f0f3f7);
}
.report-row span {
  font-size: 13px;
  color: var(--text-muted, #667085);
}
.reports-actions {
  justify-content: flex-start;
  flex-wrap: wrap;
  margin: 16px 0;
}
fieldset {
  border: 0;
  padding: 0;
  margin: 0;
}
label {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin: 14px 0;
}
input,
select {
  padding: 10px;
  width: 100%;
  border: 1px solid var(--border, #ddd);
  border-radius: 8px;
}
.report-text {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  max-height: 65vh;
  overflow: auto;
  font-family: inherit;
  font-size: 14px;
  line-height: 1.8;
}
details {
  margin-top: 24px;
}
li {
  margin: 10px 0;
}
.delete-report {
  padding: 12px;
  border: 1px solid #c55;
  margin: 16px 0;
}
@media (max-width: 760px) {
  .reports-columns {
    grid-template-columns: 1fr;
  }
  .reports-heading {
    align-items: flex-start;
    flex-direction: column;
  }
  .reports-page {
    padding: 16px;
  }
}
</style>
