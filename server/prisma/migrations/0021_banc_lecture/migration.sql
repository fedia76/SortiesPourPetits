-- Le banc de lecture : l'étage 5.
--
-- L'étage 3 se mesure sur des agendas, celui-ci sur des fiches. Ce ne sont pas
-- les mêmes pages, donc pas le même corpus, donc pas la même table.
--
-- Ce qu'on y mesure, ce sont les trois lectures que l'étage fait d'un même
-- HTML — le texte qui part au modèle, les dates que le site déclare,
-- l'illustration — plus la décision qui en découle : sous le seuil de deux
-- cents caractères, la page est abandonnée avant le moindre appel payant.
--
-- Les quatre booléens sont des signaux gratuits, et ils ne décident de rien :
-- la brique a déjà rendu ce qu'elle rend, et c'est ce rendu qu'on mesure. Ils
-- disent seulement où regarder, parce qu'une page qui se lit mal se reconnaît
-- presque toujours à l'un d'eux. Le premier est le plus utile : quand le titre
-- de la page ne se retrouve pas dans le texte extrait, c'est que le décapage a
-- emporté le bloc qui le portait — presque toujours un <header>, et avec lui
-- les dates et l'adresse. Le texte reste non vide, rien ne proteste, et c'est
-- l'extraction qu'on ira accuser de rendre une fiche sans date.
CREATE TABLE `EvalReading` (
  `id`     INTEGER NOT NULL AUTO_INCREMENT,
  `url`    VARCHAR(500) NOT NULL,
  `label`  VARCHAR(191) NOT NULL DEFAULT '',
  `status` ENUM('QUEUED', 'RUNNING', 'ANALYZED', 'FAILED', 'VALIDATED') NOT NULL DEFAULT 'QUEUED',
  `error`  TEXT NULL,
  `note`   TEXT NOT NULL,

  -- ce que la brique a rendu
  `readUrl`   VARCHAR(500) NOT NULL DEFAULT '',
  `swapped`   BOOLEAN NOT NULL DEFAULT false,
  `text`      TEXT NOT NULL,
  `textChars` INTEGER NOT NULL DEFAULT 0,
  `dates`     TEXT NOT NULL,
  `imageUrl`  VARCHAR(500) NOT NULL DEFAULT '',
  `chars`     INTEGER NOT NULL DEFAULT 0,
  `htmlPath`  VARCHAR(255) NULL,

  -- les signaux gratuits
  `heading`        VARCHAR(200) NOT NULL DEFAULT '',
  `h1InText`       BOOLEAN NOT NULL DEFAULT false,
  `truncated`      BOOLEAN NOT NULL DEFAULT false,
  `tooShort`       BOOLEAN NOT NULL DEFAULT false,
  `imageLooksLogo` BOOLEAN NOT NULL DEFAULT false,

  -- ce qu'un humain en dit. Nul tant qu'il n'a rien dit : la console propose ce
  -- que la brique prétend, mais rien de cette proposition n'est écrit ici. Une
  -- page n'est jugée que lorsque les trois verdicts sont posés, et c'est ce qui
  -- remplace le `reviewed` de l'étage 3 — trois clics, il n'y a rien à
  -- précocher en base.
  `textVerdict`  ENUM('CORRECT', 'AMPUTE', 'TRONQUE', 'HORS_SUJET') NULL,
  `imageVerdict` ENUM('CORRECTE', 'LOGO', 'MAUVAISE', 'MANQUANTE') NULL,
  `datesVerdict` ENUM('CORRECTES', 'INCOMPLETES', 'FAUSSES', 'MANQUANTES') NULL,

  `createdAt`   DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `analyzedAt`  DATETIME(3) NULL,
  `validatedAt` DATETIME(3) NULL,
  `createdById` INTEGER NOT NULL,

  UNIQUE INDEX `EvalReading_url_key`(`url`),
  INDEX `EvalReading_status_idx`(`status`),
  INDEX `EvalReading_createdById_idx`(`createdById`),
  PRIMARY KEY (`id`)
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- Même règle que pour les agendas : une page validée est une vérité de
-- référence, elle ne doit pas disparaître avec le compte qui l'a saisie.
ALTER TABLE `EvalReading`
  ADD CONSTRAINT `EvalReading_createdById_fkey`
  FOREIGN KEY (`createdById`) REFERENCES `User`(`id`)
  ON DELETE RESTRICT ON UPDATE CASCADE;
