-- Un verdict de pagination au niveau de la page, parce que les étiquettes sur
-- les liens ne suffisent pas — et parfois ne peuvent pas exister.
--
-- La console affichait « l'étage 3 suivrait telle URL, qu'aucun lien de la page
-- n'est étiqueté pagination — vérifiez que c'est bien la page suivante », et ne
-- laissait aucune façon de répondre. Deux raisons, dont une rédhibitoire.
--
-- `next_page()` lit le `rel="next"` des `<a>` **et** des `<link>` du `<head>`.
-- Quand l'URL vient d'un `<link>`, ce n'est pas un lien de la page : elle
-- n'apparaît dans aucune ligne, et l'étiqueter était donc impossible. La
-- console demandait quelque chose qui n'existait pas.
--
-- Et même sur un `<a>`, rien ne permettait de dire « vérifié, ce n'est pas la
-- suite » : le bandeau restait rouge, indéfiniment, sans que l'humain puisse
-- clore la question.
--
-- D'où le même principe que pour les liens : la brique propose, l'humain
-- tranche. Trois valeurs, parce que savoir qu'elle s'est trompée ne dit pas si
-- elle a raté une suite ou couru après une fausse — et les deux ne se réparent
-- pas de la même façon.
ALTER TABLE `EvalAgendaPage`
  ADD COLUMN `nextVerdict` ENUM('CORRECT', 'MANQUEE', 'FAUSSE') NULL;

-- L'adresse de la vraie page suivante, quand l'humain la connaît. Savoir que
-- l'étage 3 s'est trompé ne dit pas ce qu'il aurait dû trouver ; une poignée de
-- ces adresses dit tout de suite si `next_page()` doit apprendre à lire une
-- pagination numérotée.
ALTER TABLE `EvalAgendaPage`
  ADD COLUMN `nextExpected` VARCHAR(500) NOT NULL DEFAULT '';
