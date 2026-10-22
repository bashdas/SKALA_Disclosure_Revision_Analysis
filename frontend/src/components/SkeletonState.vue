<script setup lang="ts">
import { Skeleton } from './ui/skeleton'
withDefaults(
  defineProps<{
    rows?: number
    header?: boolean
    variant?:
      | 'filings'
      | 'directory'
      | 'company'
      | 'home'
      | 'market'
      | 'chart'
      | 'price'
      | 'stats'
      | 'analysis'
      | 'report'
      | 'memo-upload'
      | 'memo-write'
      | 'analysis-form'
      | 'account-form'
      | 'login-form'
      | 'login'
      | 'document'
  }>(),
  { rows: 4, variant: 'filings', header: false },
)
</script>
<template>
  <div class="skeleton-state" :class="'skeleton-' + variant" role="status" aria-label="불러오는 중">
    <div v-if="variant === 'directory' || variant === 'home'" aria-hidden="true">
      <div v-if="header || variant === 'home'" class="sk-page-heading">
        <Skeleton class="skeleton sk-page-title" /><Skeleton
          v-if="variant === 'directory'"
          class="skeleton sk-search"
        />
      </div>
      <SkeletonState v-if="variant === 'home'" variant="market" />
      <div v-if="variant === 'home'" class="sk-section-heading">
        <Skeleton class="skeleton sk-title" /><Skeleton class="skeleton sk-search" />
      </div>
      <div class="sk-table-shell">
        <div class="sk-table" :class="{ 'sk-watchlist': variant === 'home' }">
          <div class="sk-table-row sk-table-head">
            <span>종목</span><span>현재가</span><span>등락률</span><span>거래대금</span
            ><span>시가총액</span><span v-if="variant === 'directory'">업데이트</span
            ><span>산업군</span><span></span>
          </div>
          <div v-for="i in rows" :key="i" class="sk-table-row">
            <div class="sk-table-company">
              <Skeleton class="skeleton sk-avatar" />
              <div class="sk-copy">
                <Skeleton class="skeleton sk-line" /><Skeleton class="skeleton sk-caption" />
              </div>
            </div>
            <Skeleton v-for="j in 4" :key="j" class="skeleton sk-number" />
            <div v-if="variant === 'directory'" class="sk-badges">
              <Skeleton v-for="j in 3" :key="j" class="skeleton" />
            </div>
            <Skeleton class="skeleton sk-number" />
            <Skeleton class="skeleton sk-star" />
          </div>
        </div>
      </div>
    </div>

    <div v-else-if="variant === 'company'" aria-hidden="true">
      <div class="sk-company-header">
        <div class="sk-company-main">
          <div class="sk-company-identity">
            <div class="sk-company-name">
              <Skeleton class="skeleton sk-logo" />
              <div class="sk-copy">
                <Skeleton class="skeleton sk-caption" /><Skeleton class="skeleton sk-page-title" />
              </div>
            </div>
            <div class="sk-identity-price">
              <SkeletonState variant="price" />
            </div>

          </div>
          <div class="sk-company-panel">
            <SkeletonState variant="chart" />
            <div class="sk-day-prices"><Skeleton v-for="i in 3" :key="i" class="skeleton sk-line" /></div>
            <SkeletonState variant="stats" :rows="3" />
            <SkeletonState variant="stats" :rows="3" />
          </div>
        </div>
      </div>
      <div class="sk-tabs"><Skeleton v-for="i in 4" :key="i" class="skeleton" /></div>
      <div class="sk-section-heading"><Skeleton class="skeleton sk-title" /></div>
      <div class="sk-filters">
        <Skeleton class="skeleton" /><Skeleton class="skeleton" /><Skeleton
          class="skeleton"
        /><Skeleton class="skeleton" />
      </div>
      <SkeletonState variant="filings" :rows="rows" />
    </div>

    <div v-else-if="variant === 'market'" class="sk-market-viewport" aria-hidden="true">
      <div class="sk-market-filters"><Skeleton v-for="i in 5" :key="i" class="skeleton" /></div>
      <div class="sk-market-board">
        <div class="sk-featured">
          <Skeleton class="skeleton sk-title" /><Skeleton class="skeleton sk-price" /><Skeleton
            class="skeleton sk-featured-chart"
          />
        </div>
        <div class="sk-market-grid">
          <div v-for="i in 11" :key="i" class="sk-market-item">
            <Skeleton class="skeleton sk-mini-chart" />
            <div class="sk-copy">
              <Skeleton class="skeleton sk-caption" /><Skeleton class="skeleton sk-line" />
            </div>
          </div>
        </div>
      </div>
    </div>

    <div v-else-if="variant === 'chart'" class="sk-chart" aria-hidden="true">
      <Skeleton class="skeleton sk-chart-area" />
      <div class="sk-chart-dates"><Skeleton class="skeleton" /><Skeleton class="skeleton" /></div>
    </div>
    <div v-else-if="variant === 'price'" class="sk-price-row" aria-hidden="true">
      <Skeleton class="skeleton sk-price" /><Skeleton class="skeleton sk-delta" />
    </div>
    <div v-else-if="variant === 'stats'" class="sk-stats" aria-hidden="true">
      <div v-for="i in (rows === 3 ? 3 : 6)" :key="i" class="sk-copy">
        <Skeleton class="skeleton sk-caption" /><Skeleton class="skeleton sk-line" />
      </div>
    </div>

    <div v-else-if="variant === 'analysis' || variant === 'report'" aria-hidden="true">
      <template v-if="variant === 'analysis'">
        <Skeleton class="skeleton sk-back" />
        <div class="sk-page-heading">
          <div class="sk-copy">
            <Skeleton class="skeleton sk-caption" /><Skeleton
              class="skeleton sk-page-title"
            /><Skeleton class="skeleton sk-title" />
          </div>
          <Skeleton class="skeleton sk-badge" />
        </div>
        <div class="sk-section-heading">
          <Skeleton class="skeleton sk-title" /><Skeleton class="skeleton sk-title" />
        </div>
        <div class="sk-timeline">
          <div v-for="i in 7" :key="i" class="sk-copy">
            <Skeleton class="skeleton sk-star" /><Skeleton class="skeleton sk-caption" />
          </div>
        </div>
        <div class="sk-report-summary">
          <Skeleton class="skeleton sk-caption" /><Skeleton
            class="skeleton sk-page-title"
          /><Skeleton class="skeleton sk-line" />
          <div class="sk-report-cards"><Skeleton v-for="i in 3" :key="i" class="skeleton" /></div>
        </div>
      </template>
      <div class="sk-report-body">
        <div class="sk-section-heading">
          <Skeleton class="skeleton sk-title" /><Skeleton class="skeleton sk-submit" />
        </div>
        <div v-for="i in 4" :key="i" class="sk-paragraph">
          <Skeleton class="skeleton sk-title" /><Skeleton
            v-for="j in 3"
            :key="j"
            class="skeleton sk-line"
            :class="{ short: j === 3 }"
          />
        </div>
      </div>
    </div>

    <div
      v-else-if="
        [
          'memo-upload',
          'memo-write',
          'analysis-form',
          'account-form',
          'login-form',
          'login',
        ].includes(variant)
      "
      class="sk-form"
      :class="{ 'sk-login': variant === 'login' }"
      aria-hidden="true"
    >
      <Skeleton v-if="variant === 'login'" class="skeleton sk-page-title" />
      <div v-if="variant === 'memo-upload'" class="sk-dropzone">
        <Skeleton class="skeleton sk-avatar" /><Skeleton class="skeleton sk-title" /><Skeleton
          class="skeleton sk-caption"
        />
      </div>
      <div
        v-for="i in variant === 'account-form'
          ? 3
          : variant === 'analysis-form' || variant === 'login'
            ? 2
            : variant === 'login-form'
              ? rows
              : 1"
        :key="i"
        class="sk-field"
      >
        <Skeleton class="skeleton sk-field-label" /><Skeleton class="skeleton sk-input" />
      </div>
      <div v-if="variant === 'memo-write'" class="sk-field">
        <Skeleton class="skeleton sk-field-label" /><Skeleton class="skeleton sk-textarea" />
      </div>
      <div v-if="variant === 'account-form'" class="sk-copy">
        <Skeleton class="skeleton sk-line" /><Skeleton class="skeleton sk-caption" />
      </div>
      <Skeleton class="skeleton sk-submit" />
    </div>

    <div v-else-if="variant === 'document'" class="sk-document" aria-hidden="true">
      <Skeleton class="skeleton sk-caption" /><Skeleton class="skeleton sk-page-title" /><Skeleton
        class="skeleton sk-title"
      />
      <div v-for="i in rows" :key="i" class="sk-paragraph">
        <Skeleton v-for="j in 3" :key="j" class="skeleton sk-line" :class="{ short: j === 3 }" />
      </div>
    </div>

    <div v-else aria-hidden="true">
      <div v-for="i in rows" :key="i" class="sk-filing">
        <Skeleton class="skeleton sk-avatar" />
        <div class="sk-filing-copy">
          <div class="sk-badges"><Skeleton class="skeleton" /><Skeleton class="skeleton" /></div>
          <Skeleton class="skeleton sk-title" /><Skeleton class="skeleton sk-caption" />
        </div>
        <Skeleton class="skeleton sk-action" />
      </div>
    </div>
  </div>
</template>
<style scoped>
.skeleton-state {
  width: 100%;
  min-width: 0;
}
.skeleton-state .skeleton {
  border-radius: 5px;
}
.sk-copy {
  display: grid;
  gap: 10px;
  min-width: 0;
  flex: 1;
}
.sk-line {
  width: 85%;
  height: 16px;
}
.sk-line.short {
  width: 57%;
}
.sk-caption {
  width: 55%;
  height: 12px;
}
.sk-title {
  width: 210px;
  max-width: 80%;
  height: 20px;
}
.sk-page-title {
  width: 300px;
  max-width: 100%;
  height: 30px;
}
.sk-page-heading {
  display: flex;
  justify-content: space-between;
  gap: 24px;
  align-items: center;
  margin-bottom: 28px;
}
.sk-section-heading {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 20px;
  padding: 20px;
}
.sk-search {
  width: 240px;
  height: 40px;
}
.sk-avatar {
  width: 40px;
  height: 40px;
  border-radius: 10px !important;
  flex-shrink: 0;
}
.sk-star {
  width: 16px;
  height: 16px;
}
.sk-badge {
  width: 90px;
  height: 28px;
}
.sk-number {
  height: 16px;
  width: 75%;
  justify-self: end;
}
.sk-table-shell {
  border: 1px solid var(--line);
  border-radius: 12px;
  overflow: hidden;
}
.sk-table {
  min-width: 1100px;
}
.sk-table-row {
  display: grid;
  grid-template-columns: minmax(180px, 1.8fr) repeat(4, minmax(90px, 1fr)) 180px 110px 24px;
  align-items: center;
  gap: 20px;
  padding: 16px 20px;
  border-bottom: 1px solid var(--line);
  min-height: 65px;
}
.sk-table-row:last-child {
  border-bottom: 0;
}
.sk-table-row.sk-table-head {
  min-height: 38px;
  padding-block: 10px;
  color: var(--muted);
  font-size: 12px;
  background: var(--surface);
}
.sk-table-head span:nth-child(n + 2):nth-child(-n + 5) {
  text-align: right;
}
.sk-watchlist .sk-table-row {
  grid-template-columns: minmax(180px, 1.8fr) repeat(4, minmax(90px, 1fr)) 110px 24px;
}
.sk-table-company {
  display: flex;
  align-items: center;
  gap: 12px;
}
.sk-badges {
  display: flex;
  gap: 8px;
}
.sk-badges .skeleton {
  width: 52px;
  height: 22px;
}
.sk-back {
  width: 80px;
  height: 18px;
  margin-bottom: 24px;
}
.sk-company-header {
  padding: 24px 43px;
}

.sk-company-main {
  display: grid;
  grid-template-columns: minmax(260px, 0.85fr) minmax(0, 1.4fr);
  gap: 48px;
  align-items: start;
}
.sk-company-panel {
  display: grid;
  grid-template-columns: 190px minmax(0, 1fr);
  gap: 32px;
  padding-top: 4px;
}
.sk-identity-price {
  margin-top: 24px;
}
.sk-company-top {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 190px;
  gap: 24px;
  align-items: center;
}
.sk-company-name {
  display: flex;
  gap: 18px;
  align-items: center;
}
.sk-logo {
  width: 64px;
  height: 64px;
  border-radius: 16px !important;
  flex-shrink: 0;
}
.sk-price {
  width: 200px;
  height: 40px;
  margin-top: 24px;
}
.sk-price-row {
  display: flex;
  gap: 14px;
  align-items: end;
}
.sk-delta {
  width: 75px;
  height: 20px;
}
.sk-chart-area {
  height: 88px;
  width: 100%;
  opacity: 0.65;
}
.sk-chart-dates {
  display: flex;
  justify-content: space-between;
  margin-top: 12px;
}
.sk-chart-dates > .skeleton {
  width: 38px;
  height: 12px;
}

.sk-stats {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 26px 28px;
  padding-top: 0;
  margin-top: 0;
}
.sk-stats .sk-copy {
  display: grid;
  gap: 5px;
}

.sk-stats .sk-caption {
  width: 80px;
  height: 11px;
}
.sk-stats .sk-line {
  width: 70px;
  height: 17px;
}
.sk-price-row {
  margin-top: 8px;
}
.sk-price-row .sk-price {
  margin-top: 0;
  width: 160px;
  height: 32px;
}
.sk-tabs {
  display: flex;
  gap: 32px;
  padding: 16px 43px;
  border-bottom: 1px solid var(--line);
}
.sk-tabs > .skeleton {
  width: 90px;
  height: 20px;
}
.sk-filters {
  display: grid;
  grid-template-columns: minmax(180px, 1fr) 156px 156px 80px;
  gap: 12px;
  padding: 20px 43px 24px;
  border-bottom: 1px solid var(--line);
}
.sk-filters > .skeleton {
  height: 44px;
}
.sk-filing {
  display: grid;
  grid-template-columns: 39px minmax(0, 1fr) auto;
  gap: 24px;
  padding: 26px 43px;
  align-items: center;
  border-bottom: 1px solid var(--line);
}
.sk-filing-copy {
  display: grid;
  gap: 14px;
}
.sk-filing-copy .sk-title {
  width: 60%;
}
.sk-action {
  width: 90px;
  height: 18px;
}
.sk-market-viewport {
  overflow: hidden;
  margin-bottom: 28px;
}
.sk-market-filters {
  display: flex;
  gap: 10px;
  margin-bottom: 18px;
}
.sk-market-filters > .skeleton {
  width: 65px;
  height: 25px;
}
.sk-market-board {
  display: grid;
  grid-template-columns: 250px minmax(0, 1fr);
  min-width: 1120px;
  padding-block: 12px;
}
.sk-featured {
  padding-right: 24px;
  border-right: 1px solid var(--line);
}
.sk-featured-chart {
  height: 134px;
  margin-top: 18px;
}
.sk-market-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  row-gap: 16px;
}
.sk-market-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding-inline: 18px;
  min-height: 44px;
}
.sk-mini-chart {
  width: 64px;
  height: 42px;
  flex-shrink: 0;
}
.sk-timeline {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  padding: 24px;
  gap: 20px;
  border: 1px solid var(--line);
  border-radius: 12px;
}
.sk-report-summary {
  padding: 28px;
  margin-top: 24px;
  border: 1px solid var(--line);
  border-radius: 12px;
  display: grid;
  gap: 18px;
}
.sk-report-cards {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 20px;
}
.sk-report-cards > .skeleton {
  height: 80px;
}
.sk-report-body {
  margin-top: 28px;
  border: 1px solid var(--line);
  border-radius: 12px;
  overflow: hidden;
}
.sk-paragraph {
  padding: 20px 24px;
  display: grid;
  gap: 12px;
}
.sk-form {
  display: grid;
  gap: 20px;
  margin-top: 22px;
  text-align: left;
}
.sk-field {
  display: grid;
  gap: 8px;
}
.sk-field-label {
  width: 90px;
  height: 14px;
}
.sk-input {
  height: 44px;
  width: 100%;
  border-radius: 8px !important;
}
.sk-textarea {
  height: 240px;
  width: 100%;
  border-radius: 12px !important;
}
.sk-submit {
  height: 44px;
  width: 100%;
  border-radius: 8px !important;
}
.sk-dropzone {
  min-height: 160px;
  border: 1px dashed var(--line);
  background: var(--surface);
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  gap: 12px;
}
.sk-dropzone .sk-caption {
  width: 140px;
}
.sk-login {
  width: min(420px, 100%);
  margin: 42px auto;
  padding: 28px;
  border: 1px solid var(--line);
  border-radius: 12px;
}
.sk-document {
  display: grid;
  gap: 18px;
}
.sk-document .sk-paragraph {
  padding-inline: 0;
}
@media (max-width: 930px) {
  .sk-company-main {
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    gap: 28px;
  }
  .sk-filters {
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) 80px;
  }
  .sk-filters > .skeleton:first-child {
    grid-column: 1 / -1;
  }
}
@media (max-width: 650px) {
  .sk-company-header {
    padding-inline: 19px;
  }
  .sk-company-main {
    grid-template-columns: minmax(0, 1fr);
    gap: 24px;
  }
  .sk-logo {
    width: 52px;
    height: 52px;
  }
  .sk-stats {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .sk-tabs {
    gap: 18px;
    padding-inline: 19px;
  }
  .sk-tabs > .skeleton {
    width: 65px;
  }
  .sk-filters {
    padding-inline: 19px;
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .sk-filing {
    padding-inline: 19px;
    grid-template-columns: 39px minmax(0, 1fr);
    gap: 12px;
  }
  .sk-filing .sk-action {
    grid-column: 2;
    justify-self: end;
  }
  .sk-page-heading {
    flex-wrap: wrap;
  }
  .sk-timeline {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }
  .sk-report-cards {
    grid-template-columns: minmax(0, 1fr);
  }
  .sk-report-body .sk-section-heading .sk-submit {
    width: 100px;
  }
}

@media (max-width: 1000px) {
  .sk-company-main {
    grid-template-columns: minmax(0, 1fr);
    gap: 24px;
  }
  .sk-company-panel {
    width: 100%;
  }
}
@media (max-width: 650px) {
  .sk-company-panel {
    grid-template-columns: 130px minmax(0, 1fr);
    gap: 20px;
    padding: 0;
  }
  .sk-company-top {
    grid-template-columns: minmax(0, 1fr) 130px;
    gap: 16px;
  }
  .sk-stats {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 18px 16px;
  }
  .sk-stats .sk-copy {
    display: grid;
    gap: 5px;
  }

  .sk-chart-area {
    height: 72px;
  }
}
.skeleton-directory .sk-page-title {
  height: 20px;
  width: 160px;
}
.skeleton-directory .sk-page-heading {
  margin-bottom: 17px;
}
.sk-day-prices { display: grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap: 16px; margin-top: 24px; max-width: 380px; height: 40px; align-items: end; }

.sk-company-main { display: flex; flex-direction: column; gap: 32px; }
.sk-company-identity { display: flex; justify-content: space-between; align-items: flex-start; gap: 32px; width: 100%; }
.sk-identity-price { margin: 0; }
.sk-company-panel { width: 100%; grid-template-columns: 190px 204px minmax(0, 1fr); gap: 32px; padding: 28px 0 8px; border-top: 1px solid var(--line); }
.sk-day-prices { display: grid; grid-template-columns: 1fr; gap: 16px; margin: 0; height: 113px; padding-left: 24px; padding-right: 28px; }
@media(max-width: 1000px) { .sk-company-panel { grid-template-columns: 190px minmax(0, 1fr); } .sk-company-panel > .skeleton-stats { grid-column: 1 / -1; } }
@media(max-width: 650px) { .sk-company-identity { align-items: flex-start; flex-direction: column; gap: 24px; } .sk-company-panel { grid-template-columns: 130px minmax(0,1fr); gap: 24px; padding-top: 24px; } }

.sk-company-panel { grid-template-columns: repeat(4, minmax(0,1fr)); gap: 0; }
.sk-company-panel > * { padding-inline: 32px; min-width: 0; }
.sk-company-panel > :first-child { padding-left: 0; }
.sk-company-panel > :last-child { padding-right: 24px; }
.sk-company-panel > :not(:first-child) { border-left: 1px solid var(--line); }
.sk-company-panel :deep(.sk-chart-area), .sk-company-panel :deep(.sk-chart-dates) { width: 100%; max-width: 100%; }
.sk-company-panel :deep(.sk-stats) { grid-template-columns: 1fr; }
@media(max-width: 1000px) { .sk-company-panel { grid-template-columns: repeat(2,minmax(0,1fr)); row-gap: 28px; } .sk-company-panel > .skeleton-stats { grid-column: auto; } .sk-company-panel > :nth-child(3) { border: 0; padding-left: 0; } }
@media(max-width: 650px) { .sk-company-panel > * { padding-inline: 20px; } .sk-company-panel > :first-child, .sk-company-panel > :nth-child(3) { padding-left: 0; } .sk-company-panel > :nth-child(even) { padding-right: 0; } .sk-company-panel :deep(.sk-chart-area), .sk-company-panel :deep(.sk-chart-dates) { width: 100%; } }

.sk-company-panel > * { padding-inline: 24px; }
.sk-company-panel :deep(.sk-chart-area), .sk-company-panel :deep(.sk-chart-dates) { margin-inline: 0; }
.sk-company-panel :deep(.sk-stats), .sk-day-prices { justify-content: center; }
@media(max-width: 650px) { .sk-company-panel > * { padding-inline: 12px; } }

.sk-company-panel > :first-child { padding-left: 0; display: flex; flex-direction: column; justify-content: center; }
.sk-company-panel > :last-child { padding-right: 24px; }
.sk-company-panel > :last-child :deep(.sk-stats) { justify-content: end; }
.sk-company-panel :deep(.sk-stats) { grid-template-columns: minmax(0,1fr); }
@media(max-width: 650px) { .sk-company-panel > :last-child { padding-right: 12px; } }
</style>
