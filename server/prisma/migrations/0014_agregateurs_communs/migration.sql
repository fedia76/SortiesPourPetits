-- Les agrégateurs deviennent une liste commune, tenue depuis la console.
--
-- Ils étaient un champ libre par recherche : la même quinzaine de domaines
-- recopiée dans chaque configuration, avec la certitude qu'un jour l'une
-- d'elles serait oubliée. Or un agrégateur n'est pas une préférence de
-- recherche : kidiklik republie, quelle que soit la recherche qui l'a
-- trouvé. La liste monte donc d'un cran, et chaque recherche ne garde qu'une
-- décision : lire ces sites, ou les refuser (`blockAggregators`).

CREATE TABLE `Aggregator` (
    `id` INTEGER NOT NULL AUTO_INCREMENT,
    `domain` VARCHAR(191) NOT NULL,
    `label` VARCHAR(191) NOT NULL DEFAULT '',
    `enabled` BOOLEAN NOT NULL DEFAULT true,
    `note` TEXT NOT NULL,
    `createdAt` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    `updatedAt` DATETIME(3) NOT NULL,

    UNIQUE INDEX `Aggregator_domain_key`(`domain`),
    PRIMARY KEY (`id`)
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- La liste intégrée au scraper, telle qu'elle s'appliquait par défaut jusqu'ici
-- (`sortiesbot/config.py::DEFAULT_AGGREGATOR_DOMAINS`). Elle devient modifiable :
-- c'est une amorce, pas une définition figée. Une liste vidée ne désactive pas
-- l'attribution — remonter à l'organisateur reste préférable, d'où qu'on vienne.
INSERT INTO `Aggregator` (`domain`, `label`, `note`, `updatedAt`) VALUES
  ('kidiklik.fr', 'Kidiklik', '', NOW(3)),
  ('citizenkid.com', 'CitizenKid', '', NOW(3)),
  ('parismomes.fr', 'Paris Mômes', '', NOW(3)),
  ('familyinparis.fr', 'Family in Paris', '', NOW(3)),
  ('sortiraparis.com', 'Sortir à Paris', '', NOW(3)),
  ('parisetudiant.com', 'Paris Étudiant', '', NOW(3)),
  ('unjourdeplusaparis.com', 'Un jour de plus à Paris', '', NOW(3)),
  ('offi.fr', 'Offi', '', NOW(3)),
  ('timeout.fr', 'Time Out', '', NOW(3)),
  ('lylo.fr', 'Lylo', '', NOW(3)),
  ('petitfute.com', 'Petit Futé', '', NOW(3)),
  ('tripadvisor.fr', 'Tripadvisor', '', NOW(3)),
  ('infolocale.fr', 'Infolocale', '', NOW(3)),
  ('wherevent.com', 'Wherevent', '', NOW(3)),
  ('agendaculturel.fr', 'L''Agenda culturel', '', NOW(3));

-- Les domaines saisis dans une recherche et absents de la liste par défaut sont
-- repris : personne ne doit perdre un réglage en migrant. Le préfixe et le
-- suffixe encadrent la valeur pour que `SUBSTRING_INDEX` découpe sans cas
-- particulier, et la jointure sur une table de rangs fait office de boucle —
-- dix domaines par recherche suffisent largement à ce qui existe.
INSERT IGNORE INTO `Aggregator` (`domain`, `label`, `note`, `updatedAt`)
SELECT domaine, '', CONCAT('Repris de la recherche « ', nom, ' » à la migration.'), NOW(3)
FROM (
  SELECT
    c.`name` AS nom,
    TRIM(SUBSTRING_INDEX(SUBSTRING_INDEX(c.`aggregatorDomains`, ',', r.n), ',', -1)) AS domaine
  FROM `ScraperConfig` c
  JOIN (
    SELECT 1 AS n UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4 UNION ALL SELECT 5
    UNION ALL SELECT 6 UNION ALL SELECT 7 UNION ALL SELECT 8 UNION ALL SELECT 9 UNION ALL SELECT 10
  ) r
    ON r.n <= CHAR_LENGTH(c.`aggregatorDomains`) - CHAR_LENGTH(REPLACE(c.`aggregatorDomains`, ',', '')) + 1
  WHERE c.`aggregatorDomains` <> ''
) decoupe
WHERE domaine <> '';

-- Une recherche ne porte plus la liste ; elle porte une décision. Faux pour
-- toutes : c'est le comportement d'avant, où les agrégateurs étaient lus.
ALTER TABLE `ScraperConfig`
  ADD COLUMN `blockAggregators` BOOLEAN NOT NULL DEFAULT false,
  DROP COLUMN `aggregatorDomains`,
  -- Les pages illisibles — réseaux sociaux, vidéos — ne sont pas un réglage de
  -- recherche mais un fait du web : le scraper en garde la liste, et le champ
  -- libre qui la recopiait disparaît.
  DROP COLUMN `blockedDomains`;

-- Une page suivante n'est pas un agenda de plus. `pages` continue de compter ce
-- qui a été téléchargé ; la différence dit combien d'agendas ont été ouverts.
ALTER TABLE `ScraperRun`
  ADD COLUMN `nextPages` INTEGER NOT NULL DEFAULT 0;
