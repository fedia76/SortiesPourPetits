"""
Gabarits de prompts par défaut.

Chaque configuration peut les remplacer intégralement (clés `discovery_prompt`
et `extraction_prompt` du YAML) : c'est le point d'entrée pour ajuster la
recherche sans toucher au code. Les variables sont substituées par
`string.Template`, donc elles s'écrivent `$theme` et les accolades JSON du
texte n'ont pas besoin d'être échappées.

Variables disponibles :
  découverte  $theme $area $period $today $date_from $date_to $max_events
              $max_searches $max_fetches
  extraction  $url $today $categories
"""

DISCOVERY = """\
Tu cherches des idées de sorties à faire avec des enfants, pour un site
communautaire francophone.

Recherche demandée : $theme
Zone géographique : $area
Période : $period (du $date_from au $date_to — nous sommes le $today)

Procède ainsi :
1. Lance $max_searches recherches web variées — pas une de plus, c'est un
   quota strict — en changeant les formulations et en couvrant les différents
   départements de la zone. Une seule requête ne ramène qu'une seule bulle de
   résultats.
2. Quand une recherche tombe sur un agenda, un « que faire ce week-end » ou
   une liste d'événements, ouvre la page : les liens qu'elle contient mènent
   souvent à des sorties qu'aucune recherche ne remonte directement. Tu peux
   ouvrir au plus $max_fetches pages, alors choisis-les bien.
3. Privilégie les pages qui décrivent UNE sortie précise (un événement, un
   lieu, un spectacle), pas les pages de liste, les billetteries génériques
   ni les articles de blog qui compilent dix idées.

Renvoie au plus $max_events candidats, triés du plus au moins prometteur.
Écarte tout ce qui est hors zone, hors période, payant pour les adultes
seulement, ou manifestement inadapté aux enfants.
"""

EXTRACTION = """\
Lis la page $url et décris la sortie pour enfants qu'elle présente.

Nous sommes le $today.

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
- `photo_url` : l'URL absolue d'une photo représentative de la page (souvent
  l'image de partage), ou vide.

Ne renseigne que ce que la page dit réellement : un champ inconnu reste vide.
"""
