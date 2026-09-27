import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['icon-192.png', 'icon-512.png'],
      manifest: {
        name: 'Control Horario',
        short_name: 'Horario',
        description: 'Registro de jornada, horas extra y banco de horas con asistente por voz',
        lang: 'es-AR',
        theme_color: '#1F5C52',
        background_color: '#F6F4EF',
        display: 'standalone',
        start_url: '/',
        icons: [
          { src: 'icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: 'icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'any maskable' },
        ],
      },
      workbox: { navigateFallbackDenylist: [/^\/api\//], globPatterns: ['**/*.{js,css,html,png,svg,webp,woff2}'] },
    }),
  ],
  css: {
    preprocessorOptions: {
      // Bootstrap 5.3 todavía usa @import de Sass: silenciamos sus avisos de obsolescencia.
      scss: { quietDeps: true, silenceDeprecations: ['import', 'global-builtin', 'color-functions', 'mixed-decls', 'if-function'] },
    },
  },
  server: { proxy: { '/api': 'http://localhost:8000' } },
})
