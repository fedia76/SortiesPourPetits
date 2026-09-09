-- Peupler le banc depuis ce que le pipeline a déjà fait.
--
-- Deux paniers, et l'équilibre entre eux est LA question de ce banc :
--
--   * APPROUVEE — le pipeline en a tiré une sortie qu'un modérateur a
--     approuvée. Approuver, sur ce site, veut dire qu'un humain a vérifié
--     chaque champ : la fiche est donc une vérité de référence pour l'étage 6,
--     déjà payée, y compris sur `setting` que nul instrument ne sait atteindre ;
--   * ABANDONNEE — l'étage 5 a écarté la page (vide, illisible, injoignable).
--     Personne n'a jamais vérifié si l'abandon était justifié.
--
-- Ne prendre que le premier panier mesurerait la brique sur ses propres
-- succès : une page dont le texte était amputé n'est jamais devenue une sortie
-- et ne peut donc pas s'y trouver. On lirait 96 % de textes corrects, et ça ne
-- voudrait rien dire — c'est le rappel à 100 % de l'étage 3 sous un autre
-- déguisement.
ALTER TABLE `EvalReading`
  ADD COLUMN `origin` ENUM('MANUEL', 'APPROUVEE', 'ABANDONNEE') NOT NULL DEFAULT 'MANUEL',
  -- La sortie approuvée tirée de cette page. ON DELETE SET NULL : effacer une
  -- sortie ne doit pas effacer la mesure faite dessus — seulement sa référence.
  ADD COLUMN `eventId` INTEGER NULL,
  -- Quand le pipeline avait lu cette page. La fiche décrit la page de ce
  -- jour-là, le banc la relit aujourd'hui, et aucun HTML d'époque n'est
  -- conservé : plus l'écart est grand, moins un désaccord accuse le modèle.
  ADD COLUMN `readAt` DATETIME(3) NULL,
  -- Ce que le run avait décidé, et pourquoi. C'est la précoche du panier des
  -- abandons : la brique a dit non, et personne ne l'a jamais vérifié.
  ADD COLUMN `runDecision` VARCHAR(40) NOT NULL DEFAULT '',
  ADD COLUMN `runReason` TEXT NOT NULL;

CREATE INDEX `EvalReading_origin_idx` ON `EvalReading`(`origin`);
CREATE INDEX `EvalReading_eventId_idx` ON `EvalReading`(`eventId`);

ALTER TABLE `EvalReading`
  ADD CONSTRAINT `EvalReading_eventId_fkey`
  FOREIGN KEY (`eventId`) REFERENCES `Event`(`id`)
  ON DELETE SET NULL ON UPDATE CASCADE;

-- La fiche approuvée propose un verdict par champ ; elle n'en écrit aucun. Un
-- verdict qui s'inscrirait tout seul redeviendrait indiscernable de « personne
-- n'a regardé », ce que ce banc existe pour éviter. D'où deux booléens qui
-- disent seulement si la comparaison a eu lieu — et pourquoi elle a été
-- suspendue quand le titre approuvé ne se retrouve plus dans le texte : la
-- page a changé depuis le run, et les propositions accuseraient le modèle d'un
-- changement du site.
ALTER TABLE `EvalExtraction`
  ADD COLUMN `hasReference` BOOLEAN NOT NULL DEFAULT false,
  ADD COLUMN `pageMoved` BOOLEAN NOT NULL DEFAULT false;
