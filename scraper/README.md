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
| `SERPER_API_KEY` | facultative — le moteur de recherche, pour les configurations en `provider: serper` **et** pour le repli de l'attribution, quel que soit le fournisseur |

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

Il sert aussi **trois autres files**, celles du banc d'évaluation
(`POST /api/eval/harvest/next`, `/eval/reading/next` et `/eval/extraction/next`)
— voir « [Le banc
d'évaluation](#le-banc-dévaluation) ». Les recherches passent d'abord : une
recherche produit des sorties que des parents attendent, un agenda du banc
attend un humain qui le relira quand il pourra. Et l'extraction passe en
dernier, pour une raison de plus : c'est la seule file du banc qui dépense de
l'argent.

Une exécution est close **quoi qu'il arrive**, y compris sur un plantage :
sans clôture elle resterait « En cours » dans la console, et bloquerait toute
nouvelle exécution de la même configuration.

Encore faut-il que le site réponde. Il ne répond pas toujours — un
déploiement le redémarre — et une clôture perdue ne se rattrapait pas : la
ligne restait « En cours » pour toujours. Deux filets, désormais :

- le worker **réessaie sa clôture** trois fois, à deux, quatre puis huit
  secondes d'intervalle ; c'est la durée d'un redémarrage de l'API ;
- le site **ferme d'office** une exécution dont il n'a plus aucune trace —
  ni journal, ni page — depuis trente minutes. Le seuil est large parce qu'un
  appel au modèle peut rester muet un quart d'heure ; une demi-heure de
  silence complet, elle, ne s'explique par aucun travail en cours. Le ménage
  se fait au passage du worker et au moment de lancer une recherche.

Ces deux filets ne se remplacent pas : le premier garde les compteurs et le
verdict du run, le second ne sait que constater le décès.

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

### Les huit étages, et où ils sont dans le code

Le pipeline a longtemps eu six étages, mais ils ne vivaient que dans cette
documentation : le code les enchaînait sans les nommer, dans trois fonctions
qui en portaient deux chacune. Ils ont désormais **une classe et un fichier
par brique**, leur vocabulaire commun dans
[`sortiesbot/stages/__init__.py`](sortiesbot/stages/__init__.py), et chaque
étage s'ouvre explicitement avec `log.stage(...)` :

| # | Étage | Qui travaille | Reçoit | Rend | Où |
|---|---|---|---|---|---|
| 1 | Découverte | modèle | des requêtes web | les URL qu'elles ont remontées | `stages/discovery.py` — `Discovery` |
| 2 | Reconnaissance | **mixte** | une URL trouvée | sa nature : agenda, sortie ou programme, et l'adresse retenue | `stages/identification.py` — `Identification` |
| 3 | Dépouillement | Python | URL d'agenda | liens et leur contexte | `stages/harvest.py` — `Harvest` |
| 4 | Sélection | modèle | liens numérotés | numéros retenus | `stages/selection.py` — `Selection` |
| 5 | Lecture | Python | URL de page | texte, dates JSON-LD, image | `stages/reading.py` — `Reading` |
| 6 | Extraction | modèle | texte de la page | fiche(s) JSON | `stages/extraction.py` — `Extraction` |
| 7 | Attribution | **mixte** | une fiche et la page qui la portait | l'URL de la source, vérifiée | `stages/attribution.py` — `Attribution` |
| 8 | Publication | Python | fiche JSON | sortie en attente de modération | `stages/publication.py` — `Publication` |

La **reconnaissance** est arrivée avant-dernière, d'un constat : la découverte
classait les pages parce que le fournisseur savait le faire au passage, pas
parce que c'était sa place. La nature d'une page est une propriété de la page,
pas de la façon dont on l'a trouvée. En la sortant de là, la découverte se
réduit à « des requêtes entrent, des URL sortent » — le seul contrat qu'un
moteur de recherche ordinaire sait honorer, et donc la condition pour en
brancher un autre un jour.

Elle est **mixte** : gratuite tant qu'un signal certain tranche, facturée
quand ils se taisent tous. L'attribution, arrivée après, l'est pour la même
raison — voir « [Remonter à la source](#remonter-à-la-source) ».

Aucune brique ne sait ce qui vient avant ou après elle : l'ordre n'existe qu'à
un seul endroit, [`sortiesbot/orchestrator.py`](sortiesbot/orchestrator.py),
et plus précisément dans une seule méthode, `Run.chain()`. Les huit appels s'y
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
          7  attribution                   1 fois par fiche
          8  publication                   1 fois par fiche
```

`chain()` ne contient rien d'autre que ces huit appels et les branchements qui
décident de la suite. Ce qui tranche *si* une page est lue — doublons du run,
plafond de sorties, budget — est en amont, dans `_to_read()` ; l'intendance du
run — catégories du site, comptes finaux, ouverture et clôture du journal —
est groupée à part, dans `go()`. Sans ce partage, la chaîne se lisait coupée
en trois par des décisions qui ne la concernaient pas.

Elles n'ont **pas** de signature commune, et c'est délibéré : ces cardinalités
diffèrent, et une interface uniforme aurait fait croire à une chaîne de huit
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

**Une page suivante n'est pas un agenda de plus.** C'est le même agenda, plus
loin : elle ne consomme rien du plafond `max_agendas`, qui compte des sources,
et elle ne crée pas de branche dans l'arbre de la console. Elle coûte un
téléchargement, et c'est tout ce qu'elle est. Deux compteurs le disent plutôt
qu'un :

| Compteur | Ce qu'il compte | Où il se lit |
|---|---|---|
| `pages` | pages téléchargées, suivantes comprises | « pages téléchargées » sur l'exécution |
| `next_pages` | celles qui n'étaient pas la première d'un agenda | « dont N suivante(s) » |
| `agendas` (la différence) | agendas réellement ouverts | « agendas dépouillés », et les statistiques |

Et le journal l'annonce, ligne par ligne, parce qu'une dépense qu'on ne voit
pas est une dépense qu'on ne règle pas :

| Événement | Ce qu'il dit |
|---|---|
| `next_page` | l'URL de la page suivante, son rang, les liens déjà récoltés et le plafond en vigueur — donc *pourquoi* elle est demandée |
| `harvested` (rang > 1) | ce que cette page-là a réellement apporté (`new`) et le cumul de l'agenda |
| `stage_end` du dépouillement | « N lien(s) extrait(s) sur 3 page(s) : la première et 2 page(s) suivante(s) » |

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
« Journal détaillé et graphe des étages ». Elle dessine les huit briques avec
leurs compteurs, puis trois onglets : l'**arbre** du run, la **source** —
c'est-à-dire la mesure de l'étage 7, décrite plus bas — et le journal
filtrable. Le journal se filtre par étage (en cliquant une brique), par type
d'événement, par gravité, par page suivie, ou par texte libre. Les filtres se
composent et se retirent un par un.

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

### Remonter à la source

Une recherche remonte surtout des **agrégateurs** — kidiklik, citizenkid,
parismômes, familyinparis. C'est normal et c'est même utile : ils indexent
tout, ils sont bien référencés, ils sortent en tête. Mais un atelier du musée
Rodin n'est pas une information de kidiklik ; c'est une information du musée
Rodin, que kidiklik republie. Le parent qui clique veut les horaires du jour,
la billetterie, l'annulation pour cause de grève — donc la page du musée.

L'étage 7 répond à cette question, une fois par fiche : **existe-t-il une page
de l'organisateur, et laquelle ?** Il ne touche à rien d'autre.

#### Une liste commune, et non un champ par recherche

La liste des agrégateurs a été, un temps, un champ libre de chaque
configuration. C'était une erreur de niveau : kidiklik republie, que la
recherche qui l'a trouvé cherche des spectacles ou des ateliers de vacances.
Recopier la même quinzaine de domaines dans chaque recherche, c'était se
garantir qu'un jour l'une d'elles serait oubliée — et qu'une sortie sortirait
avec l'adresse de l'agrégateur pour seule source, sans que personne sache
pourquoi.

Elle vit donc dans la table `Aggregator`, tenue depuis **Recherche auto →
Agrégateurs**, et le serveur la joint à la configuration qu'il envoie au
worker. Le scraper, lui, n'a pas changé de contrat : il reçoit toujours
`aggregatorDomains`, et ignore d'où la liste vient. Une ligne décochée reste
en base — on saura qu'elle avait été écrite, et pourquoi elle ne s'applique
plus.

Chaque recherche ne garde qu'une décision, une case à cocher :
`block_aggregators`. Décochée (le défaut), les agrégateurs sont lus, puis
l'étage 7 remonte à l'organisateur. Cochée, ils rejoignent les domaines
bloqués : la recherche les exclut et aucune de leurs pages n'est ouverte.
C'est renoncer aux agendas les mieux fournis du web francophone — à réserver
aux recherches qui veulent du premier ressort.

Les **domaines bloqués**, eux, ne se règlent plus du tout par recherche.
Facebook, Instagram, TikTok sont illisibles pour tout le monde : c'est un fait
du web, pas une préférence, et la liste appartient au scraper
(`DEFAULT_BLOCKED_DOMAINS`).

Deux champs plutôt qu'un, et le partage compte :

| Champ envoyé au site | Ce qu'il porte | Qui le lit |
|---|---|---|
| `sourceUrl` | le **meilleur lien connu** — l'organisateur si on l'a trouvé, la page lue sinon | le parent, sur la fiche |
| `foundOnUrl` | la page réellement lue, quand elle diffère | le modérateur, la console |
| `sourceUrlSignal` | ce qui a désigné le premier | le modérateur, pour la confiance |

`sourceUrl` **ne change pas de rôle**, et c'est ce qui a rendu ce chantier
petit côté site : aucun de ses lecteurs — la fiche, le formulaire, un futur
export — n'a eu à apprendre un second champ. Une sortie déjà en base garde un
lien qui reste vrai, simplement moins bon que ce qu'on sait faire depuis.

#### La cascade

La même que celle de `classify.py`, et pour la même raison : chaque signal
gratuit qui tranche est un appel payant qu'on ne fait pas.

| # | Signal | Ce qu'il lit | Confiance | Coût |
|---|---|---|---|---|
| 1 | **JSON-LD** | `Event.url`, `sameAs`, `offers.url` de la page lue | certain | nul |
| 2 | **Domaine du lieu** | « Musée Rodin » ↔ `musee-rodin.fr` dans les liens sortants | certain | nul |
| 3 | **Texte du lien** | « site officiel », « réserver », « en savoir plus » | probable | nul |
| 4 | **Le moteur** | une requête Serper, titre + lieu | probable | ~0,001 $ |

Les trois premiers lisent le HTML que le `Fetcher` garde déjà depuis la
lecture : ni un octet de réseau, ni un jeton. Ils s'appuient sur
`outbound_links` et `json_ld_urls`, exacts **compléments** de `links_of` — qui
écarte tous les liens sortants, parce que sur un agenda ce sont des
partenaires et de la publicité. Sur la fiche d'un agrégateur, c'est au
contraire le seul endroit où figure l'organisateur : ce qui est du bruit pour
le dépouillement est ici le signal.

Le quatrième est le seul appel payant de l'étage, et le seul qu'on puisse
couper (`source_search: false`, ou la case de la console). Il n'est atteint que
lorsque la page ne cite tout simplement pas sa source, ce qui arrive
constamment. Sa requête est le **titre et le lieu**, pas « site officiel » : on
cherche cette page-là, et l'ajouter ferait remonter la racine d'un site qui ne
parle de rien.

Le moteur du repli est **indépendant du fournisseur de la recherche** : une
configuration qui cherche avec `anthropic` remonte quand même à la source, dès
lors que `SERPER_API_KEY` est dans l'environnement. C'est ce qui a fait sortir
la mécanique HTTP de `serper_provider.py` vers `providers/serper_client.py` —
deux appelants, deux politiques, un seul client.

#### La validation, qui n'est pas optionnelle

Aucun des quatre signaux ne prouve quoi que ce soit. Un lien « réserver » mène
souvent à l'accueil d'une billetterie ; un résultat de moteur peut être le bon
site et la mauvaise saison. Une source fausse est **pire** qu'une source
absente : elle a l'air d'une réponse, le modérateur la croit, et le parent
tombe sur un spectacle qui n'existe plus.

La page candidate est donc **ouverte et lue** avant d'être retenue, et elle
doit parler de cette sortie :

* son **titre** s'y retrouve, à 60 % de ses mots significatifs — un titre est
  presque toujours reformulé d'un site à l'autre, exiger la phrase exacte
  reviendrait à ne jamais rien valider ;
* à défaut, son **lieu et une de ses dates** : c'est la preuve du programme de
  festival, qui ne nomme pas chaque atelier comme l'agrégateur.

Ce qui ne passe pas est journalisé avec l'URL écartée et le signal qui l'avait
proposée, puis jeté. `SourceLink.found` n'est vrai que si `checked` l'est :
la règle est portée par l'objet, pas par la discipline de l'appelant.

Les chercheurs **proposent**, la vérification **dispose** : chacun rend toutes
les candidates qu'il voit, et c'est l'épreuve qui tranche. Sans ça, un premier
lien plausible mais faux ferait perdre le bon, qui était deux lignes plus bas.
Quatre pages ouvertes au plus, tous signaux confondus — au-delà, on paie en
secondes de politesse ce qu'on ne trouvera pas.

#### Le rejouer sur une sortie, à la demande

Cet étage ne tournait qu'au fil d'une recherche. Une sortie déjà publiée dont
le lien pointe sur kidiklik y restait donc pour toujours : le modérateur qui le
voyait n'avait rien d'autre à faire que de chercher à la main, et la fiche
gardait l'agrégateur.

La fiche porte maintenant un bouton **« Chercher la source »**, visible des
seuls modérateurs, qui met en file une exécution d'un seul étage — le
septième. Elle part de la page réellement lue (`foundOnUrl`, sinon
`sourceUrl`), rejoue la cascade et la vérification à l'identique, et le site
écrit ce qu'elle a rapporté :

* trouvée et **vérifiée** : `sourceUrl` devient la page de l'organisateur, la
  page de départ descend dans `foundOnUrl`, et `sourceUrlSignal` dit lequel des
  quatre signaux a tranché ;
* rien de vérifié : **la fiche ne bouge pas**. Le journal de l'exécution, lui,
  dit ce qui a été essayé — c'est exactement ce que l'onglet « Source » de la
  page de débogage montre, pour cette exécution comme pour une autre.

Côté code, c'est une **seconde porte d'entrée** de l'orchestrateur,
`run_source()`, écrite à côté de `run()` pour la raison qui fait exister ce
fichier : c'est le seul endroit qui décide de ce qui s'exécute, et une chaîne
d'un maillon se lit mieux à côté de celle qui en a huit. La brique, elle, est
la même — un test qui passerait pour la recherche de source et pas pour
l'étage 7 dirait qu'on a dupliqué la règle.

Côté site, une telle exécution est une `ScraperRun` **sans configuration** :
elle n'explore rien, elle n'a donc ni thème, ni zone, ni période. C'est la
sortie qu'elle porte (`eventId`) qui dit au worker de ne jouer que
l'attribution — un champ, pas un mode de plus. Tout le reste lui est commun
avec une vraie recherche : le journal renvoyé au fil de l'eau, le graphe des
étages, la page de débogage, la clôture et les compteurs.

#### Où il perd, et comment le voir

Le graphe dit que l'étage a été traversé onze fois en douze secondes. Il ne dit
pas ce qu'on veut savoir quand il déçoit : **où il perd**. Ne rien proposer et
proposer quatre pages fausses sont deux pannes opposées, qui se corrigent à
deux endroits opposés du code — et le journal plat les affiche pareil, quelques
lignes noyées dans mille.

L'onglet « Source » de la page de débogage range donc le journal de l'étage en
trois questions (`server/src/lib/scraperAttribution.ts`) :

| Ce qu'il montre | Ce que ça répond |
|---|---|
| l'entonnoir — fiches vues, creusées, candidates ouvertes, sources retenues | l'étage s'est-il seulement déclenché ? Il ne creuse que sur un agrégateur **connu**, et un run où « creusées » vaut zéro n'a pas un problème de cascade mais de liste |
| le rendement de chaque signal — ouvertes, retenues, écartées, injoignables | quel signal propose sans jamais tenir. Le plafond de quatre candidates est commun : un mauvais signal ne coûte pas que du temps, il fait perdre les suivantes |
| les motifs d'abandon, groupés | la phrase exacte que la brique a rendue — « aucun résultat vérifiable pour … », « recherche de source désactivée », « budget atteint » |

S'y ajoutent les listes qu'on relit à l'œil : les candidates ouvertes puis
écartées, avec le signal qui les avait proposées, et les sources retenues, avec
ce qui les a vérifiées. Chaque ligne ouvre le journal filtré sur la piste de sa
page.

Et surtout **le rendement du moteur**, qui manquait. Les résultats refusés par
le tamis — un autre agrégateur, un réseau social, le site de la page lue — ne
laissaient aucune trace : `_by_search` passait au suivant sans rien dire. Une
recherche où le moteur n'avait rien trouvé et une recherche où il avait tout
rendu et tout fait refuser s'affichaient donc à l'identique, c'est-à-dire pas
du tout. Ce sont pourtant deux pannes opposées : la première tient à la
requête, la seconde au tamis.

Deux événements comblent ce trou, et eux seuls suffisent à trancher :

| Événement | Ce qu'il porte | Ce qu'il permet de dire |
|---|---|---|
| `moteur interrogé` | le nombre de résultats rendus | zéro alors qu'une requête est partie : l'organisateur n'a probablement pas de page à lui |
| `résultat écarté` | l'URL et le motif du refus — « agrégateur (infolocale.fr) », « domaine bloqué », « déjà le site de la page lue » | quatre résultats, quatre agrégateurs : le web ne connaît que des republications |

Le refus est journalisé **au moteur seulement**, pas dans les trois signaux
gratuits : sur la fiche d'un agrégateur, ceux-ci passent au tamis des dizaines
de liens sortants dont on sait d'avance qu'ils seront refusés, et les
journaliser noierait le reste.

Rien n'est calculé par le scraper pour cette page : tout est relu du journal
tel qu'il est déjà écrit — les événements `attribution`, et le `stage_end` de
l'étage. Une exécution d'hier se mesure donc comme une de demain, sans avoir
rien à relancer.

#### Ce que cet étage ne fait pas

Il ne demande **jamais une URL au modèle**. C'est la règle que la publication
applique déjà à la photo — « une URL de sa part est au mieux une devinette » —
et elle vaut ici davantage : une URL inventée qui répond en 200 est
indétectable. Toute adresse qui sort de là a été lue dans un HTML ou rendue
par un moteur.

Il ne touche pas non plus à la **mémoire** : `store` reste indexé sur la page
lue, qui est celle qu'un prochain run retrouvera. Indexer sur la source
attribuée serait la meilleure clé de déduplication — le même atelier trouvé
via kidiklik *et* via citizenkid est une seule sortie, ce que
`event_key(page_url, title)` ne peut pas voir — mais cela se décidera sur des
chiffres, quand le registre en aura assez. Le sujet `attribute` s'y accumule
dès maintenant, avec le signal, la candidate et son verdict.

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

### Le banc d'évaluation

> **Le banc a été scindé en trois.** Ce qui suit décrit ce qu'il mesure et
> pourquoi, et reste juste. Ce qui a changé, c'est *où* les choses vivent :
>
> * le **corpus** — une entrée gelée et ce qu'un humain dit qu'elle contient.
>   Il ne dépend d'aucun modèle et vit des années. L'étiquette dit désormais ce
>   que la page *contient* (« la page annonce 8 € ») et non si une brique a eu
>   raison (« le tarif rendu est juste ») : la première vaut pour toujours, la
>   seconde périmait au premier changement de prompt ;
> * un **run** — ce qu'une brique, à sa version du jour, rend sur ce corpus.
>   Immuable, empilé, jamais écrasé, et il déclare de quoi il est le run (SHA,
>   modèle, empreinte du prompt, réglages) ;
> * la **mesure** — la confrontation des deux, calculée à la demande et
>   stockée nulle part.
>
> Le mélange n'était pas une gêne d'architecture : rejouer un agenda
> supprimait ses pages, donc en cascade les verdicts humains qu'elles
> portaient. Mesurer détruisait la mesure, et « est-ce que ça s'améliore ? » —
> la seule question pour laquelle un banc existe — restait sans réponse.
>
> Trois conséquences visibles : `reviewed` n'existe plus (une étiquette existe
> parce qu'un humain l'a posée, son absence dit qu'il n'a pas regardé),
> `hasReference` non plus (une proposition est un run qu'on affiche), ni
> `pageMoved` (un run rejoue sur l'entrée gelée, jamais sur le web
> d'aujourd'hui). La console est en deux pages : **Corpus et étiquettes**, et
> **Mesures**.


Le registre ci-dessus mesure la **reconnaissance** en la laissant tourner. Le
banc répond à l'autre question, celle qu'aucune observation passive ne peut
atteindre : **ce que le pipeline a manqué.**

Le déséquilibre est structurel. Une fausse sortie remonte au modérateur, qui la
refuse — l'erreur est vue, corrigée, et *étiquetée*. Une vraie sortie écartée à
l'étage 3 ou 4 n'est vue par personne, jamais ; elle ne produit même pas une
ligne de regret. La précision a le filet de la modération, le rappel n'en a
aucun.

Le banc s'ouvre donc par le **dépouillement**, et l'ordre n'est pas arbitraire :

* il est **en amont** — un lien que `links_of` n'a pas vu est perdu pour les
  cinq étages suivants, et aucun modèle en aval ne le rattrape ;
* il est **déterministe, ce qui ne veut pas dire juste**. `links_of` rend les
  mêmes liens à chaque fois ; ça ne dit rien de savoir si ce sont les bons. Une
  fonction peut être fiablement fausse ;
* et **sa panne se déguise en panne de l'étage 4**. Un agenda dont les liens de
  fiche ont été perdus rend son menu ; la sélection n'en retient rien, avec un
  `dropped_reason` parfaitement sensé ; et c'est le prompt de la sélection qu'on
  ira retoucher pour un bug de sélecteur.

#### Comment ça marche

La console est à `/admin/evaluation`, réservée aux **administrateurs** — le banc
fabrique la vérité de référence sur laquelle les mesures s'appuieront, et une
vérité que plusieurs mains modifient sans se concerter n'en est plus une.

On y donne un agenda réel et un nombre de pages. L'agenda part en file ; le
worker le réclame comme il réclame une exécution
(`POST /api/eval/harvest/next`), télécharge les pages avec le `Fetcher` du
scraper — donc `robots.txt` et le délai par hôte — et appelle
[`evaluation.harvest_agenda()`](sortiesbot/evaluation.py), qui n'est qu'une
enveloppe autour du **vrai** `links_of`.

C'est le point qui commande tout le reste, et il demande d'être précis :

* **la fonction est partagée** avec la production — `links_of` est importée
  telle quelle, avec ses seuils et son plafond. Refaire l'extraction côté site
  donnerait la vérité d'une réimplémentation, c'est-à-dire aucune ;
* **l'orchestration ne l'est pas.** L'étage 3 fait davantage qu'appeler
  `links_of` : il journalise, tient les compteurs du run, dédoublonne entre
  pages, et s'arrête dès que sa moisson suffit. Le banc a sa propre boucle,
  délibérément plus bête. **On mesure la fonction, pas la brique.**

Ce module n'a pas non plus le droit de « corriger » quoi que ce soit au
passage — il appelle et rapporte. Compléter est le travail de l'humain.

#### Le corpus est gelé, pour de bon

Chaque page part avec son **HTML gzippé**, écrit sur le disque du serveur. Sans
lui, le banc ne mesurerait `links_of` qu'à un instant donné : rejouer la mesure
après l'avoir modifié obligerait à retélécharger, donc à comparer un nouveau
code à une nouvelle page — et l'écart ne dirait plus lequel des deux a bougé.

`GET /api/eval/pages/:id/html` rend cette page telle qu'elle a été servie. Une
page injoignable ou démesurée est rapportée **sans** son archive : la mesure
est le travail, l'archive est le confort du rejeu, et on ne perd pas la
première pour avoir manqué la seconde. La console dit quelles pages ne sont pas
archivées.

#### La brique précoche, l'humain corrige

Le banc relève **tous** les liens de la page, pas seulement ceux que le
dépouillement a retenus, et ce que la brique en a fait devient une
**précoche** : retenu, donc proposé comme « sortie » ; écarté, donc proposé
comme « autre ». Il ne reste qu'à corriger ce qui est faux, et ce sont ces
corrections-là qui sont la mesure.

Ne montrer que la moisson obligeait à retrouver les manqués soi-même, en
rouvrant la vraie page : lent, et incomplet par construction — on ne trouve que
ce qu'on a pensé à chercher. Et surtout ça ne disait rien du contraire.

**La précoche vient de la fonction, jamais d'une relecture de ses règles.**
`evaluation.audit_links()` appelle le vrai `links_of` et se sert de sa réponse ;
le motif du rejet, lui, est reconstitué à côté. Une erreur dans ce
raisonnement-là fausserait un libellé, jamais la mesure — et un test le vérifie
terme à terme.

#### Les quatre verdicts

Il en faut **quatre**, parce que trois ne suffisent pas à décrire ce qu'un
agenda contient :

| Verdict | Ce que c'est | Ce que le pipeline en fait |
|---|---|---|
| **sortie** | mène à la fiche d'un événement | ce que l'étage 4 doit garder |
| **pagination** | la page 2, 3… du même agenda | suivie, mais seulement en `rel="next"` |
| **sous-agenda** | une **autre** liste de sorties | **rien** |
| **autre** | navigation, mentions légales, partage | correctement écarté |

`SOUS_AGENDA` est le cas que personne ne comptait, et il est partout : « voir
aussi les sorties en château », « les sorties gratuites ». Ces pages à facettes
portent d'autres sorties sans être la page suivante. Le dépouillement les rend,
le prompt de sélection lui dit d'écarter « les liens de navigation, de catégorie
ou de pagination » — donc le modèle les jette, et ce qu'elles portent n'est
jamais atteint. Le banc ne corrige pas ce trou : il le chiffre, ce qui est le
premier pas.

#### Les deux erreurs

Le croisement de la précoche et du verdict les donne toutes les deux :

|  | l'humain dit « sortie » | l'humain dit autre chose |
|---|---|---|
| **retenu** | juste | **retenu à tort** — un appel payant pour rien |
| **écarté** | **sortie perdue** | juste |

« Sortie perdue » est la plus chère, précisément parce qu'elle ne coûte rien :
elle ne consomme aucun jeton, ne produit aucune ligne de journal, et personne
ne la voit jamais.

Car l'étage 3 n'est pas un pur extracteur. `links_of` **filtre déjà** : hors
domaine, texte d'ancre de moins de quinze caractères, chemins de service,
doublons, plafond à deux cents. Le partage avec l'étage 4 est celui-ci —
l'étage 3 retire ce qui n'est *certainement pas* une fiche, gratuitement et par
des règles ; l'étage 4 décide lesquelles des restantes correspondent au thème, à
la zone et à la période, et c'est un jugement, donc facturé.

Ce préfiltrage est légitime — il raccourcit l'appel payant. Mais il a sa propre
balance, et un lien qu'il écarte n'atteint jamais l'étage 4. Les erreurs de
l'étage 4 laissent une trace, un `dropped_reason` que la console affiche ;
celles de l'étage 3 ne laissent rien.

Chaque rejet part d'ailleurs avec **son motif** — « texte trop court », « hors
domaine », « chemin de service ». Il ne décide de rien : il sert à ranger les
rejets dans la console, parce que les sorties perdues se concentrent sous deux
motifs et jamais sous les autres. La console offre aussi de trancher un motif
entier d'un clic ; l'outil coupe dans les deux sens, et ne touche jamais les
liens retenus.

Et **tous** les liens partent avec leur contexte, écartés compris. Une première
version le réservait aux retenus, au motif que c'est ce que l'étage 4 reçoit :
l'argument était juste et la conséquence absurde. Le contexte ne sert pas ici à
l'étage 4, il sert à l'humain pour juger — et il manquait très exactement là où
il est indispensable, puisqu'un lien écarté pour « texte trop court » est par
définition un lien dont l'intitulé ne dit rien. Sans lui, la console affichait
des URL nues, impossibles à trancher sans les ouvrir une par une.

Formellement, avec `retenus∩sorties` l'intersection des deux :

```
précision     = retenus∩sorties / retenus      ce que l'étage 4 veut, sur ce qu'il reçoit
dont utiles   = retenus non-« autre » / retenus  ce qui mène quelque part, bruit exclu
rappel        = retenus∩sorties / sorties      les vraies sorties que la brique a vues
```

**Deux précisions, parce qu'une seule accuse la mauvaise brique.** Compter tout
ce qui n'est pas une sortie comme une faute du dépouillement est injuste : un
sous-agenda retenu mène bien quelque part — vers d'autres sorties — et c'est
l'étage 4 qui le jette, parce qu'on lui dit d'écarter les catégories. Une
pagination retenue mène à la suite de la liste. « Précision » mesure donc le
couple 3+4 et dit ce qu'on paie ; « dont utiles » mesure l'étage 3 seul et dit
s'il sait reconnaître un lien qui compte.

**Rien n'est dédoublonné entre pages** : un lien présent sur les pages 1 et 2
compte deux fois, parce que `links_of` l'a vu deux fois.

#### Ce qu'un humain a tranché, et ce que la brique a deviné

L'import pose déjà un verdict sur chaque lien — la précoche. C'est ce qui rend
la relecture rapide, et c'était un piège : rien ne distinguait « la machine a
deviné *autre* » de « un humain a confirmé *autre* ».

Constaté sur un vrai agenda : on pouvait valider en n'ayant relu que les
soixante-trois liens retenus, et le rappel affichait **100 %**. Non pas parce
que le dépouillement n'avait rien raté, mais parce que personne n'avait regardé
les soixante-seize autres. Le dénominateur du rappel — les liens qu'un humain
appelle « sortie » — ne peut pas être juste si une partie des liens n'a jamais
été lue.

D'où la colonne `reviewed`, posée au premier clic humain, et la règle qui en
découle : **la validation exige que tout ait été tranché.** Ce n'est pas de la
rigidité, c'est la condition pour que les taux veuillent dire quelque chose. Le
filtre « À revoir » liste ce qui reste, et l'action de groupe permet d'expédier
un motif entier.

Les taux ne s'affichent **qu'une fois l'extraction validée** — donc une fois
tout relu. Avant, ils ne diraient que « personne n'a encore regardé ».

#### Parcourir les pages fait partie du travail, donc en rater est une erreur

L'étage 3 ne se contente pas de lire une page : **il suit la pagination**. Un
agenda pour lequel on demande deux pages et dont une seule est lue est donc un
ratage, au même titre qu'une sortie perdue.

Et il ne se voyait nulle part : la deuxième page n'existait simplement pas dans
l'arbre, sans un mot. Deux compteurs le disent maintenant.

**`pages lues / demandées`**, tout de suite, sans attendre l'humain — avec le
motif de l'arrêt, dérivé de ce qu'on garde déjà :

| Ce qu'on constate sur la dernière page lue | Motif |
|---|---|
| elle porte une erreur de lecture | `injoignable` — ce n'est pas la brique qu'il faut accuser |
| pas de `rel="next"` | `sans_suite` — la brique n'a pas su désigner la suivante |
| un `rel="next"` vers une page déjà lue | `boucle` — cet agenda tourne en rond |

**`pagination ratée`**, une fois la page relue : des liens que l'humain appelle
« pagination » sur une page où `next_page()` n'a rien trouvé. Le site offrait
une suite, la brique ne l'a pas vue.

#### Le verdict de pagination est au niveau de la page

Il ne se déduit **pas** des étiquettes posées sur les liens, et une première
version qui essayait posait une question sans réponse possible.

`next_page()` lit le `rel="next"` des `<a>` **et** des `<link>` du `<head>`.
Quand l'URL vient d'un `<link>`, ce n'est pas un lien de la page : elle
n'apparaît dans aucune ligne, et l'étiqueter « pagination » était donc
impossible. La console demandait de vérifier quelque chose qui n'existait nulle
part. Et même sur un `<a>`, rien ne permettait de dire « vérifié, ce n'est pas
la suite » : le bandeau restait rouge indéfiniment.

D'où le même principe que pour les liens — la brique constate, l'humain
tranche — avec trois réponses, parce que savoir qu'elle s'est trompée ne dit
pas comment :

| Verdict | Ce qu'il dit |
|---|---|
| **correct** | ce qu'elle a trouvé, ou n'a pas trouvé, est juste |
| **suite ratée** | il y avait une suite, elle ne l'a pas vue |
| **fausse suite** | elle a trouvé une page qui n'est pas la suite |

Les deux derniers ouvrent un champ facultatif : **l'adresse de la vraie page
suivante**. C'est ce qu'il faut pour réparer — savoir que la brique s'est
trompée ne dit pas ce qu'elle aurait dû trouver, et une poignée de ces adresses
dira tout de suite si `next_page()` doit apprendre à lire une pagination
numérotée.

Le bandeau **s'abstient tant que rien n'est tranché** : affirmer « cette page
est la dernière » avant que quiconque ait regardé serait exactement
l'affirmation gratuite que ce banc existe pour éviter. Et la validation exige un
verdict sur chaque page, comme elle exige que chaque lien ait été relu.

#### Deux choix qui ne vont pas de soi

**Un nombre de pages fixe**, là où l'étage 3 en suit *tant qu'il manque de
liens*. Ce sont deux questions distinctes : « ce site a-t-il des liens que je ne
sais pas voir ? » se répond sur une page fixée, « fallait-il ouvrir la page 3 ? »
est un arbitrage de budget qui se juge sur un run entier et son coût. Le banc
répond à la première, et vérifie à part que la pagination est d'une forme
suivable.

**Pas de dédoublonnage entre pages.** `links_of` travaille page par page, et
c'est page par page que la vérité s'établit. Fusionner ferait disparaître la
moitié du travail qu'on cherche à noter — et masquerait le cas le plus
instructif, celui de la page 2 qui ne rend rien alors que la page 1 va bien.

Relancer une analyse efface aussi les ajouts manuels, et il n'y a pas d'autre
choix honnête : ils disaient « `links_of` a manqué ceci **sur cette page telle
qu'elle était** », la page vient d'être retéléchargée, et les garder les
rattacherait à un HTML qu'ils n'ont jamais décrit.

### Le banc de lecture — l'étage 5

Le même principe, sur l'autre étage gratuit. L'étage 3 se mesure sur des
**agendas**, celui-ci sur des **fiches** : ce ne sont pas les mêmes pages, donc
pas le même corpus.

L'étage 5 lit **trois fois** un même HTML — le texte qui part au modèle, les
dates JSON-LD, l'illustration — et en tire une décision : sous
`MIN_PAGE_CHARS`, la page est **abandonnée** avant le moindre appel payant.
`evaluation.read_page()` rejoue les trois lectures avec les fonctions de
production, et **l'échange de langue avec** : c'est lui qui décide *quelle* page
est lue, et l'oublier ferait mesurer une autre page que celle que le pipeline
aurait choisie.

#### Trois verdicts plutôt qu'un

Parce que les trois se ratent séparément et ne se réparent pas au même endroit.

| Aspect | Réponses | Ce que la faute accuse |
|---|---|---|
| **texte** | correct · amputé · tronqué · hors sujet | la liste des balises décapées · le plafond de caractères · la mauvaise page |
| **illustration** | correcte · logo du site · mauvaise · manquante | le tamis des images |
| **dates** | correctes · incomplètes · fausses · manquantes | la lecture du JSON-LD |

Un verdict unique les mélangerait et ne pointerait rien.

#### Les signaux, et le premier d'entre eux

Comme les motifs de rejet de l'étage 3, ce sont des **libellés** : la brique a
déjà rendu ce qu'elle rend, et c'est ce rendu qu'on mesure. Ils disent seulement
où regarder.

Le plus utile de loin : **le titre de la page ne se retrouve pas dans le texte
extrait.** `page_text` décape `nav header footer aside form`, et beaucoup de
gabarits mettent le titre et les dates dans un `<header>`, l'encadré pratique
dans un `<aside>`. Ils partent avec, le texte reste non vide, rien ne proteste —
et c'est l'extraction qu'on ira accuser de rendre une fiche sans date.

Les trois autres : texte **au plafond** (la fin n'atteindra jamais le modèle),
**sous le seuil** (la page serait abandonnée — le ratage le plus cher, et le
seul que la brique décide toute seule), et une adresse d'illustration qui
**ressemble à un logo**.

#### Rien n'est précoché en base

À l'étage 3 il le fallait : cent trente-neuf liens ne se tranchent pas un par
un, et il a fallu ensuite une colonne `reviewed` pour distinguer ce qu'un humain
avait dit de ce que la machine avait deviné. Ici il y a **trois clics par
page** : la console met en avant ce que la brique prétend, mais rien de cette
proposition n'est écrit. Un verdict nul veut dire « personne n'a encore
regardé », sans ambiguïté et sans colonne de plus.

La validation exige les trois : valider en n'ayant jugé que le texte produirait
un taux d'illustration calculé sur des pages que personne n'a regardées — le
même mensonge que le rappel à 100 % de l'étage 3.

#### Peupler le banc avec ce que le pipeline a déjà fait

Deux paniers, et **l'équilibre entre eux est la question de ce banc**.

| Panier | D'où | Ce qu'il apporte |
|---|---|---|
| **approuvées** | `ScraperRunItem` `decision='submitted'` dont la sortie est `APPROVED` | des pages où l'étage 5 a réussi — et la **vérité de référence** de l'étage 6 |
| **abandonnées** | `ScraperRunItem` `decision='invalid'` avec `reason='page vide ou illisible'` | le **point aveugle** : la brique a dit non, personne n'a jamais vérifié |

Une sortie approuvée est, par construction, une page dont le texte était
lisible : sinon elle ne serait jamais devenue une sortie. Peupler le banc avec
elles seules mesurerait la brique sur ses propres succès — on lirait 96 % de
textes corrects, et ça ne voudrait rien dire. C'est le rappel à 100 % de l'étage
3 sous un autre déguisement. La console affiche donc le mélange, et prévient
quand il ne contient que des succès.

**Pourquoi `ScraperRunItem` et pas `Event.sourceUrl`.** Parce que `sourceUrl` a
pu être réécrit par l'étage 7 : quand l'attribution a remonté de l'agrégateur au
site du musée, il désigne une page que le pipeline n'a **jamais lue**.
`ScraperRunItem.url` est l'adresse réellement ouverte, après l'échange de langue.

**Ce qui n'entre dans aucun panier :** les erreurs réseau (`decision='error'`).
Une page injoignable ce jour-là est un fait du web, pas un jugement de la brique,
et elle répond peut-être aujourd'hui.

Le motif `page vide ou illisible` est une chaîne littérale de
`stages/reading.py`, et le couplage est à connaître : s'il changeait côté
scraper, le panier se viderait en silence. C'est pourquoi la route rend toujours
le compte disponible — un panier vide se voit dans la console.

**La fiche approuvée est du contexte ici, pas un verdict.** Les trois questions
de l'étage 5 portent sur ce que la page *contient* ; la fiche dit ce que la
sortie *est*. Confondre les deux fabriquerait des taux qui ne mesurent pas ce
qu'ils annoncent. Elle est affichée en regard du texte parce qu'elle aide à
juger, et c'est tout.

### Le banc d'extraction — l'étage 6

Le premier étage mesuré qui **coûte**. Et celui qui produit tout ce dont la
fiche vit : `setting` (intérieur / extérieur), l'âge, le tarif, les horaires, le
lieu, la catégorie. L'étage 5 ne rend qu'un texte ; tout le reste est lu dedans
par le modèle.

Trois choses le distinguent des deux étages précédents, et toutes les trois
tiennent au fait que c'est un appel de modèle.

#### 1. L'entrée est le texte de l'étage 5, jamais la page

`evaluation.extract_page()` reçoit le texte que le banc de lecture a archivé, et
appelle le vrai `provider.extract` dessus. Retélécharger mêlerait deux mesures :
une fiche sans tarif dirait aussi bien « le modèle ne l'a pas vu » que « l'étage
5 l'avait déjà emporté avec un `<aside>` ». Le banc de lecture a mesuré cela
séparément, et l'a déjà dit — c'est pour ça qu'il vient avant.

Conséquence pratique : on ne met au banc d'extraction qu'une page **déjà lue et
au-dessus du seuil**. Une page que l'étage 5 aurait abandonnée n'atteint jamais
l'extraction dans le pipeline, et la mesurer ici mesurerait un appel qui n'a
pas lieu.

Un seul appel, en mode **page unique**. Le mode programme pose une autre
question — non pas « les champs sont-ils justes ? » mais « le découpage est-il
le bon ? » — qui est une mesure de segmentation, avec ses propres taux. Ce que
le banc mesure quand même, c'est la **décision** qui y mène : `several` est le
premier aspect jugé.

#### 2. Champ par champ, jamais fiche par fiche

Une fiche « fausse » ne dit pas quel champ a lâché, donc ne dit pas quoi
réparer. `audit_fiche()` découpe la fiche en **douze aspects** — les vingt-trois
colonnes du schéma regroupées par *fait* : `free` et `price` sont un seul
tarif, `age_min` et `age_max` un seul âge, les trois colonnes d'adresse une
seule adresse. Les juger séparément compterait deux fois la même erreur.

Quatre verdicts par aspect, et le croisement avec « le modèle a-t-il rempli ce
champ ? » donne les trois taux :

|                | la page le dit  | la page n'en dit rien |
|----------------|-----------------|-----------------------|
| **renseigné**  | JUSTE ou FAUX   | **INVENTE**           |
| **vide**       | **MANQUE**      | JUSTE (vide à raison) |

* **exactitude** = juste / (juste + faux + inventé) — parmi les valeurs qu'il a
  osé écrire, la part juste ;
* **couverture** = juste / (juste + faux + manqué) — parmi ce que la page
  offrait, la part rapportée juste. C'est le rappel, et c'est le seul chiffre
  qui demande vraiment un humain : il faut avoir lu la page pour savoir que
  l'information y était ;
* **invention** = inventé / renseigné. La faute propre à un modèle, celle
  qu'aucun code déterministe ne commet. La ranger sous « faux » cacherait le
  seul chiffre qui dit si le prompt tient le modèle.

#### 3. Trois instruments gratuits, avant le premier clic

Aucun ne coûte d'étiquette, et à eux trois ils désignent la plupart des fautes.

| Instrument | Ce qu'il vérifie | Aspects couverts |
|---|---|---|
| **ancrage** | la valeur se retrouve-t-elle dans le texte ? | titre, description, tarif, âge, dates, jours, horaires, lieu, adresse |
| **cohérence** | la fiche se contredit-elle toute seule ? | âge (min > max), tarif (gratuit *et* payant), dates (fin avant début), code postal |
| **accord** | les dates rencontrent-elles celles du JSON-LD de l'étage 5 ? | dates |
| **référentiel** | la catégorie existe-t-elle sur le site ? | catégorie |

L'ancrage d'un **nombre** exige son voisinage : un tarif de 8 € ne compte pour
ancré que près d'un `€` ou d'un « euro », un âge de 3 ans près d'un « ans » ou
d'un « à partir de ». Sans ça, n'importe quel texte assez long ancre n'importe
quel petit entier, et l'instrument ne dirait plus rien. Les **dates** sont
cherchées sous toutes leurs écritures françaises — « 3 août », « 03/08/2026 »,
« 2026-08-03 » — sinon toute date correctement lue serait déclarée inventée.

Une exception est codée en dur, et elle est réglementaire : le prompt impose de
mettre *aujourd'hui* en date de début quand la page n'annonce qu'une fin
(« jusqu'au 23 octobre »). Cette date-là n'est pas dans la page, et la signaler
accuserait le modèle d'avoir suivi sa consigne.

Comme ailleurs au banc, ce sont des **libellés, pas des verdicts** : ils disent
où regarder d'abord, ce qui est beaucoup quand douze aspects sur trente fiches
font trois cent soixante décisions dont l'écrasante majorité est « juste ». D'où
le bouton « le reste est juste », qui balaie ce qu'**aucun** instrument n'a
signalé — et seulement cela. Balayer aussi les aspects signalés annulerait le
seul travail que les instruments font, et rendrait la mesure indiscernable de
« personne n'a rien lu ».

#### Ce qu'aucun instrument ne sait faire

`setting` — intérieur ou extérieur — n'a **aucun** ancrage possible. Une page ne
l'écrit presque jamais : elle dit « au parc de la Villette » ou « salle
Jean-Vilar », et c'est le lecteur qui conclut. C'est l'aspect qui coûtera
toujours une étiquette humaine, et le banc l'annonce (`instrument: "aucun"`)
plutôt que d'imaginer une heuristique qui donnerait l'illusion d'une mesure.

La `description` est dans un entre-deux : c'est une reformulation, jugée sur le
**vocabulaire** — une description dont la moitié des mots longs sont absents de
la page n'a pas été tirée d'elle.

#### La fiche approuvée comme vérité de référence

Approuver, sur ce site, veut dire qu'un modérateur a vérifié **chaque champ**.
Une sortie approuvée n'est donc pas une précoche de plus : c'est une étiquette
humaine déjà payée, et elle tranche l'étage 6 gratuitement — y compris `setting`,
le seul aspect qu'aucun instrument n'atteint.

Quand la page du banc en porte une, `propose_verdicts()` compare champ par champ
et **propose** un verdict, avec la valeur approuvée citée dans le motif : sans
elle, il faudrait rouvrir la fiche publiée pour trancher, ce que la référence est
justement censée épargner.

Elle propose, elle n'écrit pas. Rien n'entre dans `verdicts` sans qu'un humain
ait cliqué — c'est le même invariant qu'à l'étage 3, où la précoche de `links_of`
est restée séparée de ce qu'un humain avait tranché. La console offre un bouton
« confirmer la fiche approuvée » : un clic, et c'est un acte humain.

Deux champs restent sans proposition, délibérément :

* **la description** est une reformulation. Deux paraphrases différentes de la
  même page sont toutes les deux justes ;
* **`several`** — la référence est *une* sortie tirée de cette page, elle ne dit
  rien de ce qu'il y en avait d'autres.

Un troisième cas ne propose rien mais s'explique : la fiche approuvée est vide et
l'ancrage retrouve pourtant la valeur dans le texte. Les deux instruments se
contredisent, et c'est exactement le cas à montrer à un humain.

**Le garde-fou.** La fiche décrit la page du jour du run ; le banc la relit
aujourd'hui, et le pipeline n'archive aucun HTML d'époque. Si le titre approuvé
ne se retrouve plus dans le texte, ce n'est plus la même page : toutes les
propositions sont retirées (`pageMoved`), parce qu'elles accuseraient le modèle
d'un changement du site. La console affiche par ailleurs l'ancienneté de la
lecture — plus l'écart est grand, moins un désaccord accuse la brique.

**Et le chiffre à garder sous les yeux :** combien de verdicts n'ont fait que
*confirmer* la référence, contre combien l'ont *corrigée*. Une mesure entièrement
confirmative reste vraie — un humain a cliqué — mais elle dit surtout que le
modèle et le modérateur sont d'accord, ce qui est plus faible qu'une relecture
indépendante. Les renseignements sont dans les corrections.

#### Le prix de la mesure

Une extraction = un appel. Le compte rendu porte les jetons et le coût, et la
console les additionne : taire le prix donnerait l'impression que cette
mesure-ci est gratuite comme les deux précédentes. C'est aussi pourquoi la file
d'extraction passe **en dernier** dans le worker, derrière les recherches, les
agendas et les lectures — tout ce qui est gratuit passe avant.

La console permet de mettre en file **toutes** les fiches lisibles d'un coup
(`POST /api/eval/extractions/all`), et c'est le seul geste du banc dont la
dépense suit le nombre de pages : d'où la confirmation, qui annonce le compte
avant de partir. Le serveur reste seul juge de ce qui est éligible — lu,
au-dessus du seuil, pas déjà extrait — et rend combien de lignes ont réellement
été créées, qui peut être moins que ce que la console annonçait si une page a
été extraite depuis un autre onglet entre-temps.

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

### La version française d'une page

Un moteur remonte volontiers l'adresse anglaise d'un site pourtant
francophone : le musée, le théâtre ou l'office de tourisme publie les deux, et
c'est parfois `/en/` qui est le mieux indexé. La sortie proposée était alors
correcte, mais son lien menait à une page anglaise alors que la française
existait juste à côté.

Le problème a deux moitiés, et les deux se règlent sans le modèle.

**Même adresse, deux versions.** Beaucoup de sites servent la page dans la
langue que le visiteur demande. Le `Fetcher` la demande donc :
`Accept-Language: fr-FR,fr;q=0.9,en;q=0.3`. Sans cet en-tête, un robot est
souvent servi en anglais par défaut.

**Une adresse par langue.** C'est le rôle de
[`sortiesbot/language.py`](sortiesbot/language.py). Trois signaux, du plus
fiable au moins sûr :

1. `<link rel="alternate" hreflang="fr">` — la traduction déclarée par le site
   lui-même, donc la réponse de celui qui la connaît ;
2. l'adresse — `/en/`, `/en-GB/`, `en.exemple.fr`, `?lang=en` se transposent ;
3. la langue du texte, quelques mots outils suffisant à séparer le français de
   l'anglais.

Le troisième ne fabrique jamais d'adresse : il **vérifie** un candidat proposé
par les deux premiers. Une transposition n'est retenue que si la page obtenue
répond *et* est réellement en français — beaucoup de sites répondent à `/fr/`
en servant l'anglais quand la traduction n'existe pas, et changer d'adresse
pour le même contenu ne tromperait que nous.

Le remplacement a lieu à trois étages, et les trois comptent :

* à la **reconnaissance** (2), parce qu'un agenda anglais ne mène qu'à des
  fiches anglaises : corriger la racine corrige toute la branche ;
* à la **lecture** (5), parce que c'est l'adresse retenue là qui devient la
  provenance (`foundOnUrl`) — et parce qu'un lien peut avoir échappé au
  premier passage ;
* à l'**attribution** (7), parce que c'est de là que sort le lien réellement
  publié quand une source est trouvée. L'organisateur publie souvent en deux
  langues, et un `sameAs` ou un résultat de moteur ramasse volontiers son
  `/en/`. La bascule y a lieu **avant** la vérification : la page contrôlée
  doit être celle qui sera publiée, et le contrôle porte justement sur un
  titre et des dates écrits en français.

Les deux filtres de la lecture — domaine bloqué, page déjà vue — se rejouent
sur l'adresse retenue : c'est elle qui sera mémorisée, sans quoi une sortie
déjà proposée reviendrait à chaque run par sa porte anglaise.

Rien de tout cela ne coûte une requête sur une page française : la question ne
se pose que si la page se déclare dans une autre langue, si son adresse
l'annonce, ou si le site déclare une traduction française. Une page anglaise
sans jumelle est lue quand même — mieux vaut une sortie en anglais que pas de
sortie — et le journal le dit (`no_french`).

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
