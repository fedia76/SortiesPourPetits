-- Une page gelée telle qu'elle a été lue.
--
-- ## Ce qui manquait
--
-- Rien ne gardait le HTML qu'une exécution avait réellement lu. Le banc gèle
-- bien des agendas, mais après la clôture, en les téléchargeant **de
-- nouveau** : c'est la page du lendemain, pas celle que le scraper a vue.
-- Impossible, donc, de répondre après coup à « est-ce que le scraper voyait
-- cet élément ? » — la question qui se pose dès qu'une page lisible dans un
-- navigateur ne donne rien : le navigateur exécute du JavaScript, le scraper
-- non.
--
-- ## Ce que ça change
--
-- Une ligne par page téléchargée pendant l'exécution, avec le code HTTP de la
-- réponse et le chemin du fichier gzippé. Une page refusée (403, 429…) est
-- gelée aussi : la page de blocage dit souvent qui bloque et pourquoi.
--
-- Une par adresse et par exécution : une page relue n'est pas regelée.

CREATE TABLE `ScraperRunPage` (
    `id` INTEGER NOT NULL AUTO_INCREMENT,
    `url` VARCHAR(500) NOT NULL,
    `status` INTEGER NOT NULL,
    `htmlPath` VARCHAR(255) NOT NULL,
    `bytes` INTEGER NOT NULL,
    `at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    `runId` INTEGER NOT NULL,

    UNIQUE INDEX `ScraperRunPage_runId_url_key`(`runId`, `url`),
    PRIMARY KEY (`id`)
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

ALTER TABLE `ScraperRunPage` ADD CONSTRAINT `ScraperRunPage_runId_fkey` FOREIGN KEY (`runId`) REFERENCES `ScraperRun`(`id`) ON DELETE CASCADE ON UPDATE CASCADE;
