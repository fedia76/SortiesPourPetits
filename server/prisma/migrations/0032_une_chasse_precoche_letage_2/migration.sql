-- Une **chasse** : peupler le corpus de l'étage 2 depuis un prompt, au lieu
-- d'y coller des adresses une par une.
--
-- Étiqueter est le seul travail coûteux du banc, et le corpus de l'étage 2 le
-- payait au prix fort : une URL collée à la main, une nature choisie, un gel
-- demandé, et on recommence. Une chasse fait le trajet d'un coup — l'étage 1
-- lance les recherches, l'étage 2 dit ce qu'il pense de chaque page, un humain
-- corrige ce qui est faux et valide le reste.
--
-- ## Ce que la précoche ne doit jamais devenir
--
-- Un corpus rempli en acceptant les propositions de la brique mesurerait la
-- brique contre elle-même, et le taux serait flatteur par construction. C'est
-- exactement le travers que la provenance des champs d'une fiche nommait déjà
-- (`CORRIGE` contre `NON_CONTREDIT`), et il est ici plus dangereux encore
-- puisqu'il n'y a qu'une seule étiquette à poser.
--
-- D'où deux garde-fous, tous deux dans ce fichier :
--
--   · `EvalHuntPage.proposed` est **nullable**. Une page que l'étage 2 ne sait
--     pas reconnaître part sans précoche et attend un humain. Le pipeline, lui,
--     tranche — il traite « inconnu » en agenda —, mais c'est une décision
--     d'orchestration : la recopier écrirait au corpus ce que le pipeline fait
--     au lieu de ce que la page est, c'est-à-dire ce qu'on cherche à mesurer ;
--   · `EvalNature.origin` garde, pour toujours, si l'humain a corrigé la
--     précoche ou l'a laissée passer. Les renseignements sont dans les
--     `CORRIGE`, et c'est le premier chiffre à regarder.
--
-- ## Pourquoi une chasse a le droit d'être en ligne
--
-- Un run ne peut pas l'être : il doit rendre le même chiffre six mois plus
-- tard, donc rejouer sur du HTML gelé. Une chasse **construit** le corpus, elle
-- ne le mesure pas — et elle gèle le HTML au passage, de sorte que la page
-- qu'un run rejouera est exactement celle sur laquelle la précoche a été faite,
-- et non celle que le site servira le jour où quelqu'un validera.

-- ─────────────────────────────── d'où vient l'étiquette d'une page du corpus

ALTER TABLE `EvalNature`
  ADD COLUMN `proposed` ENUM('AGENDA', 'SORTIE', 'PROGRAMME', 'AUTRE') NULL,
  ADD COLUMN `origin` ENUM('SAISIE', 'CORRIGE', 'NON_CONTREDIT') NOT NULL DEFAULT 'SAISIE',
  ADD INDEX `EvalNature_origin_idx` (`origin`);

-- ───────────────────────────────────────────────────────────── les chasses

CREATE TABLE `EvalHunt` (
  `id`          INTEGER      NOT NULL AUTO_INCREMENT,

  -- Ce qu'on cherche, en une phrase. Part tel quel comme thème de l'étage 1.
  `prompt`      VARCHAR(300) NOT NULL,
  `area`        VARCHAR(120) NOT NULL DEFAULT 'Île-de-France',

  -- Requêtes imposées, en JSON. Vide : le modèle les formule, et ce sont
  -- celles-là que `ranQueries` gardera.
  `queries`     TEXT         NOT NULL,
  `maxQueries`  INTEGER      NOT NULL DEFAULT 6,
  `maxPages`    INTEGER      NOT NULL DEFAULT 30,
  `provider`    VARCHAR(20)  NOT NULL DEFAULT 'serper',

  `status`      ENUM('QUEUED', 'RUNNING', 'DONE', 'FAILED') NOT NULL DEFAULT 'QUEUED',
  `error`       TEXT         NULL,

  -- Écrits à la clôture : ce qu'on ne sait pas avant d'avoir joué. Sans eux,
  -- une chasse ne se rejoue pas et son rendement ne s'attribue à rien.
  `ranQueries`  TEXT         NOT NULL,
  `overCap`     INTEGER      NOT NULL DEFAULT 0,
  `costUsd`     DOUBLE       NOT NULL DEFAULT 0,
  `model`       VARCHAR(80)  NOT NULL DEFAULT '',
  `codeRef`     VARCHAR(60)  NOT NULL DEFAULT '',

  `queuedAt`    DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `startedAt`   DATETIME(3)  NULL,
  `endedAt`     DATETIME(3)  NULL,
  `createdById` INTEGER      NOT NULL,

  PRIMARY KEY (`id`),
  INDEX `EvalHunt_status_idx` (`status`),
  CONSTRAINT `EvalHunt_createdById_fkey`
    FOREIGN KEY (`createdById`) REFERENCES `User`(`id`) ON DELETE RESTRICT ON UPDATE CASCADE
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE `EvalHuntPage` (
  `id`         INTEGER      NOT NULL AUTO_INCREMENT,
  `huntId`     INTEGER      NOT NULL,

  -- L'adresse **reconnue** : celle de la jumelle française quand l'échange de
  -- langue a joué, sinon celle qu'a rendue la recherche. C'est celle-là qui
  -- entre au corpus, parce que c'est celle que le pipeline aurait dépouillée.
  `url`        VARCHAR(500) NOT NULL,
  `foundUrl`   VARCHAR(500) NOT NULL DEFAULT '',
  `title`      VARCHAR(300) NOT NULL DEFAULT '',
  `query`      VARCHAR(300) NOT NULL DEFAULT '',

  -- La précoche. NULL est un état de plein droit : voir l'en-tête.
  `proposed`   ENUM('AGENDA', 'SORTIE', 'PROGRAMME', 'AUTRE') NULL,
  `signal`     VARCHAR(30)  NOT NULL DEFAULT '',
  `detail`     VARCHAR(300) NOT NULL DEFAULT '',
  `confidence` VARCHAR(20)  NOT NULL DEFAULT '',
  `asked`      VARCHAR(80)  NOT NULL DEFAULT '',

  -- Le condensé : de quoi trancher sans ouvrir la page.
  `links`      INTEGER      NOT NULL DEFAULT 0,
  `dated`      INTEGER      NOT NULL DEFAULT 0,
  `heading`    VARCHAR(200) NOT NULL DEFAULT '',
  `opening`    TEXT         NOT NULL,

  `chars`      INTEGER      NOT NULL DEFAULT 0,
  `htmlPath`   VARCHAR(255) NULL,
  -- Page injoignable : rendue quand même, sans archive ni précoche. La perdre
  -- pour un accident du web serait perdre le travail de la recherche.
  `error`      VARCHAR(300) NOT NULL DEFAULT '',

  `decision`   ENUM('EN_ATTENTE', 'RETENUE', 'ECARTEE') NOT NULL DEFAULT 'EN_ATTENTE',
  `decidedAt`  DATETIME(3)  NULL,
  `natureId`   INTEGER      NULL,

  `createdAt`  DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),

  PRIMARY KEY (`id`),
  UNIQUE INDEX `EvalHuntPage_huntId_url_key` (`huntId`, `url`),
  UNIQUE INDEX `EvalHuntPage_natureId_key` (`natureId`),
  INDEX `EvalHuntPage_decision_idx` (`decision`),
  CONSTRAINT `EvalHuntPage_huntId_fkey`
    FOREIGN KEY (`huntId`) REFERENCES `EvalHunt`(`id`) ON DELETE CASCADE ON UPDATE CASCADE,
  -- Retirer une page du corpus ne doit pas effacer la trace de la chasse qui
  -- l'avait proposée : la candidate survit, orpheline, et dit ce qu'on en
  -- avait fait.
  CONSTRAINT `EvalHuntPage_natureId_fkey`
    FOREIGN KEY (`natureId`) REFERENCES `EvalNature`(`id`) ON DELETE SET NULL ON UPDATE CASCADE
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
