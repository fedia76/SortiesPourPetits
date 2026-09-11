-- Ce que la sortie est, pour que la pertinence se dérive au lieu de s'étiqueter.
--
-- Les quatre verdicts — sortie, pagination, sous-agenda, autre — répondent à
-- « qu'est-ce que ce lien ? », et c'est la question de l'étage 3. Ils ne
-- répondent pas à celle de l'étage 4, qui n'en fait pas un mais trois :
-- reconnaître une sortie, écarter ce qui sort de la recherche, et n'en garder
-- qu'un nombre borné.
--
-- La mesure comptait donc comme « manquée » toute sortie que le tri n'avait
-- pas retenue — y compris un concert pour adultes écarté à raison, ou une
-- sortie de l'an prochain hors fenêtre. Elle ne mesurait pas seulement mal :
-- elle faisait baisser le rappel du tri à mesure que la recherche se précisait.
--
-- ## Pourquoi pas une étiquette « pertinente »
--
-- Parce que la pertinence n'est pas une propriété du lien : le même atelier
-- est pertinent pour « musées Île-de-France » et hors sujet pour « spectacles
-- Seine-Maritime ». L'étiquette serait fausse au premier changement de
-- configuration — la péremption même que la séparation corpus / run vient de
-- supprimer.
--
-- On étiquette donc des **faits** — la date, le lieu, le public, tels que le
-- contexte du lien les montre — et « pertinente pour ce run » se calcule en
-- les confrontant aux réglages que le run enregistre déjà.
--
-- Trois états chacun : NULL (personne n'a regardé), vide (l'agenda n'affiche
-- rien, et c'est une étiquette), une valeur. Un indice vide ne peut jamais
-- écarter une sortie : il la rend indécidable, et l'indécidable ne compte
-- dans aucun dénominateur.

ALTER TABLE `EvalLink`
  ADD COLUMN `dateHint`  VARCHAR(40)  NULL,
  ADD COLUMN `placeHint` VARCHAR(120) NULL,
  ADD COLUMN `audience`  ENUM('ENFANTS', 'ADULTES', 'INDETERMINE') NULL;
