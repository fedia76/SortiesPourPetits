/**
 * Ce qu'ESLint surveille sur l'API, et surtout ce qu'il ne surveille pas.
 *
 * Il n'y avait aucun linter, ni ici ni ailleurs. La tentation, en en posant un,
 * est de tout allumer : on obtient alors mille avertissements de mise en forme
 * qu'on éteint un par un, et le premier vrai défaut se perd au milieu.
 *
 * Les règles retenues visent donc ce que la compilation ne voit pas et qu'une
 * relecture rate :
 *
 * * **`no-floating-promises`** — la règle qui justifie à elle seule le typage.
 *   Un `await` oublié dans un gestionnaire Express ne casse rien à la
 *   compilation : la route répond avant d'avoir fait son travail, et l'erreur
 *   arrive dans le vide. C'est de la même famille que ce qui a motivé
 *   `lib/asyncRoutes`, qui a éteint le site public une fois déjà.
 * * **`no-misused-promises`** — passer une fonction `async` là où une fonction
 *   synchrone est attendue, ce qui est le cas de beaucoup de rappels d'Express.
 * * **`require-await`**, **`await-thenable`** — un `async` qui n'attend rien,
 *   ou un `await` sur ce qui n'est pas une promesse : dans les deux cas
 *   quelqu'un a cru attendre quelque chose.
 * * les variables et les imports morts, qui s'accumulent en silence.
 *
 * Le reste — guillemets, points-virgules, largeur — est laissé de côté : il ne
 * décide de rien, et l'imposer d'un coup noierait le prochain diff utile.
 */
import js from '@eslint/js';
import tseslint from 'typescript-eslint';

export default tseslint.config(
  {
    ignores: ['dist/**', 'node_modules/**', 'src/generated/**'],
  },
  js.configs.recommended,
  ...tseslint.configs.recommendedTypeChecked,
  {
    // Ce fichier-ci n'appartient à aucun projet TypeScript : les règles qui
    // réclament le typage n'ont rien à lire dessus et refuseraient de démarrer.
    files: ['**/*.mjs', '**/*.js'],
    extends: [tseslint.configs.disableTypeChecked],
  },
  {
    // Le typage ne vaut que pour les fichiers d'un projet TypeScript : la
    // configuration elle-même est un module JavaScript et n'en fait pas partie.
    files: ['**/*.ts'],
    languageOptions: {
      parserOptions: {
        // Les deux projets : `tsconfig.json` ne connaît que `src`, pour que
        // `dist` ne reçoive jamais de test. Sans le second, ESLint refuserait
        // d'analyser `tests/` et `scripts/`.
        project: ['./tsconfig.json', './tsconfig.test.json'],
        tsconfigRootDir: import.meta.dirname,
      },
    },
    rules: {
      // ── ce que le typage seul ne dit pas
      '@typescript-eslint/no-floating-promises': 'error',
      // `checksVoidReturn.arguments` désactivé, et c'est le seul assouplissement
      // qui demande une explication. La règle dit qu'on ne passe pas une
      // fonction `async` là où une fonction synchrone est attendue — ce qui est
      // le cas de **tous** les gestionnaires d'Express 4, dont les types
      // déclarent un retour `void`. C'est précisément le problème que
      // `lib/asyncRoutes` règle, une fois, à l'endroit où les routes se
      // déclarent : le rejet d'un gestionnaire y rejoint `next(err)`. La règle
      // ne sait pas voir à travers cet enrobage, et laissée telle quelle elle
      // criait cent quinze fois sur du code correct. Le reste — une promesse
      // dans un `if`, dans un spread — continue d'être vérifié.
      '@typescript-eslint/no-misused-promises': [
        'error',
        { checksVoidReturn: { arguments: false, attributes: false } },
      ],
      '@typescript-eslint/await-thenable': 'error',
      '@typescript-eslint/require-await': 'error',

      // ── ce qui s'accumule sans se voir
      '@typescript-eslint/no-unused-vars': [
        'error',
        // `_` en tête vaut « je sais, et c'est voulu » : une signature
        // d'Express impose souvent des paramètres qu'on n'utilise pas.
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_', caughtErrors: 'none' },
      ],

      // ── ce qui est vrai de ce dépôt-ci
      //
      // `any` est déjà proscrit par le `strict` de TypeScript là où il
      // compterait ; le laisser en erreur ici ne ferait que doubler le message.
      '@typescript-eslint/no-explicit-any': 'off',
      // Le serveur journalise volontairement dans la sortie du service : c'est
      // ce que `journalctl` relit après un incident.
      'no-console': 'off',
      // Les gabarits sont pleins de nombres mis en forme ; `${n}` y est la
      // façon la plus lisible d'écrire, pas un oubli de conversion.
      '@typescript-eslint/restrict-template-expressions': 'off',
    },
  },
  {
    // Les scripts d'exploitation tournent à la main, et se terminent par une
    // erreur visible plutôt que par une gestion d'erreur.
    files: ['scripts/**/*.ts', 'prisma/**/*.ts'],
    rules: { '@typescript-eslint/no-floating-promises': 'off' },
  },
  {
    // `test()` de `node:test` rend une promesse dont le lanceur est
    // propriétaire : c'est lui qui attend la fin de chaque cas et qui compte
    // les échecs. L'attendre soi-même ne dirait rien de plus, et l'exiger
    // ferait crier la règle sur chaque test du dépôt.
    files: ['tests/**/*.ts'],
    rules: {
      '@typescript-eslint/no-floating-promises': 'off',
      // Une doublure satisfait une signature `async` — c'est ce qu'on lui
      // demande — sans avoir rien à attendre.
      '@typescript-eslint/require-await': 'off',
    },
  },
);
