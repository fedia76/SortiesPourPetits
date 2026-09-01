-- Ce que le pipeline savait faire sans que la console sache le demander.
--
-- Quatre chantiers successifs ont ajouté des réglages au scraper — le moteur
-- de recherche, la reconnaissance des pages, les requêtes figées, la
-- pagination suivie — et tous n'étaient atteignables que par un fichier YAML,
-- c'est-à-dire par personne depuis l'interface. Cette migration ouvre les
-- portes correspondantes.
--
-- Tous les défauts reproduisent exactement le comportement d'avant : une
-- configuration existante ne change pas d'un iota tant qu'on n'y touche pas.
ALTER TABLE `ScraperConfig`
  -- Qui lance les recherches. « anthropic » utilise l'outil serveur du modèle ;
  -- « serper » interroge Google, pour un dixième du prix et sans un jeton
  -- d'entrée — le modèle reste derrière pour tout le reste.
  ADD COLUMN `provider` VARCHAR(191) NOT NULL DEFAULT 'anthropic',
  -- Le modèle qui tranche la nature d'une page quand aucun signal certain ne
  -- la donne. Vide : on ne demande à personne, la page part en agenda.
  ADD COLUMN `classifyModel` VARCHAR(191) NOT NULL DEFAULT 'claude-haiku-4-5',
  -- Pages suivantes d'un même agenda, suivies tant que la moisson est maigre.
  ADD COLUMN `maxNextPages` INT NOT NULL DEFAULT 2,
  -- Requêtes web imposées, une par ligne. Vide : le modèle les formule, et
  -- elles varient d'un run à l'autre. Les figer rend deux runs comparables.
  ADD COLUMN `queries` TEXT NULL,
  ADD COLUMN `queriesPrompt` TEXT NULL,
  ADD COLUMN `classifyPrompt` TEXT NULL;
