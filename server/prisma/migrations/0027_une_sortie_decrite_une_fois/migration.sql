-- Une sortie est décrite une fois, et les liens d'agenda y mènent.
--
-- ## Ce qui n'allait pas
--
-- Il existait deux descriptions de la même sortie, dans deux tables, que rien
-- ne joignait :
--
--   * `EvalReading` — l'URL, le texte attendu, l'image attendue, les dates
--     JSON-LD. L'objet des étages 5 et 6, correct et complet ;
--   * `EvalLink.dateHint / placeHint / audience` — la date, le lieu et le
--     public, ajoutés pour l'étage 4. Les mêmes faits, en plus pauvre, sur un
--     autre objet, avec la même URL et aucune clé étrangère entre les deux.
--
-- On ne pouvait donc pas répondre à « qu'est-ce que cette sortie ? » : il
-- fallait savoir laquelle des deux tables interroger, et laquelle croire.
--
-- ## Le modèle
--
-- Deux objets, et deux seulement, pour les étages 3 à 6 :
--
--   * un **agenda**, dont chaque lien est étiqueté « sortie / page suivante /
--     autre agenda / autre chose ». C'est la question de l'étage 3 ;
--   * une **sortie**, décrite une fois avec l'union de ce dont les étages 4, 5
--     et 6 ont besoin. Chaque étage y lit son sous-ensemble : l'étage 4 la
--     date, le lieu et l'âge — et rien d'autre, pas même le tarif, qui est
--     pourtant sur l'étiquette.
--
-- Un lien étiqueté « sortie » **pointe** vers une sortie au lieu de la
-- redécrire.
--
-- ## Pourquoi des colonnes et non `EvalFiche.expected`
--
-- `EvalFiche` porte déjà « du 2026-09-20 au 2026-09-22 », « dès 3 ans »,
-- « 12 rue X, 75012, Paris ». Mais ce sont des chaînes faites pour être
-- comparées à ce que le modèle a rendu, et leur mise en forme est décidée en
-- Python (`evaluation.audit_fiche`). Les relire pour l'étage 4 demanderait
-- d'écrire en TypeScript un analyseur du format d'un autre langage : deux
-- implémentations d'une seule convention, qui divergeraient en silence au
-- premier changement de rendu.
--
-- Une date se compare à une fenêtre, un code postal à des préfixes. Il faut
-- donc les faits, pas leur mise en forme. C'est aussi ce qui rend gratuite la
-- moisson depuis la modération : `Event` et `Venue` portent déjà ces colonnes,
-- structurées et vérifiées par un humain.

-- ── 1. la table dit enfin ce qu'elle contient ────────────────────────────
RENAME TABLE `EvalReading` TO `EvalSortie`;

-- `CHANGE COLUMN` plutôt que `RENAME COLUMN` : la seconde demande MariaDB
-- 10.5, et la version du serveur n'est pas une chose qu'une migration doit
-- supposer.
ALTER TABLE `EvalFiche`         CHANGE COLUMN `readingId` `sortieId` INT NOT NULL;
ALTER TABLE `EvalReadResult`    CHANGE COLUMN `readingId` `sortieId` INT NOT NULL;
ALTER TABLE `EvalExtractResult` CHANGE COLUMN `readingId` `sortieId` INT NOT NULL;

-- ── 2. ce que l'étage 4 juge, en faits ───────────────────────────────────
ALTER TABLE `EvalSortie`
  ADD COLUMN `dateStart`  DATE        NULL,
  ADD COLUMN `dateEnd`    DATE        NULL,
  ADD COLUMN `postalCode` VARCHAR(10) NULL,
  ADD COLUMN `ageMin`     INT         NULL,
  ADD COLUMN `ageMax`     INT         NULL,
  ADD COLUMN `audience`   ENUM('ENFANTS', 'ADULTES', 'INDETERMINE') NULL;

-- ── 3. le lien mène à la sortie ──────────────────────────────────────────
ALTER TABLE `EvalLink` ADD COLUMN `sortieId` INT NULL;
CREATE INDEX `EvalLink_sortieId_idx` ON `EvalLink`(`sortieId`);
ALTER TABLE `EvalLink`
  ADD CONSTRAINT `EvalLink_sortieId_fkey`
  FOREIGN KEY (`sortieId`) REFERENCES `EvalSortie`(`id`) ON DELETE SET NULL;

-- ── 4. verser les indices dans les sorties, sans en perdre un ────────────
--
-- D'abord créer la sortie manquante pour tout lien qui portait un indice et
-- dont l'URL n'était pas encore au corpus. `origin` reste `MANUEL` : ces
-- indices ont bien été saisis à la main dans la console.
--
-- `note` et `runReason` sont des colonnes `TEXT` : MySQL leur refuse une
-- valeur par défaut, et le `@default("")` de Prisma n'existe donc que dans le
-- client. Les omettre ferait échouer l'insertion — elles sont listées.
INSERT INTO `EvalSortie` (`url`, `label`, `note`, `runReason`, `origin`, `createdById`, `createdAt`)
SELECT
  l.`url`,
  MAX(l.`text`),
  'Créée en versant les indices posés sur un lien d''agenda.',
  '',
  'MANUEL',
  -- L'auteur de l'étiquette d'origine, ou le plus ancien administrateur : une
  -- sortie sans auteur ne passerait pas la contrainte, et inventer un compte
  -- serait pire que d'attribuer au doyen.
  COALESCE(MAX(l.`labelledById`), (SELECT MIN(`id`) FROM `User` WHERE `role` = 'ADMIN')),
  NOW(3)
FROM `EvalLink` l
WHERE (l.`dateHint` IS NOT NULL OR l.`placeHint` IS NOT NULL OR l.`audience` IS NOT NULL)
  AND NOT EXISTS (SELECT 1 FROM `EvalSortie` s WHERE s.`url` = l.`url`)
GROUP BY l.`url`;

-- Puis relier **tout** lien « sortie » dont l'URL est au corpus, indices ou
-- non : la jointure valait déjà, elle n'était simplement écrite nulle part.
UPDATE `EvalLink` l
  JOIN `EvalSortie` s ON s.`url` = l.`url`
SET l.`sortieId` = s.`id`
WHERE l.`verdict` = 'SORTIE';

-- Enfin verser les faits. Le code postal n'est repris que s'il en est un :
-- `placeHint` acceptait « Vincennes », qui ne se compare à aucun préfixe.
UPDATE `EvalSortie` s
  JOIN `EvalLink` l ON l.`sortieId` = s.`id`
SET
  s.`dateStart`  = COALESCE(s.`dateStart`, CASE
                     WHEN l.`dateHint` REGEXP '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
                     THEN CAST(l.`dateHint` AS DATE) END),
  s.`postalCode` = COALESCE(s.`postalCode`, CASE
                     WHEN l.`placeHint` REGEXP '^[0-9]{5}$'
                     THEN l.`placeHint` END),
  s.`audience`   = COALESCE(s.`audience`, l.`audience`);

-- ── 5. les colonnes en double s'en vont ──────────────────────────────────
ALTER TABLE `EvalLink`
  DROP COLUMN `dateHint`,
  DROP COLUMN `placeHint`,
  DROP COLUMN `audience`;

-- ── 6. les sorties déjà moissonnées récupèrent leurs faits ───────────────
--
-- La moisson depuis la modération existait déjà : elle créait la sortie et sa
-- provenance, mais pas la date, le lieu ni l'âge — l'étage 4 n'avait alors
-- rien à quoi comparer. Ces faits sont pourtant là, structurés et vérifiés par
-- un modérateur, dans `Event` et `Venue`. Les recopier ici rend décidable, du
-- jour au lendemain, tout le corpus déjà moissonné.
UPDATE `EvalSortie` s
  JOIN `Event` e ON e.`id` = s.`eventId`
  LEFT JOIN `Venue` v ON v.`id` = e.`venueId`
SET
  s.`dateStart`  = COALESCE(s.`dateStart`, e.`dateStart`),
  s.`dateEnd`    = COALESCE(s.`dateEnd`, e.`dateEnd`),
  s.`ageMin`     = COALESCE(s.`ageMin`, e.`ageMin`),
  s.`ageMax`     = COALESCE(s.`ageMax`, e.`ageMax`),
  s.`postalCode` = COALESCE(s.`postalCode`, NULLIF(v.`postalCode`, '')),
  -- Une sortie approuvée sur un site de sorties avec des enfants **est** pour
  -- les enfants : c'est la ligne éditoriale, et un modérateur l'a vérifiée
  -- fiche en main. Ce n'est donc pas une supposition de la machine. Les deux
  -- autres paniers — abandonnées, illisibles — n'ont jamais été approuvés :
  -- on ne sait rien de leur public, et on ne prétend rien.
  s.`audience`   = COALESCE(s.`audience`, CASE WHEN s.`origin` = 'APPROUVEE' THEN 'ENFANTS' END);
