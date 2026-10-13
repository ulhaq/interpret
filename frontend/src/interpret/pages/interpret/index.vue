<route lang="yaml">
meta:
  layout: dashboard
  requiresAuth: true
  permission: use:interpret
  breadcrumb: nav.interpret
</route>

<template>
  <div class="animate-fade-in mx-auto max-w-3xl">
    <template v-if="!store.conversation">
      <PageHeader :title="$t('interpret.title')" :description="$t('interpret.description')" />

      <div class="rounded-lg border bg-card p-5 space-y-4">
        <h2 class="font-semibold">{{ $t('interpret.chooseLanguage') }}</h2>
        <div class="grid gap-3 sm:grid-cols-3">
          <Button
            v-for="language in CITIZEN_LANGUAGES"
            :key="language"
            variant="outline"
            class="h-20 text-lg"
            :lang="language"
            :disabled="starting"
            @click="startConversation(language)"
          >
            {{ LANGUAGE_COPY[language].name }}
          </Button>
        </div>
        <p class="text-sm text-muted-foreground">{{ $t('interpret.privacy') }}</p>
      </div>
    </template>

    <div v-else class="flex min-h-[calc(100dvh-10rem)] flex-col gap-4">
      <div class="flex items-center justify-between gap-3">
        <div class="flex items-center gap-2 text-sm font-medium">
          <Languages class="h-4 w-4 text-muted-foreground" />
          {{ LANGUAGE_COPY.da.name }} ⇄ {{ LANGUAGE_COPY[citizenLanguage].name }}
        </div>
        <Button variant="outline" size="sm" :disabled="busy" @click="endConversation">
          {{ $t('interpret.end') }}
        </Button>
      </div>

      <div class="grid gap-1 rounded-lg border bg-muted/40 px-4 py-2 text-xs text-muted-foreground">
        <p lang="da">{{ LANGUAGE_COPY.da.notice }}</p>
        <p :lang="citizenLanguage" :dir="LANGUAGE_COPY[citizenLanguage].dir">
          {{ LANGUAGE_COPY[citizenLanguage].notice }}
        </p>
      </div>

      <div ref="turnList" class="flex-1 space-y-3 overflow-y-auto" aria-live="polite">
        <p v-if="store.turns.length === 0" class="py-10 text-center text-muted-foreground">
          {{ $t('interpret.empty') }}
        </p>
        <TurnBubble v-for="(turn, i) in store.turns" :key="i" :turn="turn" @replay="play" />
        <div
          v-if="translating"
          class="flex items-center justify-center gap-2 py-2 text-sm text-muted-foreground"
        >
          <Loader2 class="h-4 w-4 animate-spin" />
          {{ $t('interpret.translating') }}
        </div>
      </div>

      <div class="grid grid-cols-2 gap-3">
        <TalkButton
          language="da"
          :recording="recordingSpeaker === 'staff'"
          :disabled="busy && recordingSpeaker !== 'staff'"
          @start="startTurn('staff')"
          @stop="finishTurn"
        />
        <TalkButton
          :language="citizenLanguage"
          :recording="recordingSpeaker === 'citizen'"
          :disabled="busy && recordingSpeaker !== 'citizen'"
          @start="startTurn('citizen')"
          @stop="finishTurn"
        />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Languages, Loader2 } from '@lucide/vue'
import PageHeader from '@/foundation/components/common/PageHeader.vue'
import { Button } from '@/foundation/components/ui/button'
import { useConfirm } from '@/foundation/composables/useConfirm'
import { useErrorHandler } from '@/foundation/composables/useErrorHandler'
import { useToast } from '@/foundation/composables/useToast'
import TalkButton from '@/interpret/components/TalkButton.vue'
import TurnBubble from '@/interpret/components/TurnBubble.vue'
import { useWavRecorder } from '@/interpret/composables/useWavRecorder'
import { CITIZEN_LANGUAGES, LANGUAGE_COPY } from '@/interpret/constants'
import { useInterpretStore } from '@/interpret/stores/interpret'
import type { Language, Speaker, TurnOut } from '@/interpret/types/interpret'

const { t } = useI18n()
const store = useInterpretStore()
const recorder = useWavRecorder()
const { confirm } = useConfirm()
const { toast } = useToast()
const { handleError } = useErrorHandler()

const starting = ref(false)
const translating = ref(false)
const recordingSpeaker = ref<Speaker | null>(null)
const turnList = ref<HTMLElement | null>(null)
let player: HTMLAudioElement | null = null

const citizenLanguage = computed<Language>(() => store.conversation?.citizen_language ?? 'en')
const busy = computed(() => translating.value || recordingSpeaker.value !== null)

async function startConversation(language: Language) {
  starting.value = true
  try {
    // Ask for the microphone first, so the first press records right away.
    await recorder.open()
    await store.start(language)
  } catch (err: unknown) {
    if (err instanceof DOMException) {
      toast({ title: t('interpret.microphoneDenied'), variant: 'destructive' })
    } else {
      recorder.close()
      handleError(err)
    }
  } finally {
    starting.value = false
  }
}

async function startTurn(speaker: Speaker) {
  if (busy.value) return
  stopPlayback()
  recordingSpeaker.value = speaker
  try {
    await recorder.start()
  } catch {
    recordingSpeaker.value = null
    toast({ title: t('interpret.microphoneDenied'), variant: 'destructive' })
  }
}

async function finishTurn() {
  const speaker = recordingSpeaker.value
  recordingSpeaker.value = null
  const audio = recorder.stop()
  if (!speaker || !audio) return
  translating.value = true
  await scrollToEnd()
  try {
    const turn = await store.takeTurn(speaker, audio)
    play(turn)
  } catch (err: unknown) {
    handleError(err)
  } finally {
    translating.value = false
    await scrollToEnd()
  }
}

function play(turn: TurnOut) {
  if (!turn.audio_base64) return
  stopPlayback()
  player = new Audio(`data:${turn.audio_mime_type};base64,${turn.audio_base64}`)
  void player.play().catch(() => {
    // Autoplay can be refused; the replay button is still there.
  })
}

function stopPlayback() {
  player?.pause()
  player = null
}

async function scrollToEnd() {
  await nextTick()
  turnList.value?.scrollTo({ top: turnList.value.scrollHeight, behavior: 'smooth' })
}

async function endConversation() {
  const ok = await confirm(
    t('interpret.endTitle'),
    t('interpret.endDescription'),
    t('interpret.end'),
  )
  if (!ok) return
  stopPlayback()
  recorder.close()
  try {
    await store.end()
  } catch (err: unknown) {
    handleError(err)
  }
}

// Leaving the page ends the conversation: what was said is forgotten.
onBeforeUnmount(() => {
  stopPlayback()
  if (store.conversation) void store.end().catch(() => {})
})
</script>
