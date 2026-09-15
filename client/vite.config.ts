/// <reference types="vitest/config" />
import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';
import vuetify from 'vite-plugin-vuetify';

export default defineConfig({
  plugins: [vue(), vuetify({ autoImport: true })],
  // Le front n'avait aucun test pour onze mille lignes. Ceux-ci portent sur ce
  // qui **décide** quelque chose — l'aller-retour entre une adresse et un
  // formulaire, un sondage qui doit se taire, les libellés que le serveur et le
  // client calculent chacun de leur côté — et pas sur du rendu de gabarit.
  test: {
    // `happy-dom` plutôt que `jsdom` : on a besoin de `document.hidden`, d'un
    // écouteur d'événements et de rien d'autre.
    environment: 'happy-dom',
    include: ['src/**/*.test.ts'],
  },
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:3000',
      '/uploads': 'http://localhost:3000',
    },
  },
});
