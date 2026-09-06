-- Le banc d'évaluation, et son premier étage mesuré : le dépouillement.
--
-- Le pipeline sait dire qu'une sortie proposée était fausse — le modérateur la
-- refuse, et ce refus est une étiquette. Il ne sait pas dire qu'une sortie a
-- été manquée : un lien que le dépouillement n'a pas vu n'est relu par
-- personne. La précision a le filet de la modération, le rappel n'en a aucun.
--
-- D'où ces trois tables. Un agenda réel, ses pages telles qu'elles ont été
-- servies, et les liens que `links_of` en a tirés — complétés à la main par
-- ceux qu'il a manqués. C'est cette complétion qui est la mesure : elle ne
-- peut pas se déduire du HTML, parce qu'aucun site ne déclare quelles de ses
-- URL sont ses propres fiches.
--
-- Une fois posée, l'étiquette ne périme plus : la page est datée, le contrôle
-- se rejoue sans réseau et sans appel de modèle.

-- Un agenda du banc. Le statut sert aussi de file : le worker réclame ce qui
-- est en QUEUED, exactement comme il réclame une exécution du scraper.
-- VALIDATED est le seul état que le worker ne produit jamais — il dit qu'un
-- humain est passé, et c'est ce qui fait de la ligne une vérité de référence.
CREATE TABLE `EvalAgenda` (
  `id`          INTEGER NOT NULL AUTO_INCREMENT,
  `url`         VARCHAR(500) NOT NULL,
  `label`       VARCHAR(191) NOT NULL DEFAULT '',
  `status`      ENUM('QUEUED', 'RUNNING', 'ANALYZED', 'FAILED', 'VALIDATED') NOT NULL DEFAULT 'QUEUED',
  -- Un nombre fixe de pages, et non la politique de l'étage 3 qui en suit
  -- tant qu'il manque de liens : ce qu'on mesure ici est `links_of` sur une
  -- page donnée, pas la décision d'en ouvrir une de plus.
  `pages`       INTEGER NOT NULL DEFAULT 1,
  `error`       TEXT NULL,
  `note`        TEXT NOT NULL,
  `createdAt`   DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `analyzedAt`  DATETIME(3) NULL,
  `validatedAt` DATETIME(3) NULL,
  `createdById` INTEGER NOT NULL,

  UNIQUE INDEX `EvalAgenda_url_key`(`url`),
  INDEX `EvalAgenda_status_idx`(`status`),
  INDEX `EvalAgenda_createdById_idx`(`createdById`),
  PRIMARY KEY (`id`)
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- Une page réellement téléchargée : la première, puis chaque `rel="next"`
-- suivi. C'est le niveau auquel la console groupe les liens, parce que c'est
-- celui auquel `links_of` travaille — une page, une moisson.
--
-- `chars` n'est pas décoratif : un effondrement de la taille du HTML d'un run
-- à l'autre est le premier signe qu'un site s'est mis à charger sa liste en
-- JavaScript, et donc que le dépouillement ne verra plus rien.
CREATE TABLE `EvalAgendaPage` (
  `id`       INTEGER NOT NULL AUTO_INCREMENT,
  `pageNo`   INTEGER NOT NULL,
  `url`      VARCHAR(500) NOT NULL,
  `chars`    INTEGER NOT NULL DEFAULT 0,
  `error`    TEXT NULL,
  `agendaId` INTEGER NOT NULL,

  UNIQUE INDEX `EvalAgendaPage_agendaId_pageNo_key`(`agendaId`, `pageNo`),
  INDEX `EvalAgendaPage_agendaId_idx`(`agendaId`),
  PRIMARY KEY (`id`)
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- Un lien de cette page. `source` porte toute la mesure : le rappel du
-- dépouillement est le nombre de HARVEST sur le total, et un MANUAL est très
-- exactement un lien que `links_of` aurait dû voir.
--
-- `context` reste vide pour un ajout manuel, et c'est délibéré : l'humain
-- donne une URL, pas le texte qui l'entoure. En fabriquer un ferait croire à
-- l'étage 4 qu'il a reçu quelque chose que le dépouillement ne lui aurait
-- jamais donné.
CREATE TABLE `EvalLink` (
  `id`      INTEGER NOT NULL AUTO_INCREMENT,
  `url`     VARCHAR(500) NOT NULL,
  `text`    VARCHAR(200) NOT NULL DEFAULT '',
  `context` TEXT NOT NULL,
  `source`  ENUM('HARVEST', 'MANUAL') NOT NULL DEFAULT 'HARVEST',
  `note`    TEXT NOT NULL,
  `addedAt` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `pageId`  INTEGER NOT NULL,

  UNIQUE INDEX `EvalLink_pageId_url_key`(`pageId`, `url`),
  INDEX `EvalLink_pageId_idx`(`pageId`),
  PRIMARY KEY (`id`)
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- L'auteur reste, la ligne aussi : un agenda validé est une vérité de
-- référence, elle ne doit pas disparaître avec le compte qui l'a saisie. D'où
-- RESTRICT plutôt que CASCADE — supprimer un tel compte demandera de dire
-- explicitement quoi faire de ses agendas.
ALTER TABLE `EvalAgenda`
  ADD CONSTRAINT `EvalAgenda_createdById_fkey`
  FOREIGN KEY (`createdById`) REFERENCES `User`(`id`)
  ON DELETE RESTRICT ON UPDATE CASCADE;

-- Les pages et les liens, eux, n'existent que par leur agenda.
ALTER TABLE `EvalAgendaPage`
  ADD CONSTRAINT `EvalAgendaPage_agendaId_fkey`
  FOREIGN KEY (`agendaId`) REFERENCES `EvalAgenda`(`id`)
  ON DELETE CASCADE ON UPDATE CASCADE;

ALTER TABLE `EvalLink`
  ADD CONSTRAINT `EvalLink_pageId_fkey`
  FOREIGN KEY (`pageId`) REFERENCES `EvalAgendaPage`(`id`)
  ON DELETE CASCADE ON UPDATE CASCADE;
