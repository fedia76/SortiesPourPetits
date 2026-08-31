-- Le journal détaillé d'une exécution, étage par étage.
--
-- `ScraperRunItem` disait déjà le sort de chaque page — c'est le verdict.
-- Il ne disait pas comment on y était arrivé : quelles requêtes ont été
-- lancées, quels liens ont été extraits puis retenus, quel prompt est parti,
-- combien de jetons ont été consommés à quel étage. Tout cela existait déjà
-- dans le `RunLog` du scraper, mais mourait sur la sortie standard du service
-- systemd. Cette table lui donne une destination consultable.
--
-- Deux colonnes portent le sens : `stage`, l'un des six étages du pipeline
-- (voir scraper/sortiesbot/stages.py), et `seq`, le numéro d'ordre émis par le
-- scraper — c'est lui qui pagine sans rien perdre, là où l'horodatage a des
-- ex æquo à la seconde près.
CREATE TABLE `ScraperRunLog` (
    `id` INTEGER NOT NULL AUTO_INCREMENT,
    `runId` INTEGER NOT NULL,
    `seq` INTEGER NOT NULL,
    `at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    `stage` VARCHAR(24) NULL,
    `kind` VARCHAR(40) NOT NULL,
    `level` VARCHAR(8) NOT NULL DEFAULT 'info',
    `url` VARCHAR(500) NULL,
    `message` TEXT NULL,
    `data` TEXT NULL,

    -- L'ordre de lecture de la console : un run, ses événements dans l'ordre.
    INDEX `ScraperRunLog_runId_seq_idx`(`runId`, `seq`),
    -- Le filtre par brique du graphe, qui est le geste le plus fréquent.
    INDEX `ScraperRunLog_runId_stage_idx`(`runId`, `stage`),
    PRIMARY KEY (`id`)
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

ALTER TABLE `ScraperRunLog` ADD CONSTRAINT `ScraperRunLog_runId_fkey`
    FOREIGN KEY (`runId`) REFERENCES `ScraperRun`(`id`) ON DELETE CASCADE ON UPDATE CASCADE;
