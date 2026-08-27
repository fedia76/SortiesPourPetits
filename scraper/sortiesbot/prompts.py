"""Gabarits de prompts par défaut, un par appel du pipeline.

Chaque configuration peut les remplacer intégralement (clés `search_prompt`,
`select_prompt`, `extraction_prompt` du YAML) : c'est le point d'entrée pour
ajuster la recherche sans toucher au code. Les variables sont substituées par
`string.Template`, donc elles s'écrivent `$theme` et les accolades JSON du
texte n'ont pas besoin d'être échappées.

Trois appels, trois tâches bornées — plutôt qu'un seul appel à qui l'on
demanderait de dérouler toute une procédure :

  recherche   $theme $area $period $today $date_from $date_to $max_searches
  sélection   $theme $area $date_from $date_to $today $page $max_links
  extraction  $url $today $categories
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

Puis désigne, parmi les résultats obtenus, les pages à ouvrir : celles qui
**listent des événements** avec leurs dates — agendas départementaux,
« que faire ce week-end », programmations de saison. Ce sont elles qui
contiennent les liens vers les sorties elles-mêmes.

Écarte les billetteries généralistes, les annuaires de prestataires pour
fêtes privées, les articles de blog sans dates, et tout ce qui est hors zone.

Ne cherche pas à identifier les sorties maintenant : leur contenu sera lu
séparément. Ton seul travail ici est de choisir les bonnes pages d'agenda.
N'écris aucune URL de mémoire — uniquement celles que les recherches ont
remontées.
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

Réponds uniquement avec les numéros retenus.
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
- `category` doit être choisie parmi : $categories
- `photo_url` : l'URL absolue d'une photo représentative si la page en donne
  une, sinon vide.

Ne renseigne que ce que la page dit réellement : un champ inconnu reste vide.
"""
