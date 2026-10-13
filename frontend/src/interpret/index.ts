/**
 * Interpret product module entry - the manifest of everything the foundation
 * shell needs to know about the product. Listed in `src/products.ts`.
 */
import { History, Languages } from '@lucide/vue'
import da from '@/interpret/locales/da'
import en from '@/interpret/locales/en'
import { registerNavItems } from '@/foundation/navigation'
import type { Module } from '@/foundation/module'

const interpret: Module = {
  name: 'interpret',
  messages: { da, en },
  homeRoute: '/interpret',
  setup() {
    registerNavItems('main', [
      {
        to: '/interpret',
        labelKey: 'nav.interpret',
        icon: Languages,
        order: 10,
      },
      {
        to: '/interpret/history',
        labelKey: 'nav.interpretHistory',
        icon: History,
        order: 20,
      },
    ])
  },
}

export default interpret
