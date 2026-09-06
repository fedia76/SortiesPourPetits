-- Le banc relève tous les liens, la brique précoche, l'humain corrige.
--
-- La première version ne montrait que la moisson, et demandait de retrouver
-- soi-même ce qu'elle avait manqué : lent, et incomplet par construction — on
-- ne trouve que ce qu'on a pensé à chercher. Elle ne pouvait surtout mesurer
-- qu'une seule des deux erreurs. Un lien retenu qui ne mène nulle part coûte un
-- appel payant à l'étage 4, et cette erreur-là restait invisible.
--
-- Désormais chaque lien de la page est relevé, marqué de ce que `links_of` en a
-- fait, et l'humain n'a qu'à corriger. On obtient la précision et le rappel.

-- Ce que `next_page()` a trouvé sur cette page. Comparé aux liens que l'humain
-- étiquette PAGINATION, c'est la mesure de la pagination : un agenda qui
-- numérote ses pages sans `rel="next"` n'est jamais suivi par l'étage 3, et
-- rien ailleurs ne le signale.
ALTER TABLE `EvalAgendaPage` ADD COLUMN `nextUrl` VARCHAR(500) NOT NULL DEFAULT '';

-- La précoche : le verdict de `links_of` lui-même, et le motif de son rejet.
-- Le motif ne décide de rien — il range les rejets dans la console, parce que
-- les ratages se concentrent sous « texte trop court » et « hors domaine ».
ALTER TABLE `EvalLink` ADD COLUMN `harvested` BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE `EvalLink` ADD COLUMN `dropReason` VARCHAR(60) NOT NULL DEFAULT '';
ALTER TABLE `EvalLink` ADD COLUMN `position` INTEGER NOT NULL DEFAULT 0;

-- Ce que l'humain dit que le lien est. Quatre valeurs, parce que trois ne
-- suffisent pas : SOUS_AGENDA est la page à facettes — « voir aussi les
-- sorties en château » — qui porte d'autres sorties sans être la page
-- suivante. Le dépouillement la rend, la sélection l'écarte, et ce qu'elle
-- porte n'est jamais atteint.
ALTER TABLE `EvalLink`
  ADD COLUMN `verdict` ENUM('SORTIE', 'PAGINATION', 'SOUS_AGENDA', 'AUTRE') NULL;
CREATE INDEX `EvalLink_verdict_idx` ON `EvalLink`(`verdict`);

-- `HARVEST` devient `PAGE` : la colonne dit maintenant d'où vient le lien
-- (relevé sur la page, ou tapé à la main), et c'est `harvested` qui dit ce que
-- la brique en a fait. Garder les deux sens sur un même mot rendrait le code
-- illisible. Élargir l'énumération avant de la rétrécir permet de convertir
-- les lignes existantes sans les perdre.
ALTER TABLE `EvalLink`
  MODIFY COLUMN `source` ENUM('HARVEST', 'MANUAL', 'PAGE') NOT NULL DEFAULT 'PAGE';
UPDATE `EvalLink` SET `harvested` = true, `source` = 'PAGE' WHERE `source` = 'HARVEST';
ALTER TABLE `EvalLink`
  MODIFY COLUMN `source` ENUM('PAGE', 'MANUAL') NOT NULL DEFAULT 'PAGE';
