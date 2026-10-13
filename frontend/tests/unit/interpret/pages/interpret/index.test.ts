import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { ref } from 'vue'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import Interpret from '@/interpret/pages/interpret/index.vue'
import { i18n } from '@/plugins/i18n'
import { LANGUAGE_COPY } from '@/interpret/constants'
import { useInterpretStore } from '@/interpret/stores/interpret'
import type { ConversationOut, Language, TurnOut } from '@/interpret/types/interpret'

const t = i18n.global.t

const confirm = vi.fn(async (..._args: unknown[]) => true)
const toast = vi.fn()
const handleError = vi.fn()
vi.mock('@/foundation/composables/useConfirm', () => ({ useConfirm: () => ({ confirm }) }))
vi.mock('@/foundation/composables/useToast', () => ({ useToast: () => ({ toast }) }))
vi.mock('@/foundation/composables/useErrorHandler', () => ({
  useErrorHandler: () => ({ handleError }),
}))

const recording = new Blob(['wav'], { type: 'audio/wav' })
const recorder = {
  isOpen: ref(false),
  isRecording: ref(false),
  open: vi.fn(async () => {}),
  start: vi.fn(async () => {}),
  stop: vi.fn((): Blob | null => recording),
  close: vi.fn(),
}
vi.mock('@/interpret/composables/useWavRecorder', () => ({ useWavRecorder: () => recorder }))

function conversation(citizen: Language): ConversationOut {
  return {
    id: 7,
    organization_id: 1,
    user_id: 1,
    staff_language: 'da',
    citizen_language: citizen,
    turn_count: 0,
    audio_ms: 0,
    ended_at: null,
    created_at: '2026-10-12T09:00:00Z',
    updated_at: '2026-10-12T09:00:00Z',
  }
}

const STAFF_TURN: TurnOut = {
  speaker: 'staff',
  source_language: 'da',
  target_language: 'ar',
  transcript: 'Hvornår tog du sidst din medicin?',
  translation: 'متى تناولت دواءك آخر مرة؟',
  audio_base64: null,
  audio_mime_type: 'audio/mpeg',
}

let store: ReturnType<typeof useInterpretStore>

async function mountPage(): Promise<VueWrapper> {
  setActivePinia(createPinia())
  store = useInterpretStore()
  store.start = vi.fn(async (language: Language) => {
    store.conversation = conversation(language)
    return store.conversation
  })
  store.takeTurn = vi.fn(async () => {
    store.turns.push(STAFF_TURN)
    return STAFF_TURN
  })
  store.end = vi.fn(async () => {
    store.conversation = null
    store.turns = []
  })
  const wrapper = mount(Interpret, { global: { plugins: [i18n] } })
  await flushPromises()
  return wrapper
}

function button(wrapper: VueWrapper, label: string) {
  const found = wrapper.findAll('button').find((b) => b.text().includes(label))
  expect(found, `button "${label}"`).toBeDefined()
  return found!
}

async function start(wrapper: VueWrapper, language: Language) {
  await button(wrapper, LANGUAGE_COPY[language].name).trigger('click')
  await flushPromises()
}

beforeEach(() => {
  i18n.global.locale.value = 'en'
  for (const mock of [confirm, toast, handleError]) mock.mockClear()
  for (const mock of Object.values(recorder)) if (vi.isMockFunction(mock)) mock.mockClear()
  recorder.open.mockImplementation(async () => {})
  recorder.stop.mockImplementation(() => recording)
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('interpret page', () => {
  test('starts a conversation in the chosen language after asking for the microphone', async () => {
    const wrapper = await mountPage()

    await start(wrapper, 'ar')

    expect(recorder.open).toHaveBeenCalled()
    expect(store.start).toHaveBeenCalledWith('ar')
    // One button per side, each labelled in its speaker's language.
    expect(button(wrapper, LANGUAGE_COPY.da.hold).attributes('lang')).toBe('da')
    expect(button(wrapper, LANGUAGE_COPY.ar.hold).attributes('dir')).toBe('rtl')
    expect(wrapper.text()).toContain(LANGUAGE_COPY.ar.notice)
  })

  test('a denied microphone explains what to do and starts nothing', async () => {
    recorder.open.mockImplementation(async () => {
      throw new DOMException('denied', 'NotAllowedError')
    })
    const wrapper = await mountPage()

    await start(wrapper, 'uk')

    expect(toast).toHaveBeenCalledWith(
      expect.objectContaining({ title: t('interpret.microphoneDenied') }),
    )
    expect(store.start).not.toHaveBeenCalled()
  })

  test('holding the staff button records a turn and shows its translation', async () => {
    const wrapper = await mountPage()
    await start(wrapper, 'ar')

    const talk = button(wrapper, LANGUAGE_COPY.da.hold)
    await talk.trigger('pointerdown')
    await flushPromises()
    expect(recorder.start).toHaveBeenCalled()
    expect(talk.text()).toContain(LANGUAGE_COPY.da.listening)

    await talk.trigger('pointerup')
    await flushPromises()

    expect(store.takeTurn).toHaveBeenCalledWith('staff', recording)
    expect(wrapper.text()).toContain(STAFF_TURN.translation)
    expect(wrapper.text()).toContain(STAFF_TURN.transcript)
  })

  test('the citizen button sends a citizen turn', async () => {
    const wrapper = await mountPage()
    await start(wrapper, 'ar')

    const talk = button(wrapper, LANGUAGE_COPY.ar.hold)
    await talk.trigger('pointerdown')
    await flushPromises()
    await talk.trigger('pointerup')
    await flushPromises()

    expect(store.takeTurn).toHaveBeenCalledWith('citizen', recording)
  })

  test('a failed turn is reported', async () => {
    const wrapper = await mountPage()
    await start(wrapper, 'ar')
    const failure = new Error('nothing heard')
    store.takeTurn = vi.fn(async () => {
      throw failure
    })

    const talk = button(wrapper, LANGUAGE_COPY.da.hold)
    await talk.trigger('pointerdown')
    await flushPromises()
    await talk.trigger('pointerup')
    await flushPromises()

    expect(handleError).toHaveBeenCalledWith(failure)
  })

  test('ending the conversation asks first, then clears it', async () => {
    const wrapper = await mountPage()
    await start(wrapper, 'ar')

    await button(wrapper, t('interpret.end')).trigger('click')
    await flushPromises()

    expect(confirm).toHaveBeenCalled()
    expect(recorder.close).toHaveBeenCalled()
    expect(store.end).toHaveBeenCalled()
    expect(wrapper.text()).toContain(t('interpret.chooseLanguage'))
  })
})
