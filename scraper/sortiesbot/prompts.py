"""Gabarits de prompts par défaut, un par appel du pipeline.

Chaque configuration peut les remplacer intégralement (clés `search_prompt`,
`select_prompt`, `extraction_prompt` du YAML) : c'est le point d'entrée pour
ajuster la recherche sans toucher au code. Les variables sont substituées par
`string.Template`, donc elles s'écrivent `$theme` et les accolades JSON du
texte n'ont pas besoin d'être échappées.

Quatre gabarits, mais jamais plus de trois appels par page — plutôt qu'un
seul appel à qui l'on demanderait de dérouler toute une procédure :

  recherche          $theme $area $period $today $date_from $date_to $max_searches
  classement         $digest
  sélection          $theme $area $date_from $date_to $today $page $max_links
  extraction         $url $today $categories
  extraction (multi) $url $today $categories $theme $max_events

Les deux extractions s'excluent : une page ne porte qu'une sortie (mode
« recherche ») ou plusieurs (mode « site », page de programme d'un festival).

Le schéma de sortie de l'extraction est défini côté fournisseur
(`providers/anthropic_provider.py`) : un champ ajouté ici doit l'être là
aussi, sinon le modèle n'a pas le droit de le renseigner.
"""

SEARCH = """\
Tu prépares une collecte de sorties à faire avec des enfants, pour un site
communautaire francophone.

Recherche demandée : $theme
Zone géographique : $area
Période : $period (du $date_from au $date_to — nous sommes le $today)

Lance $max_searches recherches web variées, en changeant les formulations et
en couvrant les différents départements de la zone. Une seule requête ne
ramène qu'une seule bulle de résultats.

Puis désigne, parmi les résultats obtenus, les pages à ouvrir, en indiquant
pour chacune ce qu'elle est :

- `agenda` : une page qui **liste des événements** — agenda départemental,
  « que faire ce week-end », programmation de saison. On en tirera les liens
  vers les sorties.
- `sortie` : la page d'**une seule sortie précise**, avec son titre, ses
  dates et son lieu. Une recherche en remonte régulièrement, et elles
  comptent autant que les agendas.

Écarte les billetteries généralistes, les annuaires de prestataires pour
fêtes privées, les articles de blog sans dates, et tout ce qui est hors zone.

Ne cherche pas à décrire les sorties maintenant : leur contenu sera lu
séparément. N'écris aucune URL de mémoire — uniquement celles que les
recherches ont remontées.
"""

CLASSIFY = """\
Voici la carte d'identité d'une page web trouvée en cherchant des sorties.

$digest

Cette page est-elle **une sortie** — la fiche d'un événement précis, avec son
titre, ses dates et son lieu — ou **un agenda**, c'est-à-dire une page qui en
liste plusieurs et renvoie vers leurs fiches ?

Deux repères utiles :

- un agenda mène à beaucoup de choses **datées** : c'est ce que dit la ligne
  « dont N voisinent une date » ;
- une fiche a pour titre principal le nom de l'événement lui-même, et ses
  liens mènent à de la navigation ou à des suggestions, rarement datées.

Réponds `inconnu` si le condensé ne permet pas de trancher. C'est une réponse
utile : la page sera traitée comme un agenda, et relue comme une sortie si on
n'en tire rien. Une hésitation coûte donc bien moins qu'une erreur.

En une courte phrase, dis ce qui t'a décidé.
"""

SELECT = """\
Voici les liens relevés sur une page d'agenda de sorties : $page

Recherche en cours : $theme
Zone : $area — période : du $date_from au $date_to (nous sommes le $today)

Chaque ligne donne le texte du lien puis, après « | », le texte qui l'entoure
sur la page — c'est là que se trouvent en général la date et le lieu.

$links

Retiens les numéros des liens qui mènent à la page d'UNE sortie précise
correspondant à la recherche, à la zone et à la période. Au plus $max_links.

Écarte :
- les liens de navigation, de catégorie ou de pagination ;
- les sorties dont le contexte indique clairement une date hors période ;
- les sorties manifestement hors zone ;
- ce qui ne correspond pas au thème demandé.

Dans le doute sur une date ou un lieu que le contexte n'indique pas, retiens
le lien : la page sera lue ensuite et pourra encore être écartée.

Pour chaque lien retenu, donne son numéro et, en quelques mots, ce qui te l'a
fait retenir — « spectacle jeune public, date dans la période », « atelier
enfants au conservatoire ».

Puis, dans `dropped_reason`, une phrase sur ce que tu as écarté et pourquoi —
« la page ne liste que des catégories et de la pagination », « tout est daté
de l'an dernier », « uniquement des concerts pour adultes ». C'est cette
phrase qui permettra de comprendre un tri qui ne retient rien.
"""

EXTRACTION = """\
Voici le contenu de la page $url, telle qu'elle est aujourd'hui, $today.

--- début de la page ---
$content
--- fin de la page ---

Décris la sortie pour enfants que cette page présente.

Règles :
- `relevant` vaut false si la page ne décrit pas une sortie précise adaptée
  aux enfants (page de liste, billetterie, article générique, événement
  terminé, contenu pour adultes) : explique alors pourquoi dans `skip_reason`
  et laisse les autres champs vides.
- `description` : 3 à 6 phrases en français, écrites pour un parent, à partir
  du contenu réel de la page. N'invente rien, ne recopie pas un texte
  publicitaire.
- `venue_address` : l'adresse postale la plus précise que donne la page
  (numéro et rue si elle y est), sans le code postal ni la ville.
- `free` vaut true seulement si l'entrée est gratuite pour tout le monde ;
  sinon donne le tarif enfant le plus courant dans `price`.
- Les dates sont au format AAAA-MM-JJ, les horaires au format HH:MM. Si la
  sortie est ouverte toute l'année, mets `permanent` à true et laisse les
  dates vides.
- Une page qui n'annonce qu'une date de fin — « jusqu'au 23 octobre », « à
  l'affiche jusqu'au 8 novembre » — décrit une sortie **en cours** : mets
  $today dans `date_start` et la date annoncée dans `date_end`. Ne fabrique
  jamais une date de début proche de la fin : « jusqu'au 23 octobre » ne veut
  pas dire « du 22 au 23 octobre ».
- `date_start` et `date_end` bornent la sortie. Mais une sortie ne se tient
  pas forcément tous les jours de cette plage, et c'est ce qui compte pour un
  parent qui cherche une date précise :
  - `weekdays` : les jours où elle a effectivement lieu, quand la page
    l'indique — « tous les dimanches » donne ["dimanche"], « mercredis et
    samedis à 14h30 » donne ["mercredi", "samedi"], « du mardi au dimanche »
    donne les six jours, « relâche le lundi » aussi. Laisse la liste vide si
    la page ne dit rien : cela vaut « tous les jours de la plage ».
  - `dates` : les dates annoncées une à une (« les 3, 7 et 12 août »), au
    format AAAA-MM-JJ. Vide s'il s'agit d'une période continue ou d'une
    récurrence — dans ce cas `weekdays` suffit.
  N'extrapole ni l'une ni l'autre : ne remplis que ce que la page affirme.
- `category` doit être choisie parmi : $categories

Ne cherche pas d'illustration : tu ne reçois que le texte de la page, et son
image est relevée séparément dans le HTML (`harvest.main_image`). Laisse
`photo_url` vide plutôt que de deviner une URL.

Ne renseigne que ce que la page dit réellement : un champ inconnu reste vide.
"""


EXTRACTION_MULTI = """\
Voici le contenu de la page $url, telle qu'elle est aujourd'hui, $today.

--- début de la page ---
$content
--- fin de la page ---

Cette page présente le **programme complet** d'un lieu ou d'un festival :
elle décrit plusieurs sorties à la suite. Relève-les toutes, une fiche par
sortie, dans l'ordre de la page. Au plus $max_events.

Ce qu'on cherche ici : $theme

Ce qui compte, et qui change tout par rapport à la lecture d'une page unique :

- **Une sortie par entrée réellement distincte du programme** — un spectacle,
  un atelier, une exposition, une rencontre. Deux séances du même spectacle
  ne font qu'UNE sortie : réunis-les en une fiche, et mets leurs jours dans
  `dates`.
- Ne découpe pas une sortie en morceaux, et n'en fusionne pas deux qui
  portent des titres différents.
- Si la page n'est en réalité qu'une seule sortie, renvoie une seule fiche.
- Si elle ne décrit aucune sortie exploitable (page d'accueil, billetterie,
  liste de partenaires), renvoie une liste vide et dis pourquoi dans
  `skip_reason`.
- Écarte ce qui ne convient pas à un public d'enfants — soirée, concert pour
  adultes, table ronde professionnelle. Mieux vaut une fiche de moins qu'une
  fiche fausse.

Pour chaque fiche, les règles sont celles de la lecture d'une page unique :

- `description` : 3 à 6 phrases en français, écrites pour un parent, à partir
  du contenu réel de la page. N'invente rien.
- Le programme donne souvent le lieu **une seule fois, en tête ou en pied de
  page**, et les entrées ne répètent que la salle. Reporte alors ce lieu
  commun (`venue_name`, `venue_address`, `venue_city`, `venue_postal_code`)
  dans chaque fiche : une sortie sans adresse n'est pas publiable. Mais ne
  déduis jamais une adresse que la page ne donne nulle part.
- `venue_address` : l'adresse postale la plus précise que donne la page, sans
  le code postal ni la ville.
- `free` vaut true seulement si l'entrée est gratuite pour tout le monde ;
  sinon donne le tarif enfant le plus courant dans `price`. Un tarif annoncé
  pour tout le festival vaut pour chacune de ses sorties.
- Les dates sont au format AAAA-MM-JJ, les horaires au format HH:MM.
- `dates` : les jours où CETTE sortie a lieu, un par un, quand le programme
  les donne — c'est le cas le plus fréquent d'un festival. `date_start` et
  `date_end` bornent alors la sortie ; `weekdays` ne sert que si la page
  annonce une récurrence (« tous les mercredis ») plutôt que des dates.
- Une entrée sans date propre hérite des dates du festival, si la page les
  annonce clairement. Sinon, laisse les dates vides plutôt que de deviner.
- `category` doit être choisie parmi : $categories
- `relevant` vaut true pour chaque fiche que tu renvoies : les entrées
  écartées ne figurent simplement pas dans la liste.

Ne cherche pas d'illustration : tu ne reçois que le texte de la page, et son
image est relevée séparément dans le HTML. Laisse `photo_url` vide.

Ne renseigne que ce que la page dit réellement : un champ inconnu reste vide.
"""
