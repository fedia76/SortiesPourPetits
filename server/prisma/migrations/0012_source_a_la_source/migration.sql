-- Deux URLs plutôt qu'une : le lien qu'on montre, et celui d'où ça vient.
--
-- Une recherche automatique remonte surtout des agrégateurs — kidiklik,
-- citizenkid, parismômes, familyinparis. Ce sont de bons agendas, et c'est
-- pour ça qu'ils sortent en tête ; mais un atelier du musée Rodin est une
-- information du musée Rodin, et c'est sa page qu'un parent veut ouvrir.
--
-- `sourceUrl` ne change pas de rôle : il reste le meilleur lien connu, celui
-- que la fiche affiche. C'est ce qui permet à cette migration de n'invalider
-- aucune ligne existante — une sortie déjà en base garde un lien qui reste
-- vrai, simplement moins bon que ce qu'on saura faire désormais.
ALTER TABLE `Event`
  -- La page où la sortie a été repérée, quand ce n'est pas celle qu'on montre.
  -- NULL est le cas normal : proposition de visiteur, ou page déjà à la source.
  ADD COLUMN `foundOnUrl` VARCHAR(191) NULL,
  -- Ce qui a désigné `sourceUrl` : json_ld, venue_domain, page_link, search
  -- (l'étage attribution, du plus sûr au moins sûr) ou manuel. Le modérateur
  -- voit d'où sort le lien, donc quelle confiance lui accorder.
  ADD COLUMN `sourceUrlSignal` VARCHAR(191) NULL;

-- Les deux réglages de l'étage attribution, côté console. Leurs défauts
-- reproduisent le comportement du scraper laissé à lui-même : la liste
-- d'agrégateurs intégrée, et la recherche de repli active.
ALTER TABLE `ScraperConfig`
  ADD COLUMN `aggregatorDomains` TEXT NOT NULL,
  ADD COLUMN `sourceSearch` BOOLEAN NOT NULL DEFAULT true;
