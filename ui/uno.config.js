import { defineConfig, presetUno, presetIcons } from 'unocss'

export default defineConfig({
  // preflights: [],
  presets: [
    presetUno({ preflight: false }),
    presetIcons({
      scale: 1,
      extraProperties: { display: 'inline-block', 'vertical-align': 'middle' },
    }),
  ],
  theme: {
    colors: {
      accent:   '#D4A853',
      canvas:   '#09090B',
      surface1: '#0F0F12',
      surface2: '#16161A',
      surface3: '#1C1C21',
      text1:    '#FAFAFA',
      text2:    '#A1A1AA',
      text3:    '#71717A',
      positive: '#22C55E',
      negative: '#EF4444',
    },
    fontFamily: {
      sans:  'var(--sans)',
      serif: 'var(--serif)',
      mono:  'var(--mono)',
    },
    breakpoints: {
      sm:  '600px',
      md:  '768px',
      lg:  '1024px',
      xl:  '1280px',
    },
  },
  // Ensure dynamic icon classes are generated
  safelist: [
    'i-lucide-file-text',
    'i-lucide-link',
    'i-lucide-bot',
    'i-lucide-lock',
    'i-lucide-wallet',
    'i-lucide-circle-dollar-sign',
    'i-lucide-scroll-text',
    'i-lucide-arrow-left-right',
    'i-lucide-zap',
    'i-lucide-layers',
    'i-lucide-check',
    'i-lucide-trophy',
    'i-lucide-users',
  ],
})
