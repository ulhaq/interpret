import { describe, expect, test } from 'vitest'
import { SAMPLE_RATE, downsample, encodeWav } from '@/interpret/composables/useWavRecorder'

async function bytes(blob: Blob): Promise<DataView> {
  return new DataView(await blob.arrayBuffer())
}

function text(view: DataView, offset: number, length: number): string {
  return String.fromCharCode(...Array.from({ length }, (_, i) => view.getUint8(offset + i)))
}

describe('encodeWav', () => {
  test('writes a 16 kHz, 16-bit mono PCM WAV the backend accepts', async () => {
    const view = await bytes(encodeWav(new Float32Array([0, 1, -1, 0.5]), SAMPLE_RATE))

    expect(text(view, 0, 4)).toBe('RIFF')
    expect(text(view, 8, 4)).toBe('WAVE')
    expect(view.getUint16(20, true)).toBe(1) // PCM
    expect(view.getUint16(22, true)).toBe(1) // mono
    expect(view.getUint32(24, true)).toBe(16_000)
    expect(view.getUint16(34, true)).toBe(16) // bits per sample
    expect(view.getUint32(40, true)).toBe(8) // 4 samples x 2 bytes
    expect(view.byteLength).toBe(44 + 8)
    expect(view.getInt16(46, true)).toBe(0x7fff)
    expect(view.getInt16(48, true)).toBe(-0x8000)
  })

  test('clips samples outside -1..1', async () => {
    const view = await bytes(encodeWav(new Float32Array([3, -3]), SAMPLE_RATE))
    expect(view.getInt16(44, true)).toBe(0x7fff)
    expect(view.getInt16(46, true)).toBe(-0x8000)
  })
})

describe('downsample', () => {
  test('averages each window from 48 kHz to 16 kHz', () => {
    const out = downsample(new Float32Array([0, 0.3, 0.6, 1, 1, 1]), 48_000, 16_000)
    expect(Array.from(out).map((v) => Number(v.toFixed(2)))).toEqual([0.3, 1])
  })

  test('leaves audio at the target rate untouched', () => {
    const input = new Float32Array([0.1, 0.2])
    expect(downsample(input, 16_000, 16_000)).toBe(input)
  })
})
