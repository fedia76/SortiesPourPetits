-- Un run de production verse ses agendas au corpus du banc, à sa clôture.
--
-- ## Ce qui n'allait pas
--
-- Le banc mesure l'étage 3 sur des pages **gelées**, et rien ne les gelait au
-- moment utile. Un agenda entrait au corpus le jour où un humain pensait à
-- l'ajouter — c'est-à-dire des mois après le run qui l'avait rendu
-- intéressant, sur une page d'où les sorties approuvées entre-temps avaient
-- disparu. D'où des agendas à « 0 / 63 liens étiquetés » que rien ne pouvait
-- amorcer : la reprise depuis la modération ne trouve que les adresses encore
-- présentes sur la page gelée.
--
-- ## Ce que ça change
--
-- `ScraperConfig.freezeAgendas` — la clôture d'un run enrôle les agendas qu'il
-- a dépouillés, et la file de capture gèle leur page dans la foulée. Par
-- défaut vrai : les recherches existantes se mettent à nourrir le banc, ce qui
-- est le comportement qu'on regrettait de ne pas avoir eu jusqu'ici.
--
-- **Tous** les agendas du run, pas seulement ceux qui ont donné une sortie :
-- un corpus fait des seules réussites de la brique mesure ses réussites. Le
-- volume est borné par `maxAgendas` (6 par défaut) et par l'unicité de l'URL —
-- les mêmes agendas reviennent d'un run à l'autre et n'entrent qu'une fois.
--
-- `EvalAgenda.createdById` devient nul : un agenda enrôlé n'a pas d'auteur
-- dans la console. C'est déjà ce que fait `EvalLink.labelledById` pour une
-- étiquette venue de la modération, et pour la même raison — inventer un
-- auteur ferait croire que quelqu'un a regardé.
--
-- La clé étrangère reste en `RESTRICT`. La rendre `SET NULL` aurait été le
-- réflexe pour une colonne qui devient nullable, et ç'aurait été une faute
-- ici : nul porte désormais un sens — « enrôlé » —, et une suppression de
-- compte qui vide le champ ferait passer pour enrôlés des agendas saisis à la
-- main. Supprimer un compte qui en porte demande donc toujours de trancher.

ALTER TABLE `ScraperConfig` ADD COLUMN `freezeAgendas` BOOLEAN NOT NULL DEFAULT true;

ALTER TABLE `EvalAgenda` DROP FOREIGN KEY `EvalAgenda_createdById_fkey`;
ALTER TABLE `EvalAgenda` MODIFY `createdById` INTEGER NULL;
ALTER TABLE `EvalAgenda` ADD CONSTRAINT `EvalAgenda_createdById_fkey`
  FOREIGN KEY (`createdById`) REFERENCES `User`(`id`) ON DELETE RESTRICT ON UPDATE CASCADE;
