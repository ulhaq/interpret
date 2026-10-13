import { defineStore } from 'pinia'
import { ref } from 'vue'
import { interpretApi } from '@/interpret/api/interpret'
import type { PaginatedResponse } from '@/foundation/types'
import type { ConversationOut, Language, Speaker, TurnOut } from '@/interpret/types/interpret'

type ListParams = Record<string, string | number | undefined>

// Gateway store for interpreted conversations. The open conversation's turns
// live only here, in memory: the backend never stores what was said, and
// ending the conversation forgets them.
export const useInterpretStore = defineStore('interpret', () => {
  const conversation = ref<ConversationOut | null>(null)
  const turns = ref<TurnOut[]>([])

  async function list(params: ListParams = {}): Promise<PaginatedResponse<ConversationOut>> {
    const { data } = await interpretApi.list({ ...params, sort: params.sort ?? '-created_at' })
    return data
  }

  async function start(citizenLanguage: Language): Promise<ConversationOut> {
    const { data } = await interpretApi.start({
      staff_language: 'da',
      citizen_language: citizenLanguage,
    })
    conversation.value = data
    turns.value = []
    return data
  }

  async function takeTurn(speaker: Speaker, audio: Blob): Promise<TurnOut> {
    if (!conversation.value) throw new Error('No conversation in progress')
    const { data } = await interpretApi.turn(conversation.value.id, speaker, audio)
    turns.value.push(data)
    return data
  }

  async function end(): Promise<void> {
    const current = conversation.value
    conversation.value = null
    turns.value = []
    if (current) await interpretApi.end(current.id)
  }

  return { conversation, turns, list, start, takeTurn, end }
})
