-- Deux modes de recherche, jamais mélangés.
--
-- « recherche » est le mode historique : le modèle lance des recherches web,
-- on dépouille les agendas qu'elles remontent. C'est le défaut, donc toutes
-- les configurations existantes gardent exactement le chemin qu'elles avaient.
--
-- « site » part d'adresses connues — le site d'un festival, la saison d'un
-- théâtre — et ne lance aucune recherche. `seedUrls` porte ces adresses, une
-- par ligne.
ALTER TABLE `ScraperConfig`
  ADD COLUMN `mode` VARCHAR(191) NOT NULL DEFAULT 'recherche',
  ADD COLUMN `seedUrls` TEXT NOT NULL,
  ADD COLUMN `extractionMultiPrompt` TEXT NULL;
