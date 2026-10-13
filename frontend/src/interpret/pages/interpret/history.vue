<route lang="yaml">
meta:
  layout: dashboard
  requiresAuth: true
  permission: read:interpret_usage
  breadcrumb: nav.interpretHistory
</route>

<template>
  <div class="animate-fade-in">
    <PageHeader
      :title="$t('interpretHistory.title')"
      :description="$t('interpretHistory.description')"
    />

    <DataTable
      :columns="columns"
      :items="items"
      :total="total"
      :page="pagination.page"
      :page-size="pagination.pageSize"
      :total-pages="totalPages"
      :loading="isLoading"
      :empty-title="$t('interpretHistory.emptyTitle')"
      :empty-description="$t('interpretHistory.emptyDescription')"
      @sort="setSort"
      @update:page="goToPage"
      @update:page-size="setPageSize"
    >
      <template #row="{ item }">
        <TableCell class="text-sm">{{ formatDateTime(item.created_at) }}</TableCell>
        <TableCell class="text-sm">
          {{ LANGUAGE_COPY[item.staff_language].name }} ⇄
          {{ LANGUAGE_COPY[item.citizen_language].name }}
        </TableCell>
        <TableCell class="text-sm">{{ item.turn_count }}</TableCell>
        <TableCell class="text-sm">{{ formatMinutes(item.audio_ms) }}</TableCell>
        <TableCell>
          <Badge :variant="item.ended_at ? 'secondary' : 'default'" class="text-xs">
            {{ item.ended_at ? $t('interpretHistory.ended') : $t('interpretHistory.open') }}
          </Badge>
        </TableCell>
      </template>
    </DataTable>
  </div>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { Badge } from '@/foundation/components/ui/badge'
import { TableCell } from '@/foundation/components/ui/table'
import PageHeader from '@/foundation/components/common/PageHeader.vue'
import DataTable from '@/foundation/components/common/DataTable.vue'
import { useDataTable } from '@/foundation/composables/useDataTable'
import { useFormatDate } from '@/foundation/composables/useFormatDate'
import { LANGUAGE_COPY } from '@/interpret/constants'
import { useInterpretStore } from '@/interpret/stores/interpret'
import type { ConversationOut } from '@/interpret/types/interpret'

const { t } = useI18n()
const store = useInterpretStore()
const { formatDateTime } = useFormatDate()

const columns = [
  { key: 'created_at', label: t('interpretHistory.columns.started'), sortable: true },
  { key: 'citizen_language', label: t('interpretHistory.columns.languages'), sortable: true },
  { key: 'turn_count', label: t('interpretHistory.columns.turns'), sortable: true },
  { key: 'audio_ms', label: t('interpretHistory.columns.speech') },
  { key: 'ended_at', label: t('interpretHistory.columns.status') },
]

const { items, total, isLoading, totalPages, pagination, goToPage, setPageSize, setSort } =
  useDataTable<ConversationOut>({ fetcher: store.list })

function formatMinutes(ms: number): string {
  return t('interpretHistory.minutes', { minutes: (ms / 60_000).toFixed(1) })
}
</script>
