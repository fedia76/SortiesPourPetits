-- L'étiquette d'une fiche porte des faits, plus de la prose.
--
-- ## Ce qui n'allait pas
--
-- La donnée est structurée aux deux bouts de la chaîne. Le modèle rend
-- `{"ageMin": 3, "ageMax": null}` — c'est dans `EvalExtractResult.fiche`,
-- que le banc stockait déjà en la nommant « la pièce à conviction ». La sortie
-- publiée porte les colonnes `ageMin` et `ageMax`.
--
-- Entre les deux, `evaluation.audit_fiche` met en forme « dès 3 ans » pour
-- l'affichage humain, ce qui est son métier. Et la mesure comparait **cette
-- mise en forme**, en ignorant la fiche structurée qu'elle avait sous la main.
--
-- Conséquences :
--
--   * reprendre une fiche approuvée comme étiquette obligeait à réécrire en
--     TypeScript un format défini en Python — « gratuit », « 8 € », « 10:00 –
--     18:00 » au tiret demi-cadratin. Une convention dupliquée entre deux
--     langages, pour traverser un aplatissement dont personne n'avait besoin ;
--   * un point-virgule déplacé dans `audit_fiche` et tous les tarifs
--     comptaient « faux », sans que rien ne le signale.
--
-- ## Ce qui change
--
-- `expected` a désormais la forme même que la brique rend. La comparaison se
-- fait champ à champ, par genre — un nombre avec un nombre, un booléen avec un
-- booléen, une date sur son jour, de la prose au repli. Les douze aspects
-- restent l'unité de score : `free` et `price` disent un seul fait, et les
-- juger séparément compterait deux fois la même erreur.
--
-- La mise en forme redevient ce qu'elle est : de l'affichage.
--
-- ## Les étiquettes existantes
--
-- On ne relit pas de la prose pour en tirer des faits — c'est exactement ce
-- qu'on arrête de faire. Les anciennes valeurs sont donc déplacées telles
-- quelles dans `expectedLegacy`, qui n'entre dans aucune mesure, et `expected`
-- repart vide : « personne n'a regardé », ce qui est la vérité tant que
-- personne n'a réétiqueté.
--
-- Rien n'est perdu pour autant, et c'est pourquoi ce choix est tenable :
--
--   * les fiches reprises de la modération se remoissonnent d'un clic, et
--     arriveront structurées (`origins` non vide les désigne) ;
--   * les fiches reprises de l'ancien banc se régénèrent avec
--     `npm run db:backfill-eval`, qui lit maintenant `_LegacyEvalExtraction.
--     fiche` — la fiche structurée, qui était là depuis le début.

ALTER TABLE `EvalFiche` ADD COLUMN `expectedLegacy` TEXT NULL;

UPDATE `EvalFiche`
SET `expectedLegacy` = `expected`,
    `expected` = '{}'
WHERE `expected` <> '{}' AND `expected` IS NOT NULL;
