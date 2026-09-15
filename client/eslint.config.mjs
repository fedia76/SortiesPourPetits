/**
 * Ce qu'ESLint surveille sur le front.
 *
 * Même parti pris que pour l'API : les règles qui attrapent un défaut, pas
 * celles qui mettent en forme. Un `vue3-recommended` complet produirait des
 * centaines d'avertissements de style sur onze mille lignes de gabarits, qu'on
 * éteindrait en bloc — et la règle utile serait éteinte avec.
 *
 * `vue3-essential` ne contient que ce qui casse vraiment : une clé `v-for`
 * manquante, un `v-if` et un `v-for` sur le même nœud, une propriété mutée
 * depuis l'enfant.
 */
import js from '@eslint/js';
import tseslint from 'typescript-eslint';
import pluginVue from 'eslint-plugin-vue';

export default tseslint.config(
  { ignores: ['dist/**', 'node_modules/**'] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  ...pluginVue.configs['flat/essential'],
  {
    files: ['**/*.vue'],
    languageOptions: {
      parserOptions: { parser: tseslint.parser },
    },
  },
  {
    rules: {
      // TypeScript sait déjà si un identifiant existe, et il connaît les
      // globales du navigateur — `setInterval`, `URL`, `navigator`. ESLint,
      // lui, ne les connaît qu'en les déclarant : la règle ne ferait donc que
      // répéter le compilateur, en moins bien.
      'no-undef': 'off',
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_', caughtErrors: 'none' },
      ],
      '@typescript-eslint/no-explicit-any': 'off',
      // Un composant d'une seule page n'a pas à porter un nom composé : le
      // routeur ne les instancie pas comme des balises.
      'vue/multi-word-component-names': 'off',
    },
  },
);
