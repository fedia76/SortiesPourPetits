-- Un travail du banc **donne de ses nouvelles**, et le site sait donc dire la
-- différence entre lent et mort.
--
-- ## Ce qui manquait
--
-- Un run et une chasse passaient en `RUNNING` à la réclamation et n'en
-- sortaient qu'à la clôture. Si le worker mourait entre les deux — service
-- arrêté, machine redémarrée, processus tué —, la clôture n'arrivait jamais
-- et la ligne restait « en cours » **pour toujours**. Rien, côté site, ne
-- pouvait la reprendre : aucune colonne ne disait quand le worker s'était
-- manifesté la dernière fois, donc rien ne distinguait un étage 6 qui met
-- deux heures sur deux cents sorties d'un worker disparu depuis midi.
--
-- La console affichait « En cours » dans les deux cas, et la seule issue
-- était une clôture à la main en base.
--
-- ## Pourquoi une colonne, et pas un délai sur `startedAt`
--
-- Parce qu'un travail du banc n'a pas de durée prévisible : elle dépend du
-- nombre d'entrées du corpus, qui grandit, et de la lenteur du modèle. Tout
-- délai fixé sur `startedAt` serait donc soit trop court — il tuerait un run
-- honnête —, soit assez long pour ne plus rien reprendre.
--
-- Ce qu'on peut borner, en revanche, c'est l'écart entre **deux entrées** :
-- au pire, le temps d'un appel de modèle et de ses reprises. D'où un
-- battement, comparé à cet écart-là et non à la durée totale.
--
-- ## Ce que le battement ne coûte pas
--
-- Pas une ligne de worker. Le battement est l'appel qu'il fait déjà pour
-- demander l'entrée suivante (`POST /runs/:id/next-item`) ou pour rendre un
-- paquet de candidates (`POST /hunts/:id/pages`) : le site l'horodate en
-- passant. Un worker ne peut donc pas mentir sur sa vitalité en oubliant de
-- la déclarer — c'est son travail même qui la déclare.

-- AlterTable
ALTER TABLE `EvalRun` ADD COLUMN `heartbeatAt` DATETIME(3) NULL;

-- AlterTable
ALTER TABLE `EvalHunt` ADD COLUMN `heartbeatAt` DATETIME(3) NULL;
