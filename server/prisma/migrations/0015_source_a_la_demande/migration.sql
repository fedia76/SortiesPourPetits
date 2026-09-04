-- Chercher la source d'une sortie à la demande, depuis sa fiche.
--
-- L'étage 7 du scraper remonte de la page lue à celle de l'organisateur, mais
-- il ne le fait qu'au fil d'une recherche : une sortie déjà en base, dont le
-- lien pointe sur un agrégateur, restait comme ça pour toujours. Un modérateur
-- peut désormais relancer cet étage-là, et lui seul, depuis la fiche.
--
-- Une telle exécution est une `ScraperRun` comme une autre — elle a un
-- journal, un graphe, une page de débogage, et la mesure de l'étage 7 s'y
-- applique telle quelle. Ce qui change tient en deux colonnes.

-- 1. Elle ne joue aucune recherche, donc elle n'a pas de configuration : ni
--    thème, ni zone, ni période n'auraient de sens. La contrainte reste en
--    CASCADE — supprimer une recherche emporte toujours ses exécutions — mais
--    elle ne s'applique plus qu'à celles qui en ont une.
ALTER TABLE `ScraperRun` DROP FOREIGN KEY `ScraperRun_configId_fkey`;
ALTER TABLE `ScraperRun` MODIFY `configId` INTEGER NULL;
ALTER TABLE `ScraperRun`
  ADD CONSTRAINT `ScraperRun_configId_fkey`
  FOREIGN KEY (`configId`) REFERENCES `ScraperConfig`(`id`)
  ON DELETE CASCADE ON UPDATE CASCADE;

-- 2. Elle porte la sortie sur laquelle elle travaille. C'est ce champ, et non
--    un mode de plus, qui dit au worker de ne jouer que l'attribution : une
--    exécution qui porte une sortie cherche sa source, une exécution qui porte
--    une configuration joue le pipeline entier.
--
--    `SET NULL` plutôt que `CASCADE` : la sortie peut être supprimée, le
--    journal de la recherche reste. Il dit ce qui a été cherché, et pourquoi
--    ça n'a rien donné — ce qui vaut d'être gardé même sans la fiche.
ALTER TABLE `ScraperRun` ADD COLUMN `eventId` INTEGER NULL;
ALTER TABLE `ScraperRun`
  ADD CONSTRAINT `ScraperRun_eventId_fkey`
  FOREIGN KEY (`eventId`) REFERENCES `Event`(`id`)
  ON DELETE SET NULL ON UPDATE CASCADE;
CREATE INDEX `ScraperRun_eventId_idx` ON `ScraperRun`(`eventId`);
