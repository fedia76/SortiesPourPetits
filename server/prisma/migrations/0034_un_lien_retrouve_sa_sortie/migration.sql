-- Un lien « une sortie » retrouve la sortie qui porte son adresse.
--
-- ## Ce qui n'allait pas
--
-- Le rattachement d'un lien d'agenda à la sortie vers laquelle il mène ne se
-- faisait qu'au moment d'**étiqueter le lien** : on cherchait alors la sortie
-- portant la même adresse, et s'il n'y en avait pas encore, le lien restait
-- orphelin. Rien ne repassait quand la sortie arrivait ensuite.
--
-- Or les deux entrent au corpus par deux boutons différents, et rien n'imposait
-- leur ordre. « Liens d'agenda déjà tranchés » avant « Sorties publiées », et
-- toutes les étiquettes de lien de ce passage-là restaient sans sortie —
-- définitivement.
--
-- Conséquence, invisible dans les chiffres parce qu'elle ressemble à un corpus
-- incomplet : l'étage 4 comptait chacun de ces liens *indécidable*, son rappel
-- n'existait pas (0 trouvée, 0 manquée), et la console répondait « la sortie
-- n'existe pas au corpus » en la montrant, décrite, dans l'onglet d'à côté.
--
-- ## Ce que fait cette reprise
--
-- L'appariement se fait sur l'**adresse**, et c'est un fait, pas un jugement :
-- la même adresse est la même page. Rien n'est écrasé — seuls les liens sans
-- sortie sont touchés. Un rattachement posé à la main vers une sortie d'adresse
-- différente (échange de langue, redirection) reste donc intact.
--
-- Le code ne dépend plus de cette reprise : `rattacherLiens` est appelé à
-- chaque création de sortie. Celle-ci répare ce qui a déjà été saisi.

UPDATE `EvalLink` l
JOIN `EvalSortie` s ON s.`url` = l.`url`
SET l.`sortieId` = s.`id`
WHERE l.`verdict` = 'SORTIE' AND l.`sortieId` IS NULL;
