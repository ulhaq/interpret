import type { Language } from '@/interpret/types/interpret'

/** Plan setting key the product enforces (mirrors `InterpretUsageMetric`). */
export const InterpretUsageMetric = {
  TURNS: 'interpret_turns',
} as const

/** Languages a citizen can speak; staff speak Danish. */
export const CITIZEN_LANGUAGES: Language[] = ['en', 'ar', 'uk']

/**
 * What each side of the conversation reads, in that side's own language -
 * whatever the app's UI language is. Kept out of the i18n messages, which
 * hold only the app's UI languages.
 */
export const LANGUAGE_COPY: Record<
  Language,
  { name: string; dir: 'ltr' | 'rtl'; hold: string; listening: string; notice: string }
> = {
  da: {
    name: 'Dansk',
    dir: 'ltr',
    hold: 'Hold for at tale',
    listening: 'Lytter…',
    notice: 'Dette er maskinoversættelse. Bed om en tolk, hvis noget er uklart.',
  },
  en: {
    name: 'English',
    dir: 'ltr',
    hold: 'Hold to speak',
    listening: 'Listening…',
    notice: 'This is machine translation. Ask for an interpreter if anything is unclear.',
  },
  ar: {
    name: 'العربية',
    dir: 'rtl',
    hold: 'اضغط مع الاستمرار للتحدث',
    listening: 'جارٍ الاستماع…',
    notice: 'هذه ترجمة آلية. اطلب مترجمًا فوريًا إذا كان هناك شيء غير واضح.',
  },
  uk: {
    name: 'Українська',
    dir: 'ltr',
    hold: 'Утримуйте, щоб говорити',
    listening: 'Слухаю…',
    notice: 'Це машинний переклад. Попросіть перекладача, якщо щось незрозуміло.',
  },
}
