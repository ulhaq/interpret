import { onBeforeUnmount, ref } from 'vue'

/** What the backend accepts: 16 kHz, 16-bit mono PCM WAV. */
export const SAMPLE_RATE = 16_000

/**
 * Records the microphone as 16 kHz mono WAV, which every browser can produce
 * (MediaRecorder's formats differ per browser and need server-side
 * conversion). `open()` asks for the microphone once, so the first press
 * doesn't lose its first words to the permission prompt; `start()`/`stop()`
 * record one turn.
 */
export function useWavRecorder() {
  const isOpen = ref(false)
  const isRecording = ref(false)

  let stream: MediaStream | null = null
  let context: AudioContext | null = null
  let source: MediaStreamAudioSourceNode | null = null
  let processor: ScriptProcessorNode | null = null
  let chunks: Float32Array[] = []

  async function open(): Promise<void> {
    if (isOpen.value) return
    stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
    })
    context = new AudioContext()
    source = context.createMediaStreamSource(stream)
    // ScriptProcessorNode is deprecated but works everywhere without a
    // separate worklet file; one turn is short, so its main-thread cost is fine.
    processor = context.createScriptProcessor(4096, 1, 1)
    processor.onaudioprocess = (event) => {
      if (isRecording.value) chunks.push(new Float32Array(event.inputBuffer.getChannelData(0)))
    }
    source.connect(processor)
    processor.connect(context.destination)
    isOpen.value = true
  }

  async function start(): Promise<void> {
    await open()
    await context?.resume()
    chunks = []
    isRecording.value = true
  }

  /** The recording since `start()`, as WAV; null if nothing was recorded. */
  function stop(): Blob | null {
    if (!isRecording.value || !context) return null
    isRecording.value = false
    const samples = downsample(concat(chunks), context.sampleRate, SAMPLE_RATE)
    chunks = []
    return samples.length ? encodeWav(samples, SAMPLE_RATE) : null
  }

  function close(): void {
    isRecording.value = false
    processor?.disconnect()
    source?.disconnect()
    stream?.getTracks().forEach((track) => track.stop())
    void context?.close()
    stream = context = source = processor = null
    isOpen.value = false
  }

  onBeforeUnmount(close)

  return { isOpen, isRecording, open, start, stop, close }
}

function concat(chunks: Float32Array[]): Float32Array {
  const out = new Float32Array(chunks.reduce((n, c) => n + c.length, 0))
  let offset = 0
  for (const chunk of chunks) {
    out.set(chunk, offset)
    offset += chunk.length
  }
  return out
}

/** Averages each output sample's input window: a simple low-pass + decimate. */
export function downsample(input: Float32Array, from: number, to: number): Float32Array {
  if (from === to) return input
  const ratio = from / to
  const out = new Float32Array(Math.floor(input.length / ratio))
  for (let i = 0; i < out.length; i++) {
    const start = Math.floor(i * ratio)
    const end = Math.min(Math.floor((i + 1) * ratio), input.length)
    let sum = 0
    for (let j = start; j < end; j++) sum += input[j]!
    out[i] = sum / Math.max(end - start, 1)
  }
  return out
}

export function encodeWav(samples: Float32Array, sampleRate: number): Blob {
  const buffer = new ArrayBuffer(44 + samples.length * 2)
  const view = new DataView(buffer)
  const text = (offset: number, value: string) => {
    for (let i = 0; i < value.length; i++) view.setUint8(offset + i, value.charCodeAt(i))
  }
  text(0, 'RIFF')
  view.setUint32(4, 36 + samples.length * 2, true)
  text(8, 'WAVE')
  text(12, 'fmt ')
  view.setUint32(16, 16, true) // fmt chunk size
  view.setUint16(20, 1, true) // PCM
  view.setUint16(22, 1, true) // mono
  view.setUint32(24, sampleRate, true)
  view.setUint32(28, sampleRate * 2, true) // byte rate
  view.setUint16(32, 2, true) // block align
  view.setUint16(34, 16, true) // bits per sample
  text(36, 'data')
  view.setUint32(40, samples.length * 2, true)
  samples.forEach((sample, i) => {
    const s = Math.max(-1, Math.min(1, sample))
    view.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true)
  })
  return new Blob([buffer], { type: 'audio/wav' })
}
