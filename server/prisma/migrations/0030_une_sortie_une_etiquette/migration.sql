-- Une sortie, une étiquette. Le mot « fiche » disparaît du banc.
--
-- ## Ce qui n'allait pas
--
-- Ce qu'un humain affirme d'une sortie était éparpillé à trois endroits :
--
--   * trois colonnes sur `EvalSortie` pour l'étage 5 (image, dates JSON-LD,
--     fragments du texte) ;
--   * six colonnes sur `EvalSortie` pour l'étage 4 (dates, code postal, âges) ;
--   * une table `EvalFiche` pour l'étage 6, qui redécrivait les **mêmes** dates
--     et les **mêmes** âges une seconde fois.
--
-- Et `EvalFiche` n'était qu'une colonne avec une table autour : en dehors de
-- son étiquette, elle ne portait qu'un auteur et une date, en relation 1:1.
-- Elle datait d'avant que l'objet « sortie » n'existe, quand le corpus ne
-- connaissait que des « pages de lecture » — l'étage 6 n'avait alors nulle part
-- où loger le titre, le tarif et le lieu.
--
-- Conséquence pour qui utilise la console : deux compteurs pour un seul objet,
-- deux boutons de moisson pour un seul geste, et le mot « fiche » qui désigne
-- tantôt une sortie publiée, tantôt une étiquette du banc.
--
-- ## Ce qui change
--
-- `EvalSortie` porte la **page** — adresse, HTML gelé, capture, provenance —
-- et **une seule étiquette** : `expected`, à la forme même que la brique rend.
-- Chaque étage y lit son sous-ensemble et ignore le reste.
--
-- `audience` reste en colonne : c'est la seule affirmation du banc qu'aucune
-- brique ne rend, elle n'a donc pas sa place dans un JSON qui décalque la
-- fiche.
--
-- ## Les étiquettes existantes
--
-- Elles sont reprises telles quelles — aucune conversion, aucune relecture de
-- prose. Les trois étiquettes de lecture rejoignent le JSON sous leur nom, et
-- le contenu d'`EvalFiche` est fusionné dedans.

-- ── 1. l'étiquette unique ────────────────────────────────────────────────
ALTER TABLE `EvalSortie`
  ADD COLUMN `expected`       TEXT        NOT NULL,
  ADD COLUMN `origins`        TEXT        NOT NULL,
  ADD COLUMN `expectedLegacy` TEXT        NULL,
  ADD COLUMN `labelledAt`     DATETIME(3) NULL,
  ADD COLUMN `labelledById`   INT         NULL;

ALTER TABLE `EvalSortie`
  ADD CONSTRAINT `EvalSortie_labelledById_fkey`
  FOREIGN KEY (`labelledById`) REFERENCES `User`(`id`) ON DELETE SET NULL;

-- ── 2. ce que la fiche disait rejoint la sortie ──────────────────────────
UPDATE `EvalSortie` s
  JOIN `EvalFiche` f ON f.`sortieId` = s.`id`
SET s.`expected`       = f.`expected`,
    s.`origins`        = f.`origins`,
    s.`expectedLegacy` = f.`expectedLegacy`,
    s.`labelledAt`     = f.`labelledAt`,
    s.`labelledById`   = f.`createdById`;

-- ── 3. les trois étiquettes de lecture rejoignent le même JSON ───────────
--
-- Sous leur propre nom : ce sont des faits sur la page au même titre que le
-- tarif ou le lieu, et `readScore` les y lira. `JSON_SET` respecte les trois
-- états — une colonne nulle n'ajoute pas de clé, donc « personne n'a regardé »
-- reste « personne n'a regardé ».
UPDATE `EvalSortie`
SET `expected` = JSON_SET(
      IF(`expected` = '' OR `expected` IS NULL, '{}', `expected`),
      '$.image', `expectedImage`
    )
WHERE `expectedImage` IS NOT NULL;

--
-- Les deux suivantes portent des tableaux. `CAST(… AS JSON)` est un MySQL-isme
-- que MariaDB ne connaît pas — pour elle, JSON est un alias de LONGTEXT. On
-- passe donc par `JSON_MERGE_PATCH`, qui accepte un document construit à la
-- main, et on se garde d'un contenu illisible avec `JSON_VALID` : une
-- étiquette qu'on ne sait pas relire reste absente, ce qui veut dire
-- « personne n'a regardé » — mieux qu'une valeur inventée.
UPDATE `EvalSortie`
SET `expected` = JSON_MERGE_PATCH(
      IF(`expected` = '' OR `expected` IS NULL, '{}', `expected`),
      CONCAT('{"declaredDates":', `expectedDates`, '}')
    )
WHERE `expectedDates` IS NOT NULL AND JSON_VALID(`expectedDates`);

UPDATE `EvalSortie`
SET `expected` = JSON_MERGE_PATCH(
      IF(`expected` = '' OR `expected` IS NULL, '{}', `expected`),
      CONCAT('{"markers":', `expectedMarkers`, '}')
    )
WHERE `expectedMarkers` IS NOT NULL AND JSON_VALID(`expectedMarkers`);

-- Les lignes jamais étiquetées gardent un JSON vide plutôt qu'une chaîne vide.
UPDATE `EvalSortie` SET `expected` = '{}' WHERE `expected` = '' OR `expected` IS NULL;
UPDATE `EvalSortie` SET `origins`  = '{}' WHERE `origins`  = '' OR `origins`  IS NULL;

-- ── 4. ce qui faisait doublon s'en va ────────────────────────────────────
ALTER TABLE `EvalSortie`
  DROP COLUMN `expectedImage`,
  DROP COLUMN `expectedDates`,
  DROP COLUMN `expectedMarkers`,
  DROP COLUMN `dateStart`,
  DROP COLUMN `dateEnd`,
  DROP COLUMN `postalCode`,
  DROP COLUMN `ageMin`,
  DROP COLUMN `ageMax`;

DROP TABLE `EvalFiche`;
