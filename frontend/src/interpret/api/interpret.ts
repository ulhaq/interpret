import { api } from '@/foundation/api/client'
import type { ConversationIn, Speaker } from '@/interpret/types/interpret'

type ListParams = Record<string, string | number | undefined>

export const interpretApi = {
  list(params: ListParams = {}) {
    return api.get('/interpret/conversations', { query: params })
  },

  start(data: ConversationIn) {
    return api.post('/interpret/conversations', { body: data })
  },

  turn(conversationId: number, speaker: Speaker, audio: Blob) {
    return api.post('/interpret/conversations/{conversation_id}/turns', {
      path: { conversation_id: conversationId },
      multipart: { speaker, audio },
    })
  },

  end(conversationId: number) {
    return api.post('/interpret/conversations/{conversation_id}/end', {
      path: { conversation_id: conversationId },
    })
  },
}
