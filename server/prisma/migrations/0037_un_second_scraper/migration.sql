-- Un second scraper : l'agent.
--
-- ## Ce qui change
--
-- Une exécution dit désormais **quel scraper** la joue. Le pipeline
-- (`sortiesbot`) enchaîne ses huit étages dans un ordre écrit d'avance ;
-- l'agent (`agentbot`) laisse un modèle choisir l'étape suivante, avec les
-- mêmes briques. Chacun a son worker, et chacun ne réclame que ses exécutions.
--
-- Toutes les exécutions existantes ont été jouées par le pipeline : c'est le
-- défaut de la colonne, et c'est la vérité. Le worker du pipeline n'a pas
-- changé — il ne sait rien de ce champ — et c'est ce défaut qui lui garantit
-- de ne jamais recevoir une exécution destinée à l'agent.
--
-- `pilot` est le modèle qui pilote l'agent, nul pour le pipeline.
--
-- L'index sert la seule requête qui lit la colonne à chaud : la prise de
-- travail des workers, toutes les trente secondes, sur le statut et le moteur.

ALTER TABLE `ScraperRun` ADD COLUMN `engine` VARCHAR(16) NOT NULL DEFAULT 'pipeline';
ALTER TABLE `ScraperRun` ADD COLUMN `pilot` VARCHAR(100) NULL;
CREATE INDEX `ScraperRun_status_engine_idx` ON `ScraperRun`(`status`, `engine`);
