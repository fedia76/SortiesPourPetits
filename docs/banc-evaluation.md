# Le banc d'évaluation

Mesurer ce que chaque brique du scraper rend vraiment, plutôt que d'espérer
qu'elle rende ce qu'il faut.

Ce document est la **référence du banc**, tenue à jour avec le code — à la
différence des pages HTML voisines, qui sont des analyses datées. Le pipeline
lui-même est décrit dans [`scraper/README.md`](../scraper/README.md).

| | Où |
|---|---|
| Console | `/admin/evaluation` (administrateurs) |
| Routes | [`server/src/routes/eval.ts`](../server/src/routes/eval.ts) |
| Mesure | [`server/src/lib/evalMetrics.ts`](../server/src/lib/evalMetrics.ts) — pur, testé dans [`server/tests/`](../server/tests/evalMetrics.test.ts) |
| Briques rejouées | [`scraper/sortiesbot/evaluation.py`](../scraper/sortiesbot/evaluation.py) |
| Files du worker | [`scraper/sortiesbot/worker.py`](../scraper/sortiesbot/worker.py) |

## Pourquoi un banc

La modération donne gratuitement la **précision** : parmi ce que le scraper a
proposé, ce qu'un humain a validé. Elle ne dira jamais le **rappel** — ce que le
pipeline a manqué —, et le déséquilibre est structurel :

* une fausse sortie remonte au modérateur, qui la refuse. L'erreur est vue,
  corrigée, étiquetée ;
* une vraie sortie écartée à l'étage 3 ou 4 n'est vue par personne, jamais. Elle
  ne produit même pas une ligne de regret.

La précision a le filet de la modération, le rappel n'en a aucun. C'est la seule
chose qu'aucune observation passive ne peut atteindre, et c'est ce que le banc
existe pour aller chercher.

## Les trois choses, et elles ne se mélangent pas

* le **corpus** — une entrée gelée et ce qu'un humain dit qu'elle contient. Ça
  vit des années, ça ne dépend d'aucun modèle, et c'est la seule chose qui coûte
  cher à produire ;
* un **run** — ce qu'une brique, à sa version du jour, rend sur ce corpus.
  Immuable, empilé, jamais écrasé, et il déclare de quoi il est le run ;
* la **mesure** — la confrontation des deux, calculée à la demande et stockée
  nulle part.

Elles ont vécu dans les mêmes lignes, et ce n'était pas une gêne d'architecture :
rejouer un agenda supprimait ses pages, donc en cascade les verdicts humains
qu'elles portaient. **Mesurer détruisait la mesure**, et « est-ce que ça
s'améliore ? » — la seule question pour laquelle un banc existe — restait sans
réponse possible.

D'où deux conséquences qui surprennent avant d'être comprises :

* **il n'y a pas de recapture.** Elle réécrirait l'objet que les étiquettes
  décrivent. Pour repartir d'une page fraîche, on crée une nouvelle entrée, et
  l'ancienne garde ses étiquettes et son histoire ;
* **une mesure n'est jamais stockée.** Un run de mars se re-mesure contre le
  corpus d'aujourd'hui, qui a grandi depuis. C'est voulu : c'est le corpus qui
  fait autorité, pas la photographie qu'on en avait prise.

## L'étiquette a trois états, et il en faut trois

Partout dans le corpus, pour chaque champ :

| État | Ce qu'il dit |
|---|---|
| clé **absente** | personne n'a regardé. Rien à conclure, et surtout pas que la brique a eu tort |
| clé présente, valeur **vide** | la page n'en dit rien. C'est une étiquette de plein droit |
| une **valeur** | la voici |

Sans le deuxième état, « la page n'annonce pas de tarif » et « personne n'a
vérifié le tarif » seraient le même silence — et une valeur **inventée**
deviendrait invisible. C'est la règle dont tout le reste découle.

Et c'est pourquoi une étiquette dit ce que la page **contient** (« la page
annonce 8 € ») et non si une brique a eu raison (« le tarif rendu est juste ») :
la première vaut pour toujours, la seconde périmait au premier changement de
prompt. Les quatre verdicts n'ont pas disparu — ils sont devenus des conclusions
au lieu d'être des données.

## Ce que le corpus contient

Quatre groupes, un par question posée.

| Groupe | Table | Ce qu'un humain y affirme | Étages mesurés |
|---|---|---|---|
| **Natures** | `EvalNature` | ce qu'une page **est** : agenda, sortie, programme, autre | 2 — *pas encore* |
| **Agendas** | `EvalAgenda`, `EvalAgendaPage` | les pages gelées d'un agenda, et l'adresse de la vraie page suivante | 3 |
| **Liens** | `EvalLink` | ce que chaque lien d'une page **est**, et vers quelle sortie il mène | 3 et 4 |
| **Sorties** | `EvalSortie` | ce qu'une page de fiche **contient**, champ par champ | 4, 5 et 6 |

**Le groupe des natures n'est pas encore mesuré**, et il faut le dire haut :
`EvalStage` ne connaît que `HARVEST`, `SELECT`, `READ` et `EXTRACT`. On peut donc
mettre une page à ce corpus, l'étiqueter et la geler — mais aucun run ne peut la
rejouer, et aucun chiffre n'en sort. Voir « [Ce qui reste
limité](#ce-qui-reste-limité) ».

Une **sortie n'a qu'une étiquette** (`EvalSortie.expected`), à la forme même que
la brique rend, augmentée de ce que le banc seul affirme. Chaque étage y lit son
sous-ensemble et ignore le reste : l'étage 4 lit la date, le lieu et le public,
l'étage 5 l'illustration et les dates déclarées, l'étage 6 les douze aspects de
la fiche. Les avoir éparpillées à trois endroits avait fini par faire décrire
deux fois les mêmes dates, sans que rien ne joigne les deux descriptions.

Deux affirmations restent hors de ce JSON, et pour la même raison — **aucune
brique ne les rend** :

* `audience` — « spectacle jeune public », quand la page dit le public en mots
  plutôt qu'en tranche d'âge ;
* `nextExpected` sur une page d'agenda — l'adresse de la vraie page suivante.

### Capturer n'est pas mesurer

Une entrée est **capturée** une fois : on télécharge, on gèle le HTML gzippé sur
le disque du serveur, on n'y revient plus. Un run rejoue ensuite sur ce HTML,
hors ligne, autant de fois qu'on veut — de sorte qu'un écart entre deux runs ne
peut venir que du **code**, jamais du site.

La capture ne relève rien : ni liens, ni page suivante. Ceux-là viennent d'une
brique, donc d'un run. Les faire entrer dans la capture remettrait dans le corpus
ce que la séparation vient d'en sortir.

Une page injoignable ou démesurée est rapportée **sans** son archive : la mesure
est le travail, l'archive est le confort du rejeu, et on ne perd pas la première
pour avoir manqué la seconde.

## Ce qu'un run déclare

Sans ça, un point de la courbe ne s'attribue à rien — et c'est irrattrapable
après coup : un run joué ne dira jamais ce qu'il était.

| Champ | Quand il est écrit |
|---|---|
| `codeRef` | à la réclamation — la révision du dépôt qui tourne |
| `settings` | au **lancement**, depuis la console, en dates absolues |
| `model`, `promptHash` | à la **clôture** |

Le partage n'est pas arbitraire. La **recherche** (`settings`) est fixée au
lancement parce qu'elle sert deux fois — elle part dans le prompt du tri, et elle
sert à juger ce qu'il a rendu : venant de la même ligne en base, les deux ne
peuvent plus se contredire. Et elle est en dates **absolues**, sans quoi un même
run ne mesurerait plus la même chose selon le jour où on le rejoue.

Le **modèle** et l'empreinte du prompt, eux, ne sont connus qu'une fois le run
réclamé : c'est son étage qui dit quel modèle il interroge. Les déclarer à la
réclamation les laissait vides pour toujours, ce qui a été le cas jusqu'à
septembre 2026 — deux runs n'étaient alors ni comparables ni distinguables.
L'empreinte porte sur le **gabarit** du prompt, pas sur le prompt rendu : celui-ci
change à chaque page, et ce qu'on veut savoir est si deux runs ont posé la même
question.

## Ce qui est partagé avec la production, et ce qui ne l'est pas

C'est le point qui commande tout le reste.

**Partagées : les fonctions.** `links_of`, `next_page`, `page_text`,
`json_ld_dates`, `main_image`, `french_version`, `schedule.resolve`,
`provider.select`, `provider.extract` sont importées telles quelles, avec leurs
seuils et leurs plafonds. Les refaire côté site donnerait la vérité d'une
réimplémentation, c'est-à-dire aucune.

**Pas partagée : l'orchestration.** L'étage 3 fait davantage qu'appeler
`links_of` : il journalise, tient les compteurs du run, dédoublonne entre pages,
et s'arrête dès que sa moisson suffit. Le banc a sa propre boucle, délibérément
plus bête, et un nombre de pages fixe. **On mesure la fonction, pas la brique** —
et il faut savoir lire cette phrase à l'envers : ce que l'orchestration décide
n'est pas mesuré (voir « [Ce qui reste limité](#ce-qui-reste-limité) »).

Le module de rejeu n'a pas non plus le droit de « corriger » quoi que ce soit au
passage : il appelle et rapporte. Compléter est le travail de l'humain.

## Comment chaque étage se mesure

### Étage 2 — la reconnaissance : le corpus existe, la mesure non

Ce qu'un humain dit de la page se compare à ce que la cascade de `classify.py` en
rend — **le jour où un run saura la rejouer**. Aujourd'hui le corpus se remplit et
se gèle, et rien ne le lit : il manque une valeur à `EvalStage`, une branche dans
le worker et une fonction de score. Ce qui suit dit donc pourquoi cette mesure
vaut la peine, pas ce qu'elle rend.

L'erreur n'y est **pas symétrique**, et c'est ce qui rend la mesure utile :
prendre une sortie pour un agenda coûte un appel de tri et se rattrape tout seul,
prendre un agenda pour une sortie coûte **tous ses liens**, sans rattrapage.

Le corpus a besoin de contre-exemples — une page d'accueil, un article, une
billetterie — d'où le verdict `AUTRE` et une table à part : `EvalAgenda`
présuppose que la page est un agenda, `EvalSortie` qu'elle est une sortie, et
c'est justement la question qu'on pose.

### Étage 3 — le dépouillement

Chaque lien relevé reçoit l'un de quatre verdicts, parce que trois ne suffisent
pas à décrire ce qu'un agenda contient :

| Verdict | Ce que c'est | Ce que le pipeline en fait |
|---|---|---|
| **sortie** | mène à la fiche d'un événement | ce que l'étage 4 doit garder |
| **pagination** | la page 2, 3… du même agenda | suivie, mais seulement en `rel="next"` |
| **sous-agenda** | une **autre** liste de sorties | **rien** |
| **autre** | navigation, mentions légales, partage | correctement écarté |

`SOUS_AGENDA` est le cas que personne ne comptait, et il est partout : « voir
aussi les sorties en château », « les sorties gratuites ». Ces pages à facettes
portent d'autres sorties sans être la page suivante. Le dépouillement les rend,
le prompt du tri lui dit d'écarter les liens de catégorie, et ce qu'elles portent
n'est jamais atteint. Le banc ne corrige pas ce trou : il le chiffre.

Le croisement donne les deux erreurs :

|  | l'humain dit « sortie » | l'humain dit autre chose |
|---|---|---|
| **retenu** | juste | **bruit** — un appel payant pour rien |
| **écarté** | **sortie perdue** | juste |

« Sortie perdue » est la plus chère, précisément parce qu'elle ne coûte rien :
elle ne consomme aucun jeton, ne produit aucune ligne de journal, et personne ne
la voit jamais.

Deux règles de comptage, et elles ne sont pas des détails :

* un lien retenu que **personne n'a étiqueté** sort du dénominateur de la
  précision au lieu de compter comme du bruit. Le compter accuserait la brique
  d'un trou du corpus ;
* **rien n'est dédoublonné entre pages** : un lien présent sur les pages 1 et 2
  compte deux fois, parce que `links_of` l'a vu deux fois, et parce que c'est
  page par page que la vérité s'établit. C'est aussi ce qui laisse voir le cas le
  plus instructif — la page 2 qui ne rend rien alors que la page 1 va bien.

**La pagination se mesure à part.** Le corpus porte l'adresse de la vraie page
suivante (`nextExpected`, trois états), le run porte ce que `next_page()` a
trouvé, et la comparaison rend *juste*, *suite ratée* ou *fausse suite*. Savoir
que la brique s'est trompée ne dit pas ce qu'elle aurait dû trouver : c'est
l'adresse attendue qui permet de réparer, et une poignée d'entre elles dira tout
de suite si `next_page()` doit apprendre à lire une pagination numérotée.

### Étage 4 — le tri

Le tri ne fait pas un métier mais **trois** : reconnaître une sortie, écarter ce
qui sort de la recherche, et n'en garder qu'un nombre borné. Compter comme
« manquée » toute sortie qu'il n'a pas retenue lui reprochait deux comportements
corrects — un concert pour adultes écarté à raison, une sortie de l'an prochain
hors fenêtre — et faisait baisser son rappel à mesure que la recherche se
précisait.

La **pertinence est donc dérivée**, jamais étiquetée : « pertinente » n'est pas
une propriété du lien, le même atelier étant pertinent pour « musées
Île-de-France » et hors sujet pour « spectacles Seine-Maritime ». On étiquette
des **faits** — la date, le code postal, le public — et la portée du run tranche.

Chaque lien tombe alors dans une case, et une seule :

* **trouvée** — pertinente, et retenue ;
* **manquée** — pertinente, et écartée. La vraie faute ;
* **bruit** — hors recherche, et retenue. L'autre faute, qui coûte une lecture
  payée pour rien ;
* **écartée à raison** — hors recherche, et écartée. Le travail bien fait, qui
  n'apparaissait nulle part ;
* **indécidable** — personne n'a décrit cette sortie. Hors de tout dénominateur,
  et affiché pour qu'on sache ce qu'on ignore.

Trois garde-fous, tous vérifiés par les tests :

1. un lien que le dépouillement n'a **pas soumis** au tri ne compte pas contre le
   tri, qui ne l'a jamais vu — sinon son rappel baisserait chaque fois que
   l'étage 3 s'améliorerait ;
2. une page où le tri a retenu **exactement son plafond** sort du rappel : « écarté
   à tort » et « tronqué » y sont indiscernables, et un rappel calculé dessus
   mesurerait `max_links` plutôt que le modèle. Le nombre de ces pages est
   affiché ;
3. le rappel d'un run ne se calcule donc **pas** sur la somme de ses pages : il
   faut deux comptes, celui qu'on affiche — ce qui s'est passé — et celui du
   rappel, qui ne retient que les pages où le modèle avait les mains libres.

On juge **si l'objectif est atteint**, pas si l'étage avait les moyens de
l'atteindre : un lien au contexte muet qu'il a gardé, et qui s'avère être un
concert pour adultes, compte comme du bruit. Il n'est pas fautif, et la lecture a
quand même été payée pour rien. Un banc qui absout l'étage 4 parce que l'agenda
était avare ne dit plus rien de ce qu'il faut corriger.

### Étage 5 — la lecture

L'étage lit **trois fois** un même HTML — le texte qui part au modèle, les dates
JSON-LD, l'illustration — et en tire une décision : sous `MIN_PAGE_CHARS`, la
page est abandonnée avant le moindre appel payant. Trois lectures, donc trois
mesures : elles se ratent séparément et ne se réparent pas au même endroit.

| Ce que le corpus porte | Ce qu'on en conclut |
|---|---|
| `markers` — quelques fragments que le texte doit contenir | le texte porte-t-il bien la sortie |
| `image` — l'illustration que la page porte vraiment | le tamis des images |
| `declaredDates` — les dates du balisage `schema.org` | la lecture du JSON-LD |

Des fragments plutôt qu'un texte attendu, parce qu'on ne recopie pas une page à
la main : trois fragments bien choisis — la date, l'adresse, une phrase du corps
— disent tout ce qu'on veut savoir. Une clé absente ne se juge pas.

Deux signaux n'attendent personne et sortent à chaque run : le texte **au
plafond** (la fin de la page n'atteindra jamais le modèle) et **sous le seuil**
(la page serait abandonnée — le ratage le plus cher, et le seul que la brique
décide toute seule).

L'**échange de langue** est rejoué avec le reste : c'est lui qui décide *quelle*
page est lue, et l'oublier ferait mesurer une autre page que celle que le pipeline
aurait choisie. C'est le seul endroit du rejeu qui peut demander le réseau, et le
run le consigne (`swapped`).

### Étage 6 — l'extraction

Le premier étage mesuré qui **coûte**, et celui qui produit tout ce dont la fiche
vit : le cadre, l'âge, le tarif, les horaires, le lieu, la catégorie. L'étage 5 ne
rend qu'un texte ; tout le reste est lu dedans par le modèle.

**L'entrée est le texte gelé de l'étage 5, jamais la page.** Retélécharger
mêlerait deux mesures : une fiche sans tarif dirait aussi bien « le modèle ne l'a
pas vu » que « l'étage 5 l'avait déjà emporté avec un `<aside>` ». Le banc de
lecture a mesuré cela séparément, et c'est pour ça qu'il vient avant.

**Champ par champ, jamais fiche par fiche.** Une fiche « fausse » ne dit pas quel
champ a lâché, donc ne dit pas quoi réparer. Douze aspects — les vingt-trois
colonnes du schéma regroupées par *fait*, `free` et `price` ne faisant qu'un seul
tarif — disent « le tarif se rate une fois sur trois », et c'est une ligne de
prompt à réécrire.

Quatre verdicts par aspect, dérivés de la comparaison :

| | la page le dit | la page n'en dit rien |
|---|---|---|
| **renseigné** | JUSTE ou FAUX | **INVENTÉ** |
| **vide** | **MANQUÉ** | JUSTE (vide à raison) |

Plus un cinquième état qui n'est pas un verdict : **inconnu**, quand le corpus ne
porte aucun champ de cet aspect. C'est une dette, pas une faute.

Deux champs se comparent autrement, et les deux corrections datent de septembre
2026 :

* **la description** ne se juge que sur sa **présence**. Deux paraphrases
  différentes de la même page sont toutes les deux justes ; les comparer à la
  lettre comptait FAUX à chaque fiche moissonnée — un aspect sur douze perdu pour
  rien. Le *contenu* d'une description se juge sans référence, par l'ancrage dans
  le texte de la page ;
* **les jours de représentation** se comparent **après le calendrier**. Le site ne
  stocke pas des « dimanches », il stocke des dates : c'est `schedule.resolve`,
  la fonction de production, qui convertit, et le run rend son résultat
  (`resolvedDates`) à côté de la prose du modèle. Comparer les deux directement
  comptait MANQUÉ toute sortie récurrente, pour une conversion qui a lieu deux
  étages plus loin.

**Ce que coûte la mesure** est rendu avec elle : une extraction est un appel, et
taire le prix donnerait l'impression que cette mesure-ci est gratuite comme les
précédentes. C'est aussi pourquoi les catégories du site partent dans le prompt —
le modèle doit y choisir la sienne, et les lui refuser faisait compter faux un
champ qu'on l'empêchait de remplir.

## Peupler le corpus avec ce que la modération a déjà payé

Étiqueter est le seul travail coûteux du banc. Tout ce qui peut venir d'un geste
humain **déjà fait** doit en venir.

| Panier | D'où | Ce qu'il apporte |
|---|---|---|
| **approuvées** | `ScraperRunItem` `submitted` dont la sortie est `APPROVED` | des pages où l'étage 5 a réussi, et la vérité de référence de l'étage 6 |
| **abandonnées** | `decision='invalid'`, motif « page vide ou illisible » | le point aveugle : la brique a dit non, personne n'a jamais vérifié |
| **illisibles** | sorties refusées pour `DESCRIPTION_INUTILISABLE` | le pire des trois : la page a passé le seuil, coûté une extraction, et son texte ne valait rien |
| **liens** | une page devenue une sortie approuvée, trouvée parmi les liens d'un agenda du corpus | l'étiquette `SORTIE` est acquise |
| **fiches** | la fiche approuvée elle-même, champ par champ | l'étiquette de l'étage 6, sans un clic |

**L'équilibre entre les paniers est la question.** Une sortie approuvée est, par
construction, une page dont le texte était lisible : n'en prendre que celles-là
mesurerait la brique sur ses propres succès — on lirait 96 % de textes corrects,
et ça ne voudrait rien dire.

Deux précautions valent d'être connues :

* les pages viennent de `ScraperRunItem.url`, l'adresse **réellement lue**, et
  non de `Event.sourceUrl` que l'étage 7 a pu réécrire vers une page jamais
  ouverte ;
* les erreurs réseau n'entrent dans aucun panier : une page injoignable ce
  jour-là est un fait du web, pas un jugement de la brique.

### La limite de la fiche approuvée, qu'il faut avoir en tête

Approuver, sur ce site, veut dire qu'un modérateur a vérifié chaque champ. C'est
l'hypothèse qui rend ce panier utilisable, et elle est **faible** : dans les
faits, l'essentiel d'une fiche approuvée est ce que le modèle avait écrit et que
personne n'a retapé.

La provenance de chaque champ est donc conservée (`origins`) :

| Provenance | Ce que ça vaut |
|---|---|
| `SAISIE` | un humain a tapé la valeur dans le banc. La plus forte |
| `CORRIGE` | un modérateur a réécrit ce champ avant d'approuver. Une étiquette **indépendante du modèle** |
| `NON_CONTREDIT` | le modèle l'a rendu, le modérateur l'a laissé passer |

La mesure les traite à égalité. Mais un taux calculé surtout sur des
`NON_CONTREDIT` mesure **le modèle contre lui-même**, et il sera flatteur par
construction : **les renseignements sont dans les `CORRIGE`.** C'est le premier
chiffre à regarder, et la raison pour laquelle cette colonne existe — si le taux
de correction s'effondrait un jour sur tous les champs à la fois, l'hypothèse
aurait vieilli, et on ne pourra le voir que si on l'a noté.

## Ce qu'il reste à faire à la main, compté

`GET /api/eval/reste` affiche la dette, en trois listes :

* **jamais regardés** — les liens qu'un run a relevés et que personne n'a
  étiquetés, par page. Tant qu'ils sont là, le rappel de l'étage 3 est une
  illusion ;
* **à créer** — le lien dit « une sortie », mais aucune sortie n'existe au
  corpus ;
* **à décrire** — la sortie existe et n'affirme rien que l'étage 4 sache lire.

Ces comptes ne raccourcissent pas le travail : ils l'**affichent**. Un coût qu'on
découvre au fil de l'eau fait abandonner un banc au bout de trois semaines ; un
coût annoncé se planifie.

## Les files, et l'ordre dans lequel le worker les sert

1. les **recherches** — elles produisent des sorties que des parents attendent ;
2. les **captures** du banc — geler est gratuit, et un run joué sur un corpus
   incomplet mesure ce qu'on a sous la main plutôt que ce qu'on voulait mesurer ;
3. les **runs** du banc — dont deux étages sur quatre appellent le modèle et se
   paient.

Un run est clos **quoi qu'il arrive**, y compris sur un plantage : sans clôture
il resterait « en cours » et le worker n'en prendrait plus d'autre.

## Ce qui reste limité

Un banc qui tait ses angles morts est un banc qui mentira un jour. Ceux-ci sont
connus.

**Le banc de tri ne mesure pas tout à fait l'étage 4 de production.** Il rejoue
le tri **page par page** ; en production, l'étage 3 agrège les liens de plusieurs
pages d'un même agenda avant un **seul** appel. Le modèle du banc reçoit donc une
liste plus courte, et son plafond s'applique à chaque page au lieu de l'agenda
entier. On mesure la fonction sur une entrée qui n'est pas celle qu'elle reçoit —
et c'est le seul étage où c'est le cas. Le détail, et pourquoi ce n'est pas
anodin, sont dans la section suivante.

**`setting` — intérieur ou extérieur — n'a aucun instrument.** Une page ne
l'écrit presque jamais : elle dit « au parc de la Villette », et c'est le lecteur
qui conclut. C'est l'aspect qui coûtera toujours une étiquette humaine, et le
banc l'annonce plutôt que d'imaginer une heuristique qui donnerait l'illusion
d'une mesure.

**Le mode programme n'est pas mesuré.** Le banc d'extraction joue un seul appel,
en page unique. Une page qui porte vingt sorties pose une autre question — non
pas « les champs sont-ils justes ? » mais « le découpage est-il le bon ? » —, qui
est une mesure de segmentation, avec ses propres taux. Ce que le banc mesure
quand même, c'est la **décision** qui y mène : `several` est le premier aspect
jugé.

**Le corpus de l'étage 2 ne se mesure pas encore.** Les pages s'y ajoutent,
s'étiquettent et se gèlent, mais `EvalStage` ne connaît que les quatre autres
étages : aucun run ne peut les rejouer. C'est un corpus qui se paie en travail
humain sans rien rendre, et c'est la première chose à finir — il manque une valeur
d'énuméré, une branche dans le worker et une fonction de score, la plus simple des
cinq puisqu'il s'agit de comparer deux étiquettes.

**Les étages 1, 7 et 8 ne sont pas au banc.** La découverte se juge sur le
rendement des requêtes (page « Statistiques »), l'attribution sur l'entonnoir de
l'onglet « Source » d'une exécution, la publication par les motifs de refus. Ce
sont des observations du pipeline en marche, pas des mesures contre une vérité.

**Un prix perdu compte FAUX et non MANQUÉ.** `free: false` est une valeur, donc
l'aspect « tarif » est renseigné même sans prix. Les deux pèsent pareil dans le
taux ; seul le rangement diffère, et c'est le rangement qu'il faudra revoir si
l'on veut séparer l'oubli de l'erreur.

**Deux choses sont stockées et jamais montrées** : les drapeaux d'instrument
(`EvalExtractResult.aspects` — ancrage, cohérence, accord) et `promptHash`. La
console ne les affiche pas. Ce sont des dettes d'interface, pas de mesure.

**Deux vestiges attendent une migration** : la table `_LegacyEvalExtraction` et
la colonne `EvalSortie.expectedLegacy`. `npm run db:backfill-eval` sait encore
reprendre les étiquettes de la première ; la seconde n'entre dans aucune mesure.

## Pourquoi le banc de tri ne mesure pas la production

C'est le seul endroit du banc où l'entrée d'une brique n'est pas celle qu'elle
reçoit en vrai. Le détail vaut d'être écrit, parce qu'il change l'interprétation
des chiffres de l'étage 4 — et seulement de ceux-là.

### Les deux chemins, côte à côte

En **production**, l'étage 3 ne rend pas les liens d'une page : il rend les liens
d'un **agenda**. Il télécharge la première page, suit `rel="next"` tant qu'il
manque de liens (`max_next_pages`, deux par défaut), **dédoublonne** ce qu'il
trouve, et rend un seul tas. L'étage 4 reçoit ce tas, en **un seul appel**, avec
une consigne : « au plus `max_links` » — huit par défaut.

```
production   page 1 ─┐
             page 2 ─┼─► un tas dédoublonné (jusqu'à 200 liens) ─► 1 appel ─► 8 retenus
             page 3 ─┘
```

Au **banc**, chaque page gelée est une entrée de run indépendante. Le worker
appelle `links_of` sur cette page, puis `provider.select` sur ce seul résultat.

```
banc         page 1 ─► ses liens ─► 1 appel ─► 8 retenus
             page 2 ─► ses liens ─► 1 appel ─► 8 retenus
             page 3 ─► ses liens ─► 1 appel ─► 8 retenus
```

### Ce que cela change, concrètement

**Le plafond ne porte pas sur la même chose.** En production, huit liens pour
l'agenda entier ; au banc, huit liens **par page**, soit vingt-quatre pour le
même agenda de trois pages. Le banc est donc plus généreux que la production, et
son rappel est optimiste d'autant.

**La compétition entre pages disparaît, et c'est le plus gênant.** En production,
une sortie de la page 2 concourt pour les mêmes huit places que celles de la page
1. Elle est très souvent écartée non parce que le modèle l'a mal jugée, mais
parce que huit liens la précédaient. C'est un effet réel, il coûte des sorties, et
le banc ne peut pas le voir : chaque page y dispose de son propre quota. Autrement
dit le banc mesure le **jugement** du modèle, jamais l'**arbitrage** que le
plafond lui impose — alors que c'est l'arbitrage qui fait perdre des sorties en
vrai.

**La liste soumise n'a pas la même longueur.** Trente liens d'une page, ou cent
cinquante venus de trois pages : ce n'est pas la même tâche pour un modèle. Une
liste longue dilue l'attention et change la façon dont la consigne « au plus huit »
est appliquée. Un taux mesuré sur trente ne se transporte pas à cent cinquante.

**Le dédoublonnage manque.** La production dédoublonne avant l'appel, le banc
non : un lien présent sur deux pages est soumis deux fois au banc, une seule fois
en production. Pour l'étage 3 c'est voulu — on mesure `links_of`, qui l'a bien vu
deux fois. Pour l'étage 4, ça ajoute un écart de plus.

**La pagination suivie n'est pas la même.** En production, le nombre de pages
dépend de la moisson (`len(links) < 200`) ; au banc, il est fixé à la capture
(`EvalAgenda.pages`, un par défaut). Un agenda capturé sur une page mesure donc le
tri d'une page, là où la production en aurait agrégé deux ou trois.

### Ce que les chiffres valent quand même

Ils valent pleinement pour ce qu'ils disent : **ce modèle, sur cette liste, avec
cette consigne, reconnaît-il une sortie ?** C'est la question du prompt de tri, et
c'est celle qu'on veut poser quand on le réécrit. Un `SOUS_AGENDA` retenu, un
concert pour adultes gardé, un titre de fiche pris pour de la navigation : tout
cela se mesure juste.

Ils ne valent pas comme prédiction de ce que le pipeline ramènera. Le rappel du
banc est une **borne haute** du rappel réel sur un agenda paginé.

Et ils valent exactement pour un cas : un agenda **d'une seule page**, dont la
production n'aurait suivi aucune suite. Là, les deux chemins coïncident.

### Comment on le corrigerait

En donnant au run de tri la même entrée qu'à la production : réclamer un
**agenda** plutôt qu'une page, rejouer la boucle de l'étage 3 sur ses pages
**gelées** — sans réseau, l'archive est déjà là — puis un seul appel sur le tas
dédoublonné. Les résultats resteraient rattachés à la page d'où chaque lien
provient (`EvalLinkResult.pageId`), donc la mesure par page survivrait, et le
plafond redeviendrait celui de l'agenda.

Ce n'est pas fait. Le coût est une modification du protocole worker ↔ site
(`/runs/:id/next-item` rendrait plusieurs pages d'un coup), et la contrepartie est
que le tri deviendrait alors le seul étage dont le banc partage aussi
l'orchestration — ce qui est justement ce qu'on a refusé partout ailleurs. Le
partage « on mesure la fonction, pas la brique » tient pour `links_of`, qui est
une fonction pure d'une page. Il ne tient pas pour le tri, dont l'entrée est
fabriquée par l'orchestration de l'étage précédent.

## Ce qu'un banc demande pour servir

Une itération complète, et une seule, suffit à savoir s'il sert :

1. lancer un run sur un étage, avec un `label` qui dit ce qu'on essaie ;
2. lire **les `CORRIGE` d'abord**, et le champ qui se rate le plus ;
3. changer une ligne de prompt, ou un seuil ;
4. relancer, et comparer les deux points.

Tant que cette boucle n'a pas tourné une fois, le banc est un outil qu'on
construit, pas un outil qui mesure.
