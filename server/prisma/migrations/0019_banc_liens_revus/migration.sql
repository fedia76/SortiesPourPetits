-- Distinguer ce qu'un humain a tranché de ce que la brique a deviné.
--
-- L'import pose déjà un verdict sur chaque lien : la précoche. C'est ce qui
-- rend la relecture rapide, et c'était un piège — rien ne distinguait « la
-- machine a deviné *autre* » de « un humain a confirmé *autre* ».
--
-- Conséquence, constatée sur un vrai agenda : on pouvait valider en n'ayant
-- relu que les soixante-trois liens retenus, et le rappel affichait 100 %. Non
-- pas parce que le dépouillement n'avait rien raté, mais parce que personne
-- n'avait regardé les soixante-seize autres. Le dénominateur du rappel — les
-- liens qu'un humain appelle « sortie » — ne peut pas être juste si une partie
-- des liens n'a jamais été lue.
--
-- Le compteur qui devait dire cela existait, et il était mort : il comptait les
-- verdicts non nuls, or ils le sont tous depuis l'import. Il valait donc
-- toujours le total, et n'était même pas affiché.
ALTER TABLE `EvalLink` ADD COLUMN `reviewed` BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE `EvalLink` ADD COLUMN `reviewedAt` DATETIME(3) NULL;
CREATE INDEX `EvalLink_reviewed_idx` ON `EvalLink`(`reviewed`);
