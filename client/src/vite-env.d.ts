/// <reference types="vite/client" />

/**
 * Les réglages passés au **build**, que Vite remplace dans le code compilé.
 *
 * Déclarés ici plutôt que lus au jugé : sans ce typage, `import.meta.env.VITE_X`
 * vaut `any` et une faute de frappe passe la compilation pour donner
 * `undefined` en production.
 */
interface ImportMetaEnv {
  /** Le géocodeur du formulaire : « photon » (défaut) ou « ban ». */
  readonly VITE_GEOCODER?: 'photon' | 'ban';
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

declare module '*.vue' {
  import type { DefineComponent } from 'vue';
  const component: DefineComponent<Record<string, never>, Record<string, never>, unknown>;
  export default component;
}
