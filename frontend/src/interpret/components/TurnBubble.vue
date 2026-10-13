<template>
  <div :class="cn('flex', turn.speaker === 'citizen' ? 'justify-end' : 'justify-start')">
    <div
      :class="
        cn(
          'max-w-[85%] space-y-2 rounded-xl border px-4 py-3',
          turn.speaker === 'citizen' ? 'bg-primary/5' : 'bg-card',
        )
      "
    >
      <p
        class="text-xl font-medium leading-snug"
        :lang="turn.target_language"
        :dir="LANGUAGE_COPY[turn.target_language].dir"
      >
        {{ turn.translation }}
      </p>
      <p
        class="text-sm text-muted-foreground"
        :lang="turn.source_language"
        :dir="LANGUAGE_COPY[turn.source_language].dir"
      >
        {{ turn.transcript }}
      </p>
      <div class="flex items-center justify-between gap-3 text-xs text-muted-foreground">
        <span>
          {{ LANGUAGE_COPY[turn.source_language].name }} →
          {{ LANGUAGE_COPY[turn.target_language].name }}
        </span>
        <Button
          v-if="turn.audio_base64"
          variant="ghost"
          size="sm"
          class="h-7 px-2"
          :aria-label="$t('interpret.replay')"
          @click="$emit('replay', turn)"
        >
          <Volume2 class="h-4 w-4" />
        </Button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { Volume2 } from '@lucide/vue'
import { Button } from '@/foundation/components/ui/button'
import { cn } from '@/foundation/lib/utils'
import { LANGUAGE_COPY } from '@/interpret/constants'
import type { TurnOut } from '@/interpret/types/interpret'

defineProps<{ turn: TurnOut }>()
defineEmits<{ (e: 'replay', turn: TurnOut): void }>()
</script>
