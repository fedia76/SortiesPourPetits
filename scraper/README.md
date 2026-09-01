# Scraper — recherche automatique de sorties

Script Python autonome qui cherche des sorties pour enfants sur le web et les
propose au site comme n'importe quel programme tiers : via `POST /api/events`
avec une clé d'API. Les sorties trouvées arrivent **en attente de modération**,
jamais publiées directement.

Seule la recherche passe par l'API Claude (outil serveur `web_search`) : le
téléchargement des pages et l'extraction de leurs liens se font en Python, et
le modèle n'intervient que pour trancher — trier des liens, remplir une fiche.

Deux modes, choisis par configuration et jamais mélangés : **recherche**, où le
modèle cherche sur le web, et **site**, où l'on donne l'adresse d'un festival
ou d'un théâtre et où aucune recherche n'est lancée. Ils ne diffèrent que par
l'étage découverte ; tout le reste — lecture, dates, photo, géocodage,
soumission — est le même code (voir « [Les deux modes](#les-deux-modes) »).

## Installation

Sur le VPS, rien à faire : le déploiement automatique envoie le dossier, crée
l'environnement virtuel et écrit le `.env` depuis les secrets GitHub. Seule
l'unité systemd du worker s'installe à la main, une fois, en root — le
déploiement la dépose à jour dans `/opt/sortiespourpetits/deploy/`, la
procédure est au § 9 de [`deploy/README.md`](../deploy/README.md).

Les instructions ci-dessous sont pour une installation locale.

```bash
cd scraper
python3 -m venv .venv && source .venv/bin/activate
pip install -e .            # + ".[dev]" pour les tests
cp .env.example .env        # puis renseignez les clés
```

`.env` :

| Variable | Rôle |
|---|---|
| `ANTHROPIC_API_KEY` | clé de l'API Claude |
| `SPP_API_URL` | URL du site (défaut `http://localhost:3000`) |
| `SPP_API_KEY` | clé `spp_…` créée depuis la page « Clés d'API » du site |

La clé du site hérite du rôle de son compte : rattachez-la à un compte dont les
propositions doivent passer par la modération.

## Utilisation

Deux façons de lancer une recherche, le même pipeline derrière :

| | Console du site | Ligne de commande |
|---|---|---|
| Configuration | table `ScraperConfig`, éditée dans **Recherche auto** | fichier YAML de `configs/` |
| Déclenchement | bouton « Essai » ou « Lancer et proposer » | `python -m sortiesbot` |
| Mémoire des pages | table `ScrapedUrl`, **commune à toutes les recherches** | SQLite local `state/seen.sqlite3` |
| Journal | consultable dans la console, page par page | fichiers de `runs/` |

La console est le mode normal ; la ligne de commande sert à mettre au point une
configuration ou à rejouer un run.

### Depuis la console (worker)

Le worker tourne en service sur le VPS (`sortiespourpetits-scraper`, installé
selon le § 9 de [`deploy/README.md`](../deploy/README.md)) et attend le
travail :

```bash
python -m sortiesbot.worker          # boucle, une passe toutes les 30 s
python -m sortiesbot.worker --once   # traite au plus une exécution, puis sort
```

Il réclame l'exécution en attente (`POST /api/scraper/next`), joue la
recherche avec la configuration que le site lui donne, rend compte page par
page (`/runs/:id/items`) puis clôt l'exécution avec ses compteurs
(`/runs/:id/finish`). Il ne décide de rien : tout se règle dans la console.

Une exécution est close **quoi qu'il arrive**, y compris sur un plantage :
sans clôture elle resterait « En cours » dans la console, et bloquerait toute
nouvelle exécution de la même configuration.

### En ligne de commande

```bash
# Dry-run (défaut) : rien n'est envoyé au site.
python -m sortiesbot --config configs/spectacles-weekend.yaml

# Soumission réelle, une fois le JSON du dry-run relu.
python -m sortiesbot --config configs/spectacles-weekend.yaml --submit

# Un site précis, sans aucune recherche web (voir configs/festival-site.yaml).
python -m sortiesbot --config configs/festival-site.yaml
```

**Un run dure plusieurs minutes.** L'étage découverte enchaîne une dizaine de
recherches et de lectures de pages dans un seul appel, côté Anthropic ; il faut
le laisser aller au bout. La console affiche le temps écoulé en tête de chaque
ligne et se remplit au fur et à mesure — résumé du raisonnement, puis chaque
recherche et chaque page ouverte. Si rien n'apparaît pendant plus d'une minute,
c'est anormal ; sinon, c'est que ça travaille.

| Option | Effet |
|---|---|
| `--submit` | propose réellement les sorties (sinon rien n'est envoyé) |
| `--limit N` | plafonne le nombre de sorties du run |
| `--quiet` | pas de sortie console (le journal reste écrit) |
| `--forget` | ignore la mémoire des URLs déjà vues, pour rejouer un run |
| `--runs-dir`, `--state` | emplacements du journal et de la mémoire |
| `--classifier-dir` | dossier du registre du classifieur, un fichier horodaté par run (`-` pour ne rien écrire) |
| `--save-pages DOSSIER` | archive chaque page téléchargée dans un sous-dossier horodaté |

Chaque run écrit deux fichiers dans `runs/` :

- `<horodatage>_<config>.jsonl` — le **journal détaillé** : chaque requête
  lancée, chaque page ouverte, chaque page écartée et pourquoi, chaque
  géocodage, chaque soumission, et la consommation de jetons par étage ;
- `<horodatage>_<config>.json` — les **sorties retenues**, payload prêt pour
  l'API, à relire avant de relancer avec `--submit`.

## Comment ça marche

> Les mêmes explications en version illustrée, à ouvrir dans un navigateur :
> [`docs/scraper-posters.html`](../docs/scraper-posters.html) (deux planches
> d'une page) et [`docs/scraper-anatomie.html`](../docs/scraper-anatomie.html)
> (le document long, avec le détail du coût). Index et statut de ces documents
> dans [`docs/`](../docs/README.md).

### Les sept étages, et où ils sont dans le code

Le pipeline a toujours eu six étages, mais ils ne vivaient que dans cette
documentation : le code les enchaînait sans les nommer, dans trois fonctions
qui en portaient deux chacune. Ils ont désormais **une classe et un fichier
par brique**, leur vocabulaire commun dans
[`sortiesbot/stages/__init__.py`](sortiesbot/stages/__init__.py), et chaque
étage s'ouvre explicitement avec `log.stage(...)` :

| # | Étage | Qui travaille | Reçoit | Rend | Où |
|---|---|---|---|---|---|
| 1 | Découverte | modèle | des requêtes web | les URL qu'elles ont remontées | `stages/discovery.py` — `Discovery` |
| 2 | Reconnaissance | **mixte** | une URL trouvée | sa nature : agenda, sortie ou programme | `stages/identification.py` — `Identification` |
| 3 | Dépouillement | Python | URL d'agenda | liens et leur contexte | `stages/harvest.py` — `Harvest` |

| 4 | Sélection | modèle | liens numérotés | numéros retenus | `stages/selection.py` — `Selection` |
| 5 | Lecture | Python | URL de page | texte, dates JSON-LD, image | `stages/reading.py` — `Reading` |
| 6 | Extraction | modèle | texte de la page | fiche(s) JSON | `stages/extraction.py` — `Extraction` |
| 7 | Publication | Python | fiche JSON | sortie en attente de modération | `stages/publication.py` — `Publication` |

La **reconnaissance** est arrivée en dernier, d'un constat : la découverte
classait les pages parce que le fournisseur savait le faire au passage, pas
parce que c'était sa place. La nature d'une page est une propriété de la page,
pas de la façon dont on l'a trouvée. En la sortant de là, la découverte se
réduit à « des requêtes entrent, des URL sortent » — le seul contrat qu'un
moteur de recherche ordinaire sait honorer, et donc la condition pour en
brancher un autre un jour.

Elle est le seul étage **mixte** : gratuite tant qu'un signal certain tranche,
facturée quand ils se taisent tous.

Aucune brique ne sait ce qui vient avant ou après elle : l'ordre n'existe qu'à
un seul endroit, [`sortiesbot/orchestrator.py`](sortiesbot/orchestrator.py),
et plus précisément dans une seule méthode, `Run.chain()`. Les six appels s'y
suivent de haut en bas, chacun annoncé par son numéro, et leur **indentation
dit la cardinalité** — ce qui est plus à droite tourne plus souvent :

```
1  découverte                              1 fois par run
     2  reconnaissance                     1 fois par URL trouvée
       si agenda :
         3  dépouillement                  1 fois par agenda
         4  sélection                      1 fois par agenda
       si sortie ou programme : elle saute 3 et 4
   puis, pour chaque page retenue :
     5  lecture                            1 fois par page
     6  extraction                         1 fois par page → n fiches
          7  publication                   1 fois par fiche
```

`chain()` ne contient rien d'autre que ces sept appels et les branchements qui
décident de la suite. Ce qui tranche *si* une page est lue — doublons du run,
plafond de sorties, budget — est en amont, dans `_to_read()` ; l'intendance du
run — catégories du site, comptes finaux, ouverture et clôture du journal —
est groupée à part, dans `go()`. Sans ce partage, la chaîne se lisait coupée
en trois par des décisions qui ne la concernaient pas.

Elles n'ont **pas** de signature commune, et c'est délibéré : ces cardinalités
diffèrent, et une interface uniforme aurait fait croire à une chaîne de six
maillons identiques. Ce qu'elles partagent — le contexte du run, l'ouverture
de leur étage au journal — est dans `stages/base.py` (`RunContext`, `Brick`).

L'étage n'est pas passé en paramètre à chaque appel : `RunLog.stage()` est un
gestionnaire de contexte, et tout ce qui est journalisé à l'intérieur lui est
rattaché. C'est ce qui permet à la console de reconstituer le graphe sans que
le code ait à se répéter — et à `stages.describe()` d'être la seule source des
libellés, y compris pour l'interface du site.

### La pagination d'un agenda

La deuxième page d'un agenda porte des sorties que la première n'a pas. Le
dépouillement la suit — **mais seulement tant qu'il manque de liens**.

C'est ce qui borne la dépense : les liens partent ensuite au tri, qui est
facturé, et tripler leur nombre triplerait cet appel. Un agenda déjà riche
s'arrête donc à sa première page ; un agenda maigre va chercher plus loin, ce
qui est exactement l'inverse d'un gaspillage. Deux plafonds, et ils ne disent
pas la même chose : `max_next_pages` (deux par défaut) borne le nombre de
pages, les deux cents liens de `links_of` bornent la récolte.

On ne suit que `rel="next"`. Reconstruire « page 2 » à partir d'une suite de
liens numérotés reviendrait à **inventer une URL**, ce qu'on s'interdit partout
ailleurs — et une page qui se déclare sa propre suite ferait tourner en rond.

### Chercher avec Google plutôt qu'avec le modèle

Depuis la console : **Recherche auto** → une configuration → *Moteur de
recherche*. En YAML : `provider: serper`. Dans les deux cas, cela remplace
**un seul des cinq appels**,
la recherche. Serper interroge Google et rend du JSON ; il ne reconnaît pas une
page et ne remplit pas une fiche, donc le modèle reste derrière pour les quatre
autres. C'est ce que l'étage 1 a rendu possible en cessant de juger : il ne
demande plus que des URL, et un moteur sait en rendre.

| | `web_search` (Anthropic) | Serper |
|---|---|---|
| Index | Brave | Google, plus profond sur le local francophone |
| Prix d'une requête | 0,01 $ | **0,001 $**, annoncé par la réponse |
| Jetons d'entrée | le contenu des résultats entre dans le contexte | aucun |
| Ce qu'on reçoit | contenu de page | titre, lien, extrait |

Ce qu'on perd — le contenu — n'a plus d'importance depuis que la
reconnaissance télécharge la page et juge sur son HTML.

La forme des réponses a été **confrontée au service** ; le détail de ce qui a
été observé est en tête de `providers/serper_provider.py`. Les tests, eux,
simulent : ils verrouillent ce que le code fait de cette forme, pas qu'elle
soit la bonne. Pour la revérifier — après un changement d'API, par exemple —
il suffit de mettre `[serper]` dans un message de commit : le job du même nom
appelle le vrai service et affiche ce qu'il rend.

### Le journal, et où il va

Un même événement part vers trois destinations :

* le **fichier JSONL** de `runs/` — et il est désormais toujours écrit : si le
  dossier est illisible (typiquement créé par root, alors que le service tourne
  en `deploy`), le worker se replie sur un dossier temporaire au lieu de
  renoncer ;
* la **console**, pour un run lancé à la main ;
* le **site**, par `POST /api/scraper/runs/:id/logs`, qui alimente la page de
  débogage — c'est ce qui manquait : le worker tourne en service systemd, et
  tout ce que le journal racontait mourait sur la sortie standard.

La page de débogage se trouve depuis le détail d'une exécution, bouton
« Journal détaillé et graphe des étages ». Elle dessine les six briques avec
leurs compteurs, et le journal filtrable en dessous : par étage (en cliquant
une brique), par type d'événement, par gravité, par page suivie, ou par texte
libre. Les filtres se composent et se retirent un par un.

Le journal est verbeux : chaque lien soumis au tri y figure, soit près d'un
millier de lignes par exécution. C'est ce qui le rend utile, et c'est pourquoi
un bouton permet d'oublier celui d'une exécution donnée sans toucher à ses
compteurs ni au sort de ses pages.

### La filiation, et l'arbre du run

Un journal plat répond à « qu'est-ce qui s'est passé ? ». Il ne répond pas à
« **d'où vient cette sortie ?** », qui est la question qu'on se pose devant une
proposition douteuse — et les deux ne se déduisent pas l'une de l'autre.

Chaque événement porte donc sa filiation, posée par `RunLog.trail()` sur le
même principe que `stage()` : on ouvre une piste, tout ce qui est journalisé
dedans en hérite, et le code n'a pas à répéter `agenda=…` sur quarante appels.

| Clé | Posée par | Ce qu'elle relie |
|---|---|---|
| `query` | le fournisseur, à chaque `search_result` | la requête web → les URL qu'elle a remontées |
| `agenda` | `Run.chain`, autour des étages 2 et 3 | l'agenda → ses liens, ses liens retenus, ses pages |
| `page` | `Run.chain`, autour des étages 4 à 6 | la page → sa lecture, son extraction, son verdict |

La console reconstitue l'arbre à partir de ces trois clés
(`server/src/lib/scraperTree.ts`), et la page de débogage l'affiche en regard
du journal : les recherches et ce que chacune a remonté, puis chaque agenda
avec la requête qui l'a fait apparaître, ses liens extraits, ceux que le
modèle a retenus, et les sorties qui en sont sorties avec leur verdict.

Un nœud de l'arbre ouvre le journal filtré sur sa branche : c'est la jonction
entre « d'où vient-ce ? » et « que s'est-il passé exactement ? ».

### Pourquoi un site remonté n'a rien donné

Trois chemins faisaient auparavant disparaître un agenda sans laisser de
trace, et c'est ce qui rendait la console incompréhensible — un site remonté
par la recherche n'apparaissait nulle part, sans qu'on sache pourquoi :

| Cas | Ce qui est journalisé | Ce que la console affiche |
|---|---|---|
| Retenu et dépouillé | `agenda_planned`, `harvested`, `selected` | « dépouillé », ses liens et ses sorties |
| Retenu mais injoignable (403, `robots.txt`) | `agenda_planned` puis une erreur | « injoignable », avec le code HTTP |
| Retenu mais au-delà de `max_agendas` | un avertissement portant l'URL | « au-delà du plafond », et le réglage en cause |
| Remonté mais non désigné par le modèle | rien de plus que `search_result` | « non retenu par le modèle » |

Chaque résultat de recherche porte donc son sort, et un agenda jamais ouvert
garde son nœud dans l'arbre avec le motif.

### Le classifieur en observation

Aujourd'hui, c'est le modèle qui dit d'une page trouvée si elle est un
**agenda** ou une **sortie**, à l'étape 1 : la recherche lui remonte le
contenu des pages, et il le lit. Cette réponse est confortable, mais elle est
liée au fournisseur — un moteur de recherche ordinaire ne rend que des
extraits, pas des pages — et elle est payante à chaque run.

Or la même question se répond sur le HTML, gratuitement, une fois la page
téléchargée. C'est ce que fait [`sortiesbot/classify.py`](sortiesbot/classify.py),
en cascade, du plus certain au plus flou :

| # | Signal | Ce qu'il dit | Confiance | Coût |
|---|---|---|---|---|
| 1 | **URL** | `?page=2`, `?search=`, `?filter[]=` → agenda | certain | nul |
| 2 | **Pagination** | `rel="next"`, ou une suite « 1 2 3 » → agenda | certain | nul |
| 3 | **JSON-LD** | un seul spectacle nommé → sortie ; trois titres distincts ou un `ItemList` → agenda | certain | nul |
| 4 | **OpenGraph** | `og:type: event` → sortie | probable | nul |
| 5 | **Le modèle**, sur le condensé | agenda, sortie, ou inconnu | probable | ~0,001 $ |

La **pagination** comble le manque que la première mesure avait révélé : sans
elle, rien ne savait dire « agenda » — ni l'`ItemList`, ni les paramètres
d'URL, dont aucun n'a tiré sur les vingt-sept premières pages.

Elle exige une suite **consécutive** partant du début : `1 2 3` ou `2 3 4`,
jamais trois numéros quelconques. La première version se contentait de trois
nombres, et `22, 29, 35, 44, 56` — le gabarit de `recreatiloups.com` — a fait
passer trois fiches pour des agendas, avec la mention « certain ». Une erreur
étiquetée certaine ne fausse pas seulement le verdict : elle empoisonne le
corpus qu'on est en train de constituer. Une page qui se
pagine a une page suivante, donc plusieurs pages de quelque chose ; une fiche
n'en a pas. Elle se lit sur le HTML brut, pas sur `links_of` : celui-ci écarte
justement ces liens-là — moins de quinze caractères de texte, et `/page/2`
parmi les chemins de service. Ce qui est du bruit pour le dépouillement est ici
le signal.

Les quatre premiers sont du Python : ils ne coûtent rien. C'est la cascade de
la **reconnaissance** (étage 2). Le quatrième n'est appelé que
lorsqu'ils se taisent tous — `classify_model: ""` en configuration le
désactive, et la page reste « inconnue ».

Le **condensé** (`classify.digest`) est la carte d'identité d'une page : URL,
titre, `h1`, trois cents caractères d'amorce, et vingt textes de liens —
**les datés d'abord** — avec combien d'entre eux voisinent une date. Sur un
grand portail, les vingt premiers liens du document sont le menu : les moins
instructifs de la page, et c'étaient eux qui remplissaient le condensé. Quelques centaines de
jetons, jamais la page entière — celle-là, l'extraction la paie déjà. Il est
borné par construction, que la page fasse 2 Ko ou 2 Mo.

Cette densité de dates est le candidat sérieux au signal structurel qui
manque : *un agenda mène à des choses datées*. Elle est relevée et archivée
dès maintenant, sans voix au chapitre — c'est la leçon du comptage de liens.

Le piège est documenté dans `json_ld_dates` : beaucoup de sites publient « un
`schema.org/Event` par représentation ». Compter les objets classerait en
agenda toute pièce jouée douze fois — on compte donc les **titres distincts**.

### Deux mesures qui ne classent rien

Il y a eu un signal de plus, le **nombre de liens exploitables**, et
vingt-sept pages réelles l'ont enterré. Les deux populations se recouvrent de
bout en bout :

```
agendas dépouillés          10   33   55  65  78  90
fiches tirées d'un agenda   10 10 10 10 11  21  38  42  61
```

Aucun seuil ne les sépare. Sur `parismomes.fr`, huit pages du même site —
agendas et fiches mêlés — rendent toutes **exactement dix liens** : c'est le
gabarit du site qu'on mesurait, pas la nature de la page. Sur
`sortiraparis.com`, une fiche unique en rend deux cents, le plafond de
`links_of` : le compteur est saturé. Le compte reste relevé au registre — il
servira si l'on cherche un jour un vrai signal structurel, des blocs répétés
portant chacun un lien *et* une date — mais il ne décide plus rien.

Le **chemin** d'une URL ne dit rien non plus, pour la même raison. Sur les
mêmes vingt-sept pages, deux domaines sur sept servent agendas et fiches sous
le même segment :

```
iledefrance.kidiklik.fr/articles/   → un agenda ET des fiches
parismomes.fr/ecouter-voir/         → un agenda ET des fiches
```

Une règle sur `/agenda/` ou `/que-faire/` reviendrait à réapprendre le gabarit
de chaque site, et à ne rien savoir de celui qu'on n'a jamais vu — c'est-à-dire
du cas d'usage. Seuls les **paramètres de requête** sont retenus : eux ne
décrivent pas un site, ils décrivent une opération.

Sur ce premier échantillon, le JSON-LD couvrait **47 % des pages lues**, sans
une erreur apparente. C'est peu de données (27 pages, 7 domaines) : à confirmer.

### Le corpus, pour plus tard

Chaque page constatée part au registre **avec son condensé** et avec le nom du
modèle qui a tranché, s'il a été appelé. C'est ce qui permettra un jour
d'entraîner un classifieur local et de se passer du quatrième signal.

Une mise en garde, alors : entraîner sur les réponses du modèle ne donne au
mieux qu'une **imitation** de ce modèle. Pour un classifieur qui soit *juste*,
les étiquettes doivent venir du sort final de la page — le verdict de
l'extraction, qui dit « page de liste » ou rend une fiche valide. Le condensé
est le corpus, la réponse du modèle est la référence à battre, et l'issue du
run sera la vérité.

`inconnu` est une réponse, pas une panne : l'orchestrateur sait déjà quoi
faire d'une page dont il ignore la nature. Il la traite en agenda, et son
filet la relit comme une sortie si le dépouillement ne donne rien. L'erreur
n'est pas symétrique — croire qu'une sortie est un agenda coûte un appel de
sélection et se rattrape tout seul, l'inverse coûte tous les liens d'un
agenda. D'où le biais assumé : **dans le doute, agenda.**

Cette cascade **décide** désormais, et elle aiguille en trois :

| Nature | Ce que c'est | Où elle va |
|---|---|---|
| **agenda** | liste des sorties et **renvoie** vers leurs fiches | dépouillement, puis tri |
| **sortie** | la fiche d'un événement précis | droit à la lecture |
| **programme** | porte plusieurs sorties et **les décrit lui-même** — le festival qui tient sur une page | droit à la lecture, et l'extraction en tire plusieurs fiches |

Le partage entre agenda et programme tient à une question : pour lire le détail
d'une de ces sorties, faut-il **cliquer**, ou est-ce déjà **sous les yeux** ?
Aucun signal gratuit ne sait le dire — un `ItemList` n'indique pas si les
fiches sont ailleurs — donc cette distinction-là revient presque toujours au
modèle. Le condensé s'y prête : un programme a beaucoup de dates et peu de
liens, un agenda a beaucoup des deux.

**L'extraction peut corriger la reconnaissance.** Elle est la première du
pipeline à lire le texte entier ; quand elle répond « ce n'est pas une sortie,
il y en a plusieurs ici » (`several`), la page repart pour un tour, en
programme cette fois. Une seule reprise, et la garantie tient à la structure
plutôt qu'à un compteur : la relecture pose `multiple`, et la condition de
reprise exige qu'il soit faux — le second passage ne peut pas remplir la
condition qui a déclenché le premier.

C'est aussi la meilleure étiquette dont on dispose : « l'étage 6 a corrigé
l'étage 2 » part au registre sous le sujet `requalify`, et c'est cette
vérité-là qui servira à apprendre à mieux reconnaître.

Le chemin du programme n'est pas neuf : c'est celui que le mode « site »
empruntait déjà (`multiple`), et ses sorties se mémorisent une à une plutôt que
la page — sinon un programme lu une fois ne serait plus jamais relu, et tout ce
qu'il annoncerait ensuite serait perdu. Une page qu'on ne sait pas reconnaître
part **en agenda**, et c'est délibéré — prendre une sortie pour un agenda coûte
un tri et se rattrape tout seul, prendre un agenda pour une sortie coûte tous
ses liens sans rattrapage.

Le HTML est téléchargé une fois pour toutes à cet étage : le `Fetcher` garde
les pages du run et les rend à qui les redemandera, si bien que le
dépouillement et la lecture ne repassent pas sur le réseau.

### Le registre, et comment le lire

Les journaux de run s'oublient — un bouton de la console est là pour ça. Une
mesure qui s'accumule sur des semaines n'a donc rien à y faire : elle part
dans un fichier à part, en ajout seul, hors de `runs/`.

**Un fichier horodaté par exécution** — `state/classifier_2026-09-01T03-38-29_14.jsonl` —
sur le modèle des journaux de `runs/` : deux runs ne se marchent jamais
dessus, et un fichier se copie ou s'envoie sans emporter les autres. Le
dossier se règle par `--classifier-dir` en ligne de commande (`-` pour ne rien
écrire) ; le service écrit dans `state/` de la même façon.

`--save-pages` suit la même règle : chaque run archive dans son propre
sous-dossier horodaté. Deux captures du même site à deux semaines d'écart sont
deux données, pas une qui écrase l'autre.

```bash
# Le taux d'accord, en ne comptant chaque page qu'une fois par run.
jq -s 'unique_by(.run + .url) | map(select(.agrees != null))
       | (map(select(.agrees)) | length) as $ok | "\($ok) / \(length)"' \
   state/classifier_*.jsonl

# Les désaccords, et le signal qui les a produits.
jq -r 'select(.agrees == false) | "\(.signal)\t\(.announced) → \(.verdict)\t\(.url)"' \
   state/classifier_*.jsonl

# Quel signal a tranché, et combien de fois on a payé.
jq -r .signal state/classifier_*.jsonl | sort | uniq -c | sort -rn
```

Un désaccord ne dit pas encore qui a raison. C'est le **sort final de la
page**, dans le même run, qui tranche : une page annoncée « agenda » dont
aucun lien n'est retenu et dont l'extraction rend une sortie valide donne tort
au modèle ; une page annoncée « sortie » dont l'extraction rend
`relevant=false` avec « page de liste » lui donne tort dans l'autre sens. Le
journal porte les deux bouts, reliés par l'URL.

### Le partage des rôles

Python fait tout ce qui est mécanique — télécharger, parser, extraire des
liens — et ne coûte rien. Le modèle n'intervient qu'aux trois moments où il
faut du jugement, et **aucun de ces appels ne boucle** :

```
1. recherche        modèle + web_search   → pages à ouvrir, classées
   (mode « site » :                         « agenda » ou « sortie »
    les URLs sont données, rien n'est lancé)
   ├─ sortie  ─────────────────────────────────────────┐
   └─ agenda                                           │
2. téléchargement   Python                → HTML       │           gratuit
3. extraction liens Python (BeautifulSoup)→ (texte, url, contexte)  gratuit
4. sélection        modèle, sans outil    → liens menant à une sortie
                                                       │
5. lecture + fiche  Python puis modèle ◀───────────────┘
                                          → une sortie structurée,
                                            ou plusieurs si c'est un programme
   puis géocodage, validation, photo, soumission — sans modèle
```

Une recherche ne remonte pas que des agendas : elle tombe régulièrement sur la
page d'une sortie précise. Le modèle classe donc chaque page retenue, et une
sortie trouvée directement court-circuite les étapes 2 à 4. S'il se trompe et
qu'un « agenda » ne donne aucun lien, la page est relue comme une sortie — elle
est déjà téléchargée, la lire coûte 0,004 $, l'ignorer coûte la sortie.

C'est ce découpage qui rend le coût prévisible. La version précédente confiait
toute la procédure à un seul appel agentique : le modèle ouvrait les pages
lui-même, et la boucle serveur d'Anthropic refacturait tout le contexte
accumulé à chacune de ses itérations. Un run mesuré à **2,35 $** pour six
sorties, dont 2,29 $ de jetons d'entrée — un million de jetons pour six
recherches et cinq pages.

### Les deux modes

Une recherche web est le bon outil quand on ne sait pas où chercher. Elle est
le mauvais outil quand on le sait déjà : demander à un moteur de retrouver
`formulabula.fr` alors qu'on a l'adresse, c'est payer 0,01 $ pour espérer que
Google la remonte — et accepter qu'il remonte autre chose.

D'où le champ `mode`, qui ne change qu'une seule chose : d'où viennent les
pages à lire.

| | `recherche` (défaut) | `site` |
|---|---|---|
| Origine des pages | ce que le modèle trouve sur le web | `seed_urls`, dans la configuration |
| Coût de la découverte | 0,01 $ par recherche | **0 $** |
| Ce que `theme` sert à faire | orienter les requêtes, trier les liens | trier les liens, écarter ce qui n'est pas pour les enfants |
| Une page = | une sortie | une sortie, ou tout un programme |

Tout le reste est commun, et c'est délibéré : la fin de chaîne — lecture de la
page, dates réelles, illustration, géocodage, validation, mémoire, soumission —
est le morceau le plus délicat du projet. La dupliquer pour un second scraper
aurait voulu dire corriger chaque bug deux fois, et en oublier un sur deux. Le
point de bascule est donc unique et situé très haut : `discovery.candidates()`
choisit la stratégie, `pipeline.run()` ne connaît que le résultat.

Une configuration écrite avant l'ajout du mode ne porte pas ce champ ; elle
prend `recherche` et emprunte exactement le chemin d'avant.

### Le mode « site », en détail

On donne une ou plusieurs adresses, et rien d'autre :

```yaml
mode: site
seed_urls:
  - https://formulabula.fr/
max_page_chars: 30000
```

**La forme du site n'a pas à être déclarée : elle se constate.** Chaque adresse
est téléchargée, ses liens extraits, et c'est le résultat qui tranche —

- la page mène à des fiches (une page par spectacle) : on les suit, exactement
  comme un agenda trouvé par une recherche, et chaque fiche donne une sortie ;
- la page ne mène nulle part : c'est le programme lui-même. Un festival tient
  souvent sur une seule page, où les entrées ne sont reliées que par des ancres
  (`#atelier-bd`) — que l'extracteur de liens écarte, à raison, puisqu'elles ne
  mènent à aucune autre page.

Dans le second cas, le modèle reçoit la page entière et rend **une liste de
fiches** au lieu d'une seule (`extraction_multi_prompt`, schéma
`EXTRACTION_MULTI_SCHEMA`). C'est le seul appel dont le nombre de sorties n'est
pas connu d'avance ; il est plafonné par `max_events`.

Deux réglages comptent vraiment ici :

- **`max_page_chars`** doit monter (8 000 → 30 000). Un programme complet est
  long, et il est lu d'un seul tenant : au plafond d'une page ordinaire, il
  serait coupé au milieu de la troisième sortie.
- **`theme`** ne sert plus à chercher, mais il tranche encore : c'est lui qui
  écarte, dans le programme, la soirée de vernissage et la table ronde
  professionnelle.

**La mémoire change d'unité, et c'est le point délicat.** Mémoriser la page
d'un programme reviendrait à ne plus jamais la relire — donc à manquer tout ce
que le festival y ajoutera d'ici son ouverture. Ce sont donc ses **sorties**
qui sont mémorisées, une par une, sous une clé `page#titre-normalisé`
(`store.event_key`). Conséquence : la page est relue à chaque run, ce qui ne
coûte que son extraction, et seules les nouveautés sont proposées.

L'illustration, elle, est commune : le HTML d'une page de programme n'annonce
qu'une image (`og:image`), et toutes ses sorties la partagent. Une vignette
juste vaut mieux que vingt fiches nues.

### Étape 3, en détail

Une page d'agenda, ce qu'on y cherche, ce sont ses liens. Les faire lire au
modèle coûtait 12 000 jetons par page ; BeautifulSoup les extrait pour rien :

```python
for lien in soup.find_all("a", href=True):
    texte  = lien.get_text(strip=True)          # "Les Caprices de l'enfant roi"
    url    = urljoin(page, lien["href"])
    autour = lien.find_parent(...).get_text()   # "jusqu'au 30 août — Théâtre de Vanves"
```

Le contexte est le gain caché : les agendas affichent la date et le lieu à
côté du titre, donc l'étape 4 tranche souvent **sans ouvrir la page**.

Un premier tri mécanique retire ensuite le bruit évident — liens vides, ancres,
`mailto:`, liens sortants, textes de moins de 15 caractères (« Accueil »,
« Contact »), chemins de service (`/mentions-legales`, `/cgu`, `/newsletter`…),
doublons. Il n'a pas à être parfait : il doit réduire deux cents liens à une
cinquantaine pour que le modèle en juge à moindre coût.

### Étape 4 : le modèle répond par des numéros

Les liens lui sont soumis numérotés, et il renvoie les numéros retenus — jamais
des URL. **Il lui est donc matériellement impossible d'en inventer une**, ce qui
était un vrai problème dans la version précédente. Sa réponse tient en quelques
jetons.

### Les vraies dates d'une sortie

Un spectacle joué tous les dimanches de juillet et août arrive en base comme
« du 1er juillet au 31 août ». Cherchez une sortie un jeudi d'août : le site
le propose. Ce n'est pas approximatif, c'est faux.

Le pipeline calcule donc maintenant les dates réelles, à partir de trois
sources, de la plus sûre à la plus faible :

| Source | D'où elle vient | Coût |
|---|---|---|
| `json-ld` | le `schema.org/Event` que le site publie pour Google, **quand il porte une entrée par représentation** | nul — c'est dans le HTML déjà téléchargé |
| `dates annoncées` | « les 3, 7 et 12 août », relevé par le modèle à l'extraction | quelques jetons de sortie |
| `récurrence` | « tous les dimanches à 15h », rendu en jours de la semaine puis déroulé en Python | idem |
| `plage` | rien trouvé : la plage vaut pour tous ses jours, comme aujourd'hui | — |

Le JSON-LD demande de la prudence, et le premier run l'a montré : dix-huit
sorties sur vingt en annonçaient un, **toutes avec une seule date**. Ce
n'étaient pas dix-huit calendriers, mais dix-huit premiers jours d'affiche —
et cette date unique écrasait une récurrence, elle, exacte. Deux garde-fous
depuis : un `Event` dont la `endDate` tombe un autre jour décrit une période
et non une séance, il est ignoré ; et une date isolée ne fait un calendrier
que si la sortie tient sur un seul jour.

Aucun navigateur sans tête, aucun clic dans un widget de réservation : la
page dit presque toujours en toutes lettres ce que le calendrier de
réservation ne fait que ré-énumérer. Le JSON-LD, lui, était jusqu'ici détruit
avant l'extraction — `page_text` supprime les balises `script`.

Le calendrier part maintenant au site, dans le champ `dates` du payload, et
alimente la table `EventDate`. **Une liste vide veut dire « tous les jours de
la période »** — le cas d'une exposition ou d'une fête foraine, et le seul
modèle possible avant cette table. La recherche du site s'appuie sur les jours
quand ils existent, sur la période sinon.

Le calendrier reste journalisé (ligne `schedule`), avec sa source et la plage
dont il découle ; le compteur `scheduled` du résumé dit combien de sorties du
run ont des dates réelles plutôt qu'une plage. Sur le run qui a servi de
mesure : huit sur huit.

### Où se trouve la sortie

Le géocodeur (Photon, puis la Base Adresse Nationale) répond souvent plusieurs
lieux pour une même requête, et il y a un « Espace culturel » dans la moitié
des communes de France. Deux réglages décidaient jusqu'ici lequel gagnait, et
tous deux étaient hérités du temps où le site ne couvrait que l'Île-de-France :

- un **biais de recherche figé sur le centre de Paris**, envoyé à Photon, qui
  reclassait les résultats par proximité ;
- **aucun contrôle de concordance**, le filtre par zone ayant été retiré à
  raison — une sortie voisine de la zone visée reste une bonne sortie.

Le résultat, sur un run « Seine-Maritime » : des sorties correctement trouvées,
correctement lues — la page disait « 76600 Le Havre » — et publiées à Paris,
parce que `build_payload` laissait la réponse du géocodeur **écraser** ce que
la page annonçait.

Trois corrections, dans cet ordre d'importance :

1. **Un résultat qui contredit la page est refusé** (`geocode.agrees_with_page`).
   La comparaison porte sur le département quand la page donne un code postal,
   sur la ville sinon, et sur rien du tout quand la page est muette — c'est le
   seul cas où une homonymie française passe encore. La bonne clé n'était pas
   la zone cherchée mais **ce que la page elle-même affirme** : elle vaut pour
   toutes les zones, et n'écarte que ce qui se contredit.
2. **Le biais parisien est supprimé.** Un biais est une préférence inventée ;
   la concordance ci-dessus est une vérification, et elle s'appuie sur une
   information qu'on a vraiment.
3. **La page passe avant le géocodeur** dans le payload : ville et code postal
   viennent de ce qui est écrit sur la page, le géocodeur ne complétant que ce
   qu'elle a laissé vide.

Conséquence assumée : une sortie dont le lieu ne se géocode pas de façon
cohérente part désormais en `(0, 0)` — « adresse à compléter », que la
modération signale — au lieu de partir avec certitude au mauvais bout de la
France, où la recherche par distance la proposerait. Le compteur `ungeocoded`
monte donc, et c'est le but.

### L'illustration de la sortie

Aucune sortie importée n'arrivait avec sa photo, et la cause tenait au partage
des rôles : le modèle ne reçoit que le **texte** de la page — `page_text`
détruit les balises — alors que le prompt lui demandait l'URL d'une image.
Une information qui n'est pas dans ce qu'on lui donne ne peut être que
devinée, et une URL devinée ne se télécharge pas.

L'image se lit donc en Python, dans le HTML, comme les dates JSON-LD et pour
la même raison — c'est gratuit, et il n'y a rien à juger (`harvest.main_image`) :

1. `og:image` (puis `twitter:image`, `link rel=image_src`) — c'est l'image que
   le site montre lui-même quand on partage la page, donc exactement celle
   qu'on cherche ;
2. le champ `image` du `schema.org/Event`, sous ses trois formes (URL, liste,
   `ImageObject`) ;
3. à défaut, les `<img>` du corps, logos, icônes, boutons de partage et
   vignettes écartés — le `data-src` du lazy-loading est lu comme un `src`.

Les SVG et les `data:` URI sont refusés, l'URL est rendue absolue, et le
téléchargement réutilise la session du `Fetcher` : sans notre User-Agent,
beaucoup de serveurs refusent l'image qu'ils viennent d'annoncer. Un type MIME
absent ou fantaisiste (`image/jpg`, `application/octet-stream`) ne condamne
plus la photo — les premiers octets tranchent.

Le prompt d'extraction ne demande plus d'image ; le champ `photo_url` reste
dans le schéma et sert de recours aux configurations qui ont leur propre
prompt.

### La mémoire des pages analysées

Une page lue est une page payée : la relire, c'est repayer. Toute page dont le
sort est **définitif** est donc mémorisée, et plus jamais rouverte — par aucune
recherche, la mémoire étant commune à toutes les configurations. C'est ce qui
fait que dix recherches spécialisées se complètent au lieu de se répéter.

Restent journalisées mais **non** mémorisées les décisions provisoires, qui ne
doivent pas empêcher un run ultérieur de traiter la page :

| Décision | Mémorisée ? | Pourquoi |
|---|---|---|
| `submitted` — proposée au site | oui | c'est fait |
| `irrelevant` — pas une sortie | oui | la page ne changera pas de nature |
| `invalid` — inexploitable | oui | idem |
| `out_of_period`, `out_of_area` | oui | écartée sciemment (run strict) |
| `dry_run` — retenue à l'essai | non | sinon le run réel la sauterait |
| `seen`, `duplicate` | non | c'est la décision d'origine qui compte |
| `blocked` — domaine bloqué | non | un réglage, pas un jugement |
| `error` — site ou API injoignable | non | demain ça remarchera peut-être |

La mémoire se regarde et se purge depuis la console — « Recherche auto →
Mémoire ». Purger n'est pas anodin : les pages oubliées seront relues, donc
repayées, et celles qui avaient déjà donné une sortie pourront la proposer une
seconde fois. D'où la purge par verdict : oublier les `error` d'un site alors
en panne ne touche pas aux `submitted`.

**Défaire une exécution entière** se fait depuis sa page, dans la console :
« Supprimer les données de cette exécution » retire ses sorties — publiées
comprises — *et* oublie les pages qu'elle avait mémorisées. Les lignes de
mémoire se retrouvent de deux façons complémentaires : par la sortie qu'elles
ont produite (`ScrapedUrl.eventId`, exact et rétroactif) et par la clé que
l'exécution a employée (`ScraperRunItem.key`, seule à couvrir les pages
mémorisées sans avoir donné de sortie). La mémoire part avant les sorties :
la supprimer après aurait perdu le lien, `eventId` passant à NULL avec elles. Les deux vont
ensemble, et c'est tout l'intérêt du bouton : ne supprimer que les sorties
laisserait leurs pages mémorisées, donc jamais reproposées, et une recherche
mal réglée resterait punie longtemps après sa correction. Le journal de
l'exécution, lui, est conservé — il dit ce qu'elle a fait, et c'est justement
ce qu'on relit après coup.

Supprimer une sortie de la file de modération ne l'efface pas de cette
mémoire — la page reste connue, donc ne sera pas reproposée. Les deux gestes
sont distincts, et c'est voulu : on jette un import raté sans rouvrir la porte
aux mêmes pages.


La clé de mémorisation est l'URL normalisée (schéma, `www.`, barre finale et
paramètres de suivi retirés) ; le lien exact, lui, reste affiché et cliquable
dans la console.

**Une page de programme fait exception**, et c'est la seule. Elle porte
plusieurs sorties, et sa relecture au run suivant est justement ce qu'on veut :
un festival ajoute des dates jusqu'à son ouverture. La clé y devient
`page#titre-normalisé`, une par sortie (`store.event_key`) — la page reste donc
relisable, et seules les sorties déjà proposées sont sautées.

### Politesse

Puisque le scraper télécharge lui-même, il assume ce qu'Anthropic assumait :
`robots.txt` est lu et respecté, un `User-Agent` identifie le robot et renvoie
vers le site, et une seconde sépare deux requêtes vers le même hôte.

### Champs laissés à la modération

Une information introuvable ne fait pas perdre la sortie : elle est proposée
avec une valeur convenue que le site reconnaît
(`server/src/lib/incomplete.ts`).

| Information | Valeur envoyée | Effet côté site |
|---|---|---|
| Position (géocodage en échec ou hors zone) | `lat = 0`, `lng = 0` | invisible dans les recherches par distance ; bandeau « lieu non géolocalisé » |
| Tarif introuvable sur la page | `price = -1`, `isFree = false` | badge « Tarif à compléter » au lieu du prix ; bandeau « tarif indéterminé » |

Dans les deux cas, **l'approbation est refusée** tant qu'un modérateur n'a pas
corrigé le champ, et le bandeau pointe vers le formulaire d'édition.

## La configuration oriente, elle ne filtre pas

Thème, période et zone servent aux deux premières étapes : formuler les
recherches, trier les liens. C'est là qu'ils font gagner du temps et de
l'argent, en évitant d'ouvrir des pages sans intérêt.

Passé l'extraction, ils ne servent plus à rien — parce que la page est
**déjà lue et déjà payée**. L'écarter parce qu'elle déborde de la fenêtre,
c'est payer pour ne rien garder, alors que le site sait filtrer par date et
par distance, et qu'un modérateur relit chaque proposition.

Une recherche « spectacles de ce week-end » qui croise un atelier de musée
programmé dans trois mois le rapporte donc quand même. Plusieurs
configurations spécialisées (musée, spectacle, fête foraine…) se complètent
ainsi : chacune ratisse son thème et ramasse au passage ce que les autres
auraient manqué. `keep_out_of_scope: false` rétablit la rigueur d'une fenêtre
stricte si une configuration en a besoin.

Le géocodeur suit la même logique : il vérifie que la position trouvée est en
France — une homonymie, il y a un Montreuil au Québec — mais plus qu'elle est
dans les départements visés.

## Configuration

Une configuration = un fichier YAML dans `configs/` : `spectacles-weekend.yaml`
pour le mode `recherche`, `festival-site.yaml` pour le mode `site`, tous deux
commentés. Seules `name` et `theme` sont obligatoires — plus `seed_urls` si le
mode est `site`. Les prompts eux-mêmes sont des clés de la configuration
(`search_prompt`, `select_prompt`, `extraction_prompt`,
`extraction_multi_prompt`) : on peut les réécrire
sans toucher au code — les variables disponibles sont listées en tête de
`sortiesbot/prompts.py`.

Le choix des modèles est par configuration (`search_model`, `select_model`,
`extraction_model`), ce qui permet de comparer les coûts d'une recherche à
l'autre.

**Pourquoi Haiku partout.** Haiku 4.5 échoue dès qu'on lui demande de dérouler
une procédure en plusieurs temps — essayé trois fois : il cherche puis conclut
sans rien ouvrir, ou répond de mémoire sans chercher. Il est en revanche
parfaitement à l'aise sur une tâche bornée. Le pipeline actuel n'en contient
que : chercher, trier une liste, remplir un formulaire. C'est le découpage qui
permet le modèle bon marché, pas l'inverse.

Le seul outil serveur encore utilisé est `web_search_20250305`, la variante de
base : le filtrage dynamique des variantes récentes servait à alléger les pages
que le modèle lisait, et il ne lit plus de pages.

## Tests

```bash
pip install -e ".[dev]"
python -m pytest
```

Ils tournent aussi en intégration continue, sur toute branche et toute pull
request (`.github/workflows/verifier.yml`), avec le typecheck du front et la
compilation de l'API. Le workflow de déploiement compilait déjà le front, donc
il typecheckait — mais seulement sur `main`, c'est-à-dire une fois qu'il est
trop tard : une erreur de type y cassait la mise en production plutôt qu'une
branche. Et les tests du scraper ne tournaient nulle part.

Aucun test n'appelle le réseau : le fournisseur Claude est branché sur un
serveur HTTP local qui enregistre les requêtes, ce qui verrouille la forme de
ce qui est envoyé (outils serveur, format structuré, reprise après
`pause_turn`) sans dépenser de jetons.

### Le jeu de vraies pages

Ce qui casse en production n'est presque jamais l'enchaînement — c'est la
couche qui **lit le HTML** : un lien dont le texte a changé, un JSON-LD
reformaté, une illustration remplacée par un logo. Ces régressions-là ne se
voient que sur des pages entières, avec leur bandeau de cookies, leur
navigation et leur pied de page.

`tests/fixtures/pages/` en contient donc quelques-unes, décrites par un
`pages.jsonl` — une ligne par page : son fichier, son URL, et sa nature quand
elle a été étiquetée. `tests/test_golden.py` les rejoue.

**Ce format est celui qu'écrit `--save-pages`.** Élargir la couverture ne
demande donc pas une ligne de code :

```bash
python -m sortiesbot -c configs/spectacles-weekend.yaml --save-pages /tmp/pages
cp /tmp/pages/<page>.html scraper/tests/fixtures/pages/
# puis on recopie sa ligne dans pages.jsonl, en ajoutant "kind": "agenda"|"sortie"
```

Une page déposée est immédiatement utile : elle doit se lire sans rien casser.
Ajouter `kind` en fait en plus un cas de vérité pour le classifieur — c'est ce
jeu étiqueté qui dira, le moment venu, si on peut se passer du classement du
modèle.

Les assertions portent sur l'essentiel : quelles pages deviennent candidates,
combien de sorties sortent, leurs titres. Jamais sur le JSON octet par octet —
un test qu'un changement cosmétique fait rougir finit désactivé, et ne protège
plus rien. Et comme une capture porte des dates figées alors qu'un run se juge
par rapport à aujourd'hui, les assertions sur les dates restent du côté de la
lecture, où elles valent pour toujours.

## Coût d'un run

Trois postes seulement, tous bornés :

| Poste | Prix |
|---|---|
| Recherches web | 0,01 $ pièce (`max_searches`, 6 par défaut) — **0 $ en mode `site`** |
| Téléchargement et dépouillement des agendas | **0 $** — c'est du Python |
| Sélection des liens | ~0,005 $ par agenda |
| Lecture d'une sortie | ~0,006 $ par sortie |
| Lecture d'un programme entier | ~0,04 $ pour une page de 30 000 caractères, quel que soit le nombre de sorties qu'on en tire |

Soit de l'ordre de **0,20 $ pour un run complet de vingt sorties**. Aucun appel
n'ayant d'outil hormis la recherche, il n'y a plus de boucle serveur, donc plus
de contexte refacturé — c'est un changement de mécanisme, pas un réglage.

`max_cost_usd` (1 $ par défaut) arrête le run avant un appel payant s'il est
dépassé ; ce qui a déjà été trouvé est conservé dans le JSON. Le journal
totalise jetons, recherches et coût, par étape.

Pour mémoire, les mesures des versions précédentes : 3,24 $ avec Opus 5 et des
pages de 30 000 jetons, 2,35 $ avec Sonnet 5 — dans les deux cas, la boucle
serveur refacturant le contexte accumulé à chaque itération.

Où part cet argent poste par poste, quelles économies restent à faire sans rien
changer au modèle, et ce que remplacer Haiku par un **modèle maison**
demanderait vraiment : [`docs/scraper-anatomie.html`](../docs/scraper-anatomie.html),
puis [`docs/fabriquer-le-modele.html`](../docs/fabriquer-le-modele.html) pour la
marche à suivre. Rien n'a été implémenté dans ce sens ; ces documents disent
seulement ce que ça coûterait et ce que ça rapporterait.

## Et ensuite

1. un déclenchement périodique des configurations (le worker sait déjà exécuter
   ce qu'on lui met en file ; il manque qui l'y met, et quand) ;
2. un fournisseur OpenRouter — l'interface `Provider` (trois méthodes) est déjà
   en place pour ça, et seule la recherche y demande un outil ;
3. un second script en liste blanche, alimenté par les domaines dont les
   sorties ont été le plus souvent approuvées.
