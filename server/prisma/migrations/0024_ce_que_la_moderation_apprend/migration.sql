-- Fermer la boucle : ce que la modération sait, le scraper l'ignorait.
--
-- Le pipeline propose, un humain approuve ou refuse, et rien ne revenait
-- jamais vers l'amont. C'était le seul retour d'information gratuit et continu
-- du projet, et il tombait par terre à chaque fiche.
--
-- Trois ajouts, aucun qui demande un geste de plus au modérateur : un motif de
-- refus qui s'additionne, la trace de ce qu'il corrige avant d'approuver, et
-- la provenance recopiée sur l'item pour qu'elle survive à la purge du
-- journal. Le worker, lui, n'est pas touché.

-- ── 1. Le motif de refus, sous une forme comptable ──────────────────────
--
-- Le texte libre reste : c'est ce que l'auteur lit. Mais il ne s'additionne
-- pas, et un motif n'apprend quelque chose que s'il désigne un étage — d'où
-- cette liste-ci plutôt qu'une autre, chaque valeur étant un reproche adressé
-- à une brique précise. Ce qui n'en désigne aucune reste `AUTRE`.
ALTER TABLE `Event`
  ADD COLUMN `rejectionCode` ENUM(
    'HORS_SUJET',
    'PAS_POUR_ENFANTS',
    'DATE_FAUSSE',
    'LIEU_FAUX',
    'TARIF_FAUX',
    'DESCRIPTION_INUTILISABLE',
    'MAUVAIS_LIEN',
    'DOUBLON',
    'DEJA_PASSEE',
    'AUTRE'
  ) NULL;

-- ── 2. Ce que le modérateur corrige avant d'approuver ───────────────────
--
-- La mesure la moins chère du projet : personne n'étiquette rien, on
-- enregistre un geste déjà fait. Et la seule qui dise *où* l'étage 6 se
-- trompe — un taux d'approbation dit qu'une fiche était mauvaise, ceci dit
-- que c'était la ville.
--
-- ON DELETE CASCADE : la correction ne décrit rien sans sa fiche, à la
-- différence d'un journal d'exécution, qui vaut d'être gardé seul.
CREATE TABLE `EventCorrection` (
  `id`      INTEGER      NOT NULL AUTO_INCREMENT,
  `eventId` INTEGER      NOT NULL,
  -- Le nom que l'API donne au champ : `title`, `venueCity`, `price`… Le même
  -- vocabulaire que le payload du scraper, pour que la mesure se lise en
  -- regard de l'étage qui l'a produit.
  `field`   VARCHAR(40)  NOT NULL,
  -- Tronqués à cinq cents caractères : on mesure une fréquence, on ne rejoue
  -- pas la fiche. Une description de dix mille signes n'apprendrait rien de
  -- plus qu'un début lisible.
  `before`  VARCHAR(500) NULL,
  `after`   VARCHAR(500) NULL,
  `at`      DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),

  PRIMARY KEY (`id`),
  INDEX `EventCorrection_eventId_idx` (`eventId`),
  INDEX `EventCorrection_field_idx` (`field`),
  CONSTRAINT `EventCorrection_eventId_fkey`
    FOREIGN KEY (`eventId`) REFERENCES `Event`(`id`) ON DELETE CASCADE ON UPDATE CASCADE
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- ── 3. La provenance, recopiée sur l'item ───────────────────────────────
--
-- Le scraper journalise déjà la filiation (pistes `agenda` et `query` de
-- `RunLog.trail`), mais dans `ScraperRunLog` — que la console permet d'oublier
-- run par run, et qu'on n'a pas vocation à garder trois mois. Ces colonnes la
-- figent à la clôture : le rendement d'une requête se lit alors d'une
-- jointure, et il survit à la purge du journal.
--
-- Renseignées par le site, jamais par le worker. Nulles pour tout ce qui a
-- été exécuté avant, et pour les runs dont le journal a déjà disparu.
ALTER TABLE `ScraperRunItem`
  ADD COLUMN `agendaUrl` VARCHAR(500) NULL,
  ADD COLUMN `query`     VARCHAR(300) NULL;
