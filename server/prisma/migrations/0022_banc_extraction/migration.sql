-- Le banc d'extraction : l'étage 6, le premier que le banc mesure et qui coûte.
--
-- Une fiche par page du banc de lecture, et c'est le point : l'étage 6 ne lit
-- pas une page, il lit le texte que l'étage 5 lui tend. Rejouer l'extraction
-- sur la page vivante mêlerait deux mesures — une fiche sans tarif ne dirait
-- plus si le modèle l'a raté ou si la lecture l'avait déjà emporté avec un
-- <aside>. En partant du texte archivé, l'entrée est acquise.
--
-- Trois colonnes JSON plutôt que trois tables. La liste des aspects est
-- définie côté Python (`evaluation.audit_fiche`) et elle bougera avec le
-- schéma d'extraction : une table imposerait une migration à chaque champ
-- ajouté, pour une mesure que le serveur agrège de toute façon en mémoire,
-- sur quelques dizaines de lignes.
CREATE TABLE `EvalExtraction` (
  `id`     INTEGER NOT NULL AUTO_INCREMENT,
  `status` ENUM('QUEUED', 'RUNNING', 'ANALYZED', 'FAILED', 'VALIDATED') NOT NULL DEFAULT 'QUEUED',
  `error`  TEXT NULL,
  `note`   TEXT NOT NULL,

  -- Une mesure sans le nom du modèle ne se compare à rien : c'est la première
  -- chose qui change entre deux campagnes.
  `model` VARCHAR(120) NOT NULL DEFAULT '',

  -- La fiche rendue, entière, y compris les champs qu'aucun aspect ne juge :
  -- c'est la pièce à conviction, et une mesure dont on ne peut plus relire
  -- l'objet n'est pas vérifiable.
  `fiche` TEXT NOT NULL,

  -- Les douze aspects : libellé, valeur en clair, renseigné ou non, quel
  -- instrument l'a examiné, et les défauts relevés. Des libellés, pas des
  -- verdicts : le modèle a rendu ce qu'il a rendu, et c'est ce rendu qu'on
  -- mesure. Ils disent seulement où regarder d'abord.
  `aspects` TEXT NOT NULL,

  -- Ce qu'un humain dit de chaque aspect : {"tarif": "JUSTE", ...}. Une clé
  -- absente veut dire « personne n'a encore regardé », sans ambiguïté — c'est
  -- ce qui remplace le `reviewed` de l'étage 3.
  `verdicts` TEXT NOT NULL,

  -- Le premier étage du banc dont la mesure se paie. Le taire donnerait
  -- l'impression qu'elle est gratuite comme les deux précédentes.
  `inputTokens`  INTEGER NOT NULL DEFAULT 0,
  `outputTokens` INTEGER NOT NULL DEFAULT 0,
  `costUsd`      DOUBLE NOT NULL DEFAULT 0,

  `createdAt`   DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `analyzedAt`  DATETIME(3) NULL,
  `validatedAt` DATETIME(3) NULL,
  `readingId`   INTEGER NOT NULL,
  `createdById` INTEGER NOT NULL,

  UNIQUE INDEX `EvalExtraction_readingId_key`(`readingId`),
  INDEX `EvalExtraction_status_idx`(`status`),
  INDEX `EvalExtraction_createdById_idx`(`createdById`),
  PRIMARY KEY (`id`)
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- La lecture emporte son extraction : sans le texte de l'étage 5, la fiche
-- mesurée n'a plus d'entrée, et une mesure dont on ignore l'entrée ne mesure
-- rien.
ALTER TABLE `EvalExtraction`
  ADD CONSTRAINT `EvalExtraction_readingId_fkey`
  FOREIGN KEY (`readingId`) REFERENCES `EvalReading`(`id`)
  ON DELETE CASCADE ON UPDATE CASCADE;

-- Même règle qu'ailleurs au banc : une mesure validée est une vérité de
-- référence, elle ne doit pas disparaître avec le compte qui l'a saisie.
ALTER TABLE `EvalExtraction`
  ADD CONSTRAINT `EvalExtraction_createdById_fkey`
  FOREIGN KEY (`createdById`) REFERENCES `User`(`id`)
  ON DELETE RESTRICT ON UPDATE CASCADE;
