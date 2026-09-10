-- Séparer le corpus, les runs et la mesure.
--
-- Trois choses vivaient dans les mêmes lignes, et ce mélange n'était pas une
-- gêne d'architecture : c'était un défaut de fonctionnement.
--
--   * rejouer un agenda faisait `DELETE FROM EvalAgendaPage`, donc en cascade
--     tous les verdicts humains qu'il portait. Mesurer détruisait la mesure ;
--   * rejouer une page de lecture réécrivait son texte et supprimait son HTML
--     gelé, en laissant les verdicts en place — des étiquettes qui décrivaient
--     un objet disparu, ce qui est pire que de les avoir perdues ;
--   * rien ne gardait d'historique : `analyzedAt` était écrasé.
--
-- Autrement dit, la question « est-ce que ça s'améliore ? » — la seule pour
-- laquelle un banc existe — était sans réponse possible.
--
-- Après : le corpus ne bouge plus, les runs s'empilent, la mesure se calcule.
--
-- ## Ce que cette migration préserve, et ce qu'elle ne peut pas préserver
--
-- Les étiquettes humaines sont ce qui coûte cher : toutes celles qui décrivent
-- la page sont reprises. Celles qui ne décrivaient que le verdict d'un passage
-- — « le texte était amputé », « le tarif était faux » — ne sont pas
-- convertibles : elles disaient que la brique s'était trompée sans jamais
-- enregistrer ce qu'il aurait fallu trouver. C'est exactement le défaut qu'on
-- corrige ici, et il se paie une fois.

-- ═══════════════════════════════════════════════ 1. les nouveaux vocabulaires

CREATE TABLE `_eval_tmp_noop` (`id` INTEGER NOT NULL, PRIMARY KEY (`id`));
DROP TABLE `_eval_tmp_noop`;

-- ═══════════════════════════════════════════ 2. le corpus des agendas (ét. 3)

-- La capture construit le corpus ; le run l'interroge. Deux verbes, deux états.
ALTER TABLE `EvalAgenda`
  ADD COLUMN `capture` ENUM('QUEUED','RUNNING','CAPTURED','FAILED') NOT NULL DEFAULT 'QUEUED',
  ADD COLUMN `captureError` TEXT NULL,
  ADD COLUMN `capturedAt` DATETIME(3) NULL;

-- Un agenda déjà analysé est un agenda déjà capturé : son HTML est sur disque.
UPDATE `EvalAgenda`
   SET `capture` = CASE WHEN `status` = 'FAILED' THEN 'FAILED'
                        WHEN `status` IN ('ANALYZED','VALIDATED') THEN 'CAPTURED'
                        ELSE 'QUEUED' END,
       `captureError` = `error`,
       `capturedAt` = `analyzedAt`;

ALTER TABLE `EvalAgenda`
  DROP COLUMN `status`,
  DROP COLUMN `error`,
  DROP COLUMN `analyzedAt`,
  DROP COLUMN `validatedAt`;

CREATE INDEX `EvalAgenda_capture_idx` ON `EvalAgenda`(`capture`);

-- ── la pagination : trois états au lieu d'un verdict ────────────────────
--
-- `null` : personne n'a regardé. `''` : il n'y a pas de suite, et c'est une
-- étiquette. Une URL : la voici. Le verdict d'autrefois se déduit désormais de
-- la comparaison avec ce qu'un run a trouvé, au lieu d'être figé contre un
-- seul passage.
ALTER TABLE `EvalAgendaPage` ADD COLUMN `nextExpectedNew` VARCHAR(500) NULL;

UPDATE `EvalAgendaPage`
   SET `nextExpectedNew` = CASE
     -- L'humain a dit « juste » : ce que la brique avait trouvé était la
     -- vérité, chaîne vide comprise — « il n'y a pas de suite ».
     WHEN `nextVerdict` = 'CORRECT' THEN `nextUrl`
     -- Il a dit « manquée » ou « fausse » et donné l'adresse : c'est elle.
     WHEN `nextVerdict` IN ('MANQUEE','FAUSSE') AND `nextExpected` <> '' THEN `nextExpected`
     -- Il a dit « manquée » sans donner l'adresse : on sait qu'il y a une
     -- suite, on ignore laquelle. Inexploitable comme étiquette.
     ELSE NULL
   END;

ALTER TABLE `EvalAgendaPage`
  DROP COLUMN `nextExpected`,
  DROP COLUMN `nextVerdict`,
  DROP COLUMN `nextUrl`,
  DROP COLUMN `error`,
  CHANGE COLUMN `nextExpectedNew` `nextExpected` VARCHAR(500) NULL;

-- ── les liens : on ne garde que ce qu'un humain a tranché ───────────────
--
-- Une ligne existe désormais **parce qu'**un humain l'a posée. C'est ce qui
-- remplace `reviewed`, et c'est mieux qu'une colonne : on ne peut plus valider
-- un agenda en n'ayant relu que la moisson — ce qui affichait un rappel de
-- 100 % pour la seule raison que personne n'avait regardé le reste.
DELETE FROM `EvalLink` WHERE `reviewed` = 0;

ALTER TABLE `EvalLink`
  ADD COLUMN `origin` ENUM('HUMAIN','MODERATION') NOT NULL DEFAULT 'HUMAIN',
  ADD COLUMN `labelledAt` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  ADD COLUMN `labelledById` INTEGER NULL;

UPDATE `EvalLink` SET `labelledAt` = COALESCE(`reviewedAt`, `addedAt`);

ALTER TABLE `EvalLink`
  DROP COLUMN `harvested`,
  DROP COLUMN `dropReason`,
  DROP COLUMN `context`,
  DROP COLUMN `position`,
  DROP COLUMN `reviewed`,
  DROP COLUMN `reviewedAt`,
  DROP COLUMN `addedAt`,
  MODIFY COLUMN `verdict` ENUM('SORTIE','PAGINATION','SOUS_AGENDA','AUTRE') NOT NULL;

ALTER TABLE `EvalLink`
  ADD CONSTRAINT `EvalLink_labelledById_fkey`
    FOREIGN KEY (`labelledById`) REFERENCES `User`(`id`) ON DELETE SET NULL ON UPDATE CASCADE;


-- ═══════════════════════════════════════════ 3. le corpus de lecture (ét. 5)

ALTER TABLE `EvalReading`
  ADD COLUMN `capture` ENUM('QUEUED','RUNNING','CAPTURED','FAILED') NOT NULL DEFAULT 'QUEUED',
  ADD COLUMN `captureError` TEXT NULL,
  ADD COLUMN `capturedAt` DATETIME(3) NULL,
  -- Les étiquettes : ce que la page contient, et non ce que la brique a rendu.
  -- Trois états chacune, comme la pagination ci-dessus.
  ADD COLUMN `expectedImage` VARCHAR(500) NULL,
  ADD COLUMN `expectedDates` TEXT NULL,
  ADD COLUMN `expectedMarkers` TEXT NULL;

UPDATE `EvalReading`
   SET `capture` = CASE WHEN `status` = 'FAILED' THEN 'FAILED'
                        WHEN `status` IN ('ANALYZED','VALIDATED') THEN 'CAPTURED'
                        ELSE 'QUEUED' END,
       `captureError` = `error`,
       `capturedAt` = `analyzedAt`,
       -- Seul « correcte » se convertit : il dit que ce que la brique avait
       -- trouvé était la vérité. « logo », « mauvaise » et « manquante »
       -- disaient qu'elle s'était trompée sans dire ce qu'il fallait trouver.
       `expectedImage` = CASE WHEN `imageVerdict` = 'CORRECTE' THEN `imageUrl` ELSE NULL END,
       `expectedDates` = CASE WHEN `datesVerdict` = 'CORRECTES' THEN `dates` ELSE NULL END;

ALTER TABLE `EvalReading`
  ADD COLUMN `originNew` ENUM('MANUEL','APPROUVEE','ABANDONNEE','ILLISIBLE') NOT NULL DEFAULT 'MANUEL';
UPDATE `EvalReading` SET `originNew` = `origin`;
ALTER TABLE `EvalReading`
  DROP COLUMN `origin`,
  CHANGE COLUMN `originNew` `origin` ENUM('MANUEL','APPROUVEE','ABANDONNEE','ILLISIBLE') NOT NULL DEFAULT 'MANUEL';

ALTER TABLE `EvalReading`
  DROP COLUMN `status`,
  DROP COLUMN `error`,
  DROP COLUMN `analyzedAt`,
  DROP COLUMN `validatedAt`,
  DROP COLUMN `readUrl`,
  DROP COLUMN `swapped`,
  DROP COLUMN `text`,
  DROP COLUMN `textChars`,
  DROP COLUMN `dates`,
  DROP COLUMN `imageUrl`,
  DROP COLUMN `heading`,
  DROP COLUMN `h1InText`,
  DROP COLUMN `truncated`,
  DROP COLUMN `tooShort`,
  DROP COLUMN `imageLooksLogo`,
  DROP COLUMN `textVerdict`,
  DROP COLUMN `imageVerdict`,
  DROP COLUMN `datesVerdict`;

CREATE INDEX `EvalReading_capture_idx` ON `EvalReading`(`capture`);
CREATE INDEX `EvalReading_origin_idx` ON `EvalReading`(`origin`);

-- ═══════════════════════════════════════ 4. le corpus d'extraction (ét. 6)
--
-- Le changement de nature est ici. L'étiquette n'est plus « le tarif rendu est
-- JUSTE » — un jugement qui n'a de sens que face à une fiche donnée, et qui
-- périme au premier changement de prompt — mais « la page annonce 8 € », qui
-- décrit la page et vaut pour toujours. Les quatre verdicts se dérivent alors
-- tout seuls, pour n'importe quel run.
--
-- La conversion ne peut porter que sur les aspects jugés JUSTE : eux seuls
-- disent que la valeur rendue était celle de la page, donc eux seuls livrent
-- la valeur attendue. Les FAUX, INVENTE et MANQUE sont perdus comme
-- étiquettes — ils n'ont jamais enregistré la bonne réponse.
CREATE TABLE `EvalFiche` (
  `id`          INTEGER     NOT NULL AUTO_INCREMENT,
  `expected`    TEXT        NOT NULL,
  `note`        TEXT        NOT NULL,
  `labelledAt`  DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `readingId`   INTEGER     NOT NULL,
  `createdById` INTEGER     NOT NULL,

  PRIMARY KEY (`id`),
  UNIQUE INDEX `EvalFiche_readingId_key` (`readingId`),
  CONSTRAINT `EvalFiche_readingId_fkey`
    FOREIGN KEY (`readingId`) REFERENCES `EvalReading`(`id`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `EvalFiche_createdById_fkey`
    FOREIGN KEY (`createdById`) REFERENCES `User`(`id`) ON DELETE RESTRICT ON UPDATE CASCADE
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- L'ancienne table est **conservée**, renommée, et c'est délibéré : elle porte
-- les seules étiquettes convertibles (les aspects jugés JUSTE, dont la valeur
-- rendue *était* celle de la page). Les extraire demande de parcourir un
-- tableau JSON en le croisant avec un objet JSON — faisable en SQL, illisible,
-- et déjà faux deux fois. C'est donc `npm run db:backfill-eval` qui le fait,
-- en trente lignes qu'on peut relire.
--
-- Elle pourra être supprimée par une migration ultérieure, une fois la
-- conversion passée en production et vérifiée. Garder une table morte quelques
-- semaines coûte moins qu'un étiquetage humain perdu.
RENAME TABLE `EvalExtraction` TO `_LegacyEvalExtraction`;

-- ══════════════════════════════════════════════════════════ 5. les runs

CREATE TABLE `EvalRun` (
  `id`     INTEGER NOT NULL AUTO_INCREMENT,
  `stage`  ENUM('HARVEST','SELECT','READ','EXTRACT') NOT NULL,
  `status` ENUM('QUEUED','RUNNING','DONE','FAILED') NOT NULL DEFAULT 'QUEUED',
  `error`  TEXT NULL,
  `label`  VARCHAR(150) NOT NULL DEFAULT '',

  -- De quoi ce run est-il le run. Sans ça, une courbe qui monte ou descend
  -- n'est attribuable à rien — et c'est irrattrapable après coup.
  `codeRef`    VARCHAR(60)  NOT NULL DEFAULT '',
  `model`      VARCHAR(120) NOT NULL DEFAULT '',
  `promptHash` VARCHAR(64)  NOT NULL DEFAULT '',
  `settings`   TEXT         NOT NULL,

  `inputTokens`  INTEGER NOT NULL DEFAULT 0,
  `outputTokens` INTEGER NOT NULL DEFAULT 0,
  `costUsd`      DOUBLE  NOT NULL DEFAULT 0,
  `items`        INTEGER NOT NULL DEFAULT 0,

  `queuedAt`   DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `startedAt`  DATETIME(3) NULL,
  `finishedAt` DATETIME(3) NULL,

  `requestedById` INTEGER NULL,

  PRIMARY KEY (`id`),
  INDEX `EvalRun_stage_queuedAt_idx` (`stage`, `queuedAt`),
  INDEX `EvalRun_status_idx` (`status`),
  CONSTRAINT `EvalRun_requestedById_fkey`
    FOREIGN KEY (`requestedById`) REFERENCES `User`(`id`) ON DELETE SET NULL ON UPDATE CASCADE
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE `EvalLinkResult` (
  `id`           INTEGER NOT NULL AUTO_INCREMENT,
  `url`          VARCHAR(500) NOT NULL,
  `text`         VARCHAR(200) NOT NULL DEFAULT '',
  `context`      TEXT NOT NULL,
  `harvested`    BOOLEAN NOT NULL DEFAULT false,
  `dropReason`   VARCHAR(60) NOT NULL DEFAULT '',
  `position`     INTEGER NOT NULL DEFAULT 0,
  `selected`     BOOLEAN NULL,
  `selectReason` TEXT NOT NULL,
  `runId`        INTEGER NOT NULL,
  `pageId`       INTEGER NOT NULL,

  PRIMARY KEY (`id`),
  UNIQUE INDEX `EvalLinkResult_runId_pageId_url_key` (`runId`, `pageId`, `url`),
  INDEX `EvalLinkResult_runId_idx` (`runId`),
  INDEX `EvalLinkResult_pageId_idx` (`pageId`),
  CONSTRAINT `EvalLinkResult_runId_fkey`
    FOREIGN KEY (`runId`) REFERENCES `EvalRun`(`id`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `EvalLinkResult_pageId_fkey`
    FOREIGN KEY (`pageId`) REFERENCES `EvalAgendaPage`(`id`) ON DELETE CASCADE ON UPDATE CASCADE
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE `EvalReadResult` (
  `id`             INTEGER NOT NULL AUTO_INCREMENT,
  `readUrl`        VARCHAR(500) NOT NULL DEFAULT '',
  `swapped`        BOOLEAN NOT NULL DEFAULT false,
  `text`           LONGTEXT NOT NULL,
  `textChars`      INTEGER NOT NULL DEFAULT 0,
  `dates`          TEXT NOT NULL,
  `imageUrl`       VARCHAR(500) NOT NULL DEFAULT '',
  `heading`        VARCHAR(200) NOT NULL DEFAULT '',
  `h1InText`       BOOLEAN NOT NULL DEFAULT false,
  `truncated`      BOOLEAN NOT NULL DEFAULT false,
  `tooShort`       BOOLEAN NOT NULL DEFAULT false,
  `imageLooksLogo` BOOLEAN NOT NULL DEFAULT false,
  `error`          TEXT NULL,
  `runId`          INTEGER NOT NULL,
  `readingId`      INTEGER NOT NULL,

  PRIMARY KEY (`id`),
  UNIQUE INDEX `EvalReadResult_runId_readingId_key` (`runId`, `readingId`),
  INDEX `EvalReadResult_runId_idx` (`runId`),
  INDEX `EvalReadResult_readingId_idx` (`readingId`),
  CONSTRAINT `EvalReadResult_runId_fkey`
    FOREIGN KEY (`runId`) REFERENCES `EvalRun`(`id`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `EvalReadResult_readingId_fkey`
    FOREIGN KEY (`readingId`) REFERENCES `EvalReading`(`id`) ON DELETE CASCADE ON UPDATE CASCADE
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE `EvalExtractResult` (
  `id`           INTEGER NOT NULL AUTO_INCREMENT,
  `fiche`        LONGTEXT NOT NULL,
  `aspects`      LONGTEXT NOT NULL,
  `inputTokens`  INTEGER NOT NULL DEFAULT 0,
  `outputTokens` INTEGER NOT NULL DEFAULT 0,
  `costUsd`      DOUBLE NOT NULL DEFAULT 0,
  `error`        TEXT NULL,
  `runId`        INTEGER NOT NULL,
  `readingId`    INTEGER NOT NULL,

  PRIMARY KEY (`id`),
  UNIQUE INDEX `EvalExtractResult_runId_readingId_key` (`runId`, `readingId`),
  INDEX `EvalExtractResult_runId_idx` (`runId`),
  INDEX `EvalExtractResult_readingId_idx` (`readingId`),
  CONSTRAINT `EvalExtractResult_runId_fkey`
    FOREIGN KEY (`runId`) REFERENCES `EvalRun`(`id`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `EvalExtractResult_readingId_fkey`
    FOREIGN KEY (`readingId`) REFERENCES `EvalReading`(`id`) ON DELETE CASCADE ON UPDATE CASCADE
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
