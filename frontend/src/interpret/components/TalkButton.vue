<template>
  <button
    type="button"
    :lang="language"
    :dir="copy.dir"
    :disabled="disabled"
    :aria-pressed="recording"
    :class="
      cn(
        'flex min-h-28 w-full touch-none select-none flex-col items-center justify-center gap-2 rounded-xl border-2 px-4 py-5 text-center transition-colors',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50',
        recording
          ? 'border-destructive bg-destructive/10 text-destructive'
          : 'border-primary/30 bg-primary/5 hover:bg-primary/10',
      )
    "
    @pointerdown.prevent="press"
    @pointerup="release"
    @pointerleave="release"
    @pointercancel="release"
    @keydown.space.prevent="toggle"
    @keydown.enter.prevent="toggle"
    @contextmenu.prevent
  >
    <Mic :class="cn('h-8 w-8', recording && 'animate-pulse')" />
    <span class="text-lg font-semibold">{{ recording ? copy.listening : copy.hold }}</span>
    <span class="text-sm text-muted-foreground">{{ copy.name }}</span>
  </button>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Mic } from '@lucide/vue'
import { cn } from '@/foundation/lib/utils'
import { LANGUAGE_COPY } from '@/interpret/constants'
import type { Language } from '@/interpret/types/interpret'

const props = defineProps<{ language: Language; recording: boolean; disabled?: boolean }>()
const emit = defineEmits<{ (e: 'start'): void; (e: 'stop'): void }>()

const copy = computed(() => LANGUAGE_COPY[props.language])

// Press and hold with a finger or mouse; keyboard users press once to start
// and again to stop.
function press() {
  if (!props.disabled && !props.recording) emit('start')
}

function release() {
  if (props.recording) emit('stop')
}

function toggle() {
  if (props.recording) emit('stop')
  else press()
}
</script>
