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

**Règle absolue** : chaque URL que tu renvoies doit provenir d'un résultat de
recherche ou d'une page que tu as ouverte pendant ce tour. N'écris jamais une
adresse de mémoire, même si elle te semble évidente : les sites réorganisent
leurs pages, une URL mémorisée est presque toujours morte, et elle sera
rejetée.

Procède dans cet ordre :
1. Commence par lancer $max_searches recherches web — tu en as le quota,
   sers-t'en entièrement — en changeant les formulations et en couvrant les
   différents départements de la zone. Une seule requête ne ramène qu'une
   seule bulle de résultats. Sans recherche, ta réponse est inutilisable.
2. Ouvre ensuite jusqu'à $max_fetches des pages remontées, en choisissant les
   agendas et les « que faire ce week-end » : les liens qu'ils contiennent
   mènent aux sorties qu'aucune recherche ne remonte directement.
3. Ce qu'on attend en sortie, ce sont les URL de pages décrivant UNE sortie
   précise — un événement, un lieu, un spectacle. Les liens relevés à
   l'intérieur des agendas que tu viens d'ouvrir sont exactement ça. Une page
   de liste, une billetterie générique ou un article qui compile dix idées
   n'en est pas une.

Renvoie au plus $max_events candidats, triés du plus au moins prometteur.
Écarte tout ce qui est hors zone, hors période, payant pour les adultes
seulement, ou manifestement inadapté aux enfants.

Si aucune page d'événement individuelle ne ressort — pages refusées, agendas
peu fournis, résultats hors sujet — ne renvoie pas une liste vide : donne les
meilleures pages **parmi celles que tes recherches ont remontées**, en
expliquant la réserve dans `reason`. Une piste imparfaite se trie ensuite ;
une liste vide ne s'exploite pas.
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
