-- Défaire ce qu'une exécution a produit.
--
-- Supprimer ses sorties était déjà possible une par une ; oublier ce qu'elle
-- avait mémorisé ne l'était pas. La mémoire est indexée par clé normalisée,
-- alors que le journal ne gardait que le lien exact : les deux ne se
-- rejoignaient pas. `key` conserve donc la clé employée, ce qui rend la purge
-- exacte. Les exécutions antérieures n'en ont pas ; on retombe alors sur leur
-- URL, qui couvre les pages dont le lien était déjà normalisé.
ALTER TABLE `ScraperRunItem` ADD COLUMN `key` VARCHAR(500) NULL;

-- Une exécution vidée garde son journal — il dit ce qu'elle a fait — mais la
-- console doit pouvoir signaler que ses compteurs ne correspondent plus à
-- rien de vivant.
ALTER TABLE `ScraperRun` ADD COLUMN `purgedAt` DATETIME(3) NULL;
