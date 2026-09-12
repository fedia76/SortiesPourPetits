-- Le groupe 1 du corpus : ce qu'une page **est**.
--
-- C'est la question de l'étage 2 — `stages/identification.py`. La découverte
-- rend des adresses sans rien en dire, et c'est là qu'on décide où chacune va :
-- un agenda part au dépouillement, une sortie saute à la lecture, un programme
-- y saute aussi mais on en attend plusieurs fiches, et le reste n'a rien à
-- faire dans la chaîne.
--
-- L'erreur n'y est pas symétrique, et c'est ce qui rend la mesure utile :
-- prendre une sortie pour un agenda coûte un appel de tri et se rattrape tout
-- seul — le dépouillement ne donne rien, et l'orchestrateur relit la page pour
-- elle-même. Prendre un agenda pour une sortie coûte **tous ses liens**, sans
-- rattrapage.
--
-- ## Pourquoi une table à part
--
-- Ni `EvalAgenda` ni `EvalSortie` ne convient : l'un présuppose que la page est
-- un agenda, l'autre qu'elle est une sortie — c'est justement la question qu'on
-- pose. Et il faut pouvoir y mettre des contre-exemples : une page d'accueil,
-- un article de blog, une billetterie. Sans eux, on ne mesurerait que les cas
-- où l'étage 2 a déjà raison.
--
-- ## Pourquoi le HTML gelé
--
-- L'étage 2 décide **en lisant la page** : l'adresse, la pagination, le
-- JSON-LD, les métadonnées, puis le modèle sur un condensé quand tout se tait.
-- Une étiquette posée sur une adresse nue ne serait rejouable contre rien.
--
-- La capture réutilise le worker existant, qui est agnostique : il reçoit un
-- `kind`, une adresse, un nombre de pages, et rend le HTML. Un troisième type
-- ne lui demande aucun changement.

CREATE TABLE `EvalNature` (
  `id`           INTEGER      NOT NULL AUTO_INCREMENT,
  `url`          VARCHAR(500) NOT NULL,
  `label`        VARCHAR(150) NOT NULL DEFAULT '',

  `capture`      ENUM('QUEUED', 'RUNNING', 'CAPTURED', 'FAILED') NOT NULL DEFAULT 'QUEUED',
  `captureError` TEXT         NULL,
  `capturedAt`   DATETIME(3)  NULL,
  `chars`        INTEGER      NOT NULL DEFAULT 0,
  `htmlPath`     VARCHAR(255) NULL,

  -- Jamais nul : la ligne n'existerait pas. C'est l'étiquette elle-même, et
  -- son absence dit que personne n'a regardé — la même règle que partout
  -- ailleurs dans ce corpus.
  `nature`       ENUM('AGENDA', 'SORTIE', 'PROGRAMME', 'AUTRE') NOT NULL,

  `note`         TEXT         NOT NULL,
  `labelledAt`   DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `createdById`  INTEGER      NOT NULL,
  `createdAt`    DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),

  PRIMARY KEY (`id`),
  UNIQUE INDEX `EvalNature_url_key` (`url`),
  INDEX `EvalNature_capture_idx` (`capture`),
  INDEX `EvalNature_nature_idx` (`nature`),
  CONSTRAINT `EvalNature_createdById_fkey`
    FOREIGN KEY (`createdById`) REFERENCES `User`(`id`) ON DELETE RESTRICT ON UPDATE CASCADE
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
