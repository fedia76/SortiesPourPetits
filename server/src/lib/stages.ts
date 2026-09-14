/**
 * Le vocabulaire des huit étages du scraper, côté site.
 *
 * ## Pourquoi il existe une copie ici
 *
 * La source de vérité est `scraper/sortiesbot/stages/__init__.py`, et elle
 * voyage : l'événement `run_start` porte le graphe complet, si bien qu'une
 * brique renommée dans le scraper est renommée partout sans redéployer le
 * serveur. C'est le chemin nominal, et il ne passe pas par ce fichier.
 *
 * Reste ce que le scraper ne peut pas transporter :
 *
 * * les exécutions dont le `run_start` a été **oublié** — c'est très
 *   exactement ce que fait `DELETE /runs/:id/logs`, et les compteurs, eux,
 *   restent ;
 * * les exécutions antérieures à cet événement ;
 * * les motifs de refus (`lib/rejectionCodes.ts`), qui désignent un étage sans
 *   qu'aucun run soit en jeu.
 *
 * ## Une seule copie, pas trois
 *
 * Il y en avait deux, et elles avaient déjà divergé. Le repli de
 * `routes/scraper.ts` ne comptait que **sept** étages : `attribute` y
 * manquait, donc `indexOf` rendait -1, donc l'étage 7 s'affichait numéro 0,
 * sans libellé, en tête du graphe. Le test de `tests/stages.test.ts` verrouille
 * désormais l'accord avec le fichier Python — c'est peu, mais c'est ce qui
 * manquait pour que la divergence se voie.
 */

/** Un étage, tel que la console le dessine. Mêmes clés que `describe()` en Python. */
export interface StageDescription {
  /** L'identifiant stable, partagé avec le scraper : `identify`, `extract`… */
  stage: string;
  number: number;
  label: string;
  /** Qui travaille, donc qui paie : `modele`, `python`, ou `mixte`. */
  actor: string;
  takes: string;
  gives: string;
}

/**
 * Les huit étages dans l'ordre d'exécution.
 *
 * `actor` vaut « mixte » pour la reconnaissance et l'attribution : elles sont
 * gratuites tant qu'un signal certain tranche, et facturées seulement quand
 * tous se taisent.
 */
export const STAGES: StageDescription[] = [
  {
    stage: 'discovery',
    number: 1,
    label: 'Découverte',
    actor: 'modele',
    takes: 'des requêtes web',
    gives: "les URL qu'elles ont remontées",
  },
  {
    stage: 'identify',
    number: 2,
    label: 'Reconnaissance',
    actor: 'mixte',
    takes: 'une URL trouvée',
    gives: 'sa nature : agenda, ou sortie',
  },
  {
    stage: 'harvest',
    number: 3,
    label: 'Dépouillement',
    actor: 'python',
    takes: "URL d'agenda",
    gives: 'liens et leur contexte',
  },
  {
    stage: 'select',
    number: 4,
    label: 'Sélection',
    actor: 'modele',
    takes: 'liens numérotés',
    gives: 'numéros retenus',
  },
  {
    stage: 'read',
    number: 5,
    label: 'Lecture',
    actor: 'python',
    takes: 'URL de page',
    gives: 'texte, dates JSON-LD, image',
  },
  {
    stage: 'extract',
    number: 6,
    label: 'Extraction',
    actor: 'modele',
    takes: 'texte de la page',
    gives: 'fiche(s) JSON',
  },
  {
    stage: 'attribute',
    number: 7,
    label: 'Attribution',
    actor: 'mixte',
    takes: 'une fiche et la page qui la portait',
    gives: "l'URL de la source, vérifiée",
  },
  {
    stage: 'publish',
    number: 8,
    label: 'Publication',
    actor: 'python',
    takes: 'fiche JSON',
    gives: 'sortie en attente de modération',
  },
];

const BY_ID = new Map(STAGES.map((s) => [s.stage, s]));

/** Les identifiants, dans l'ordre. */
export const STAGE_ORDER: string[] = STAGES.map((s) => s.stage);

/** Un étage par son identifiant, ou `undefined` si le nom n'est pas connu. */
export function stageOf(id: string): StageDescription | undefined {
  return BY_ID.get(id);
}

/**
 * Décrit un étage relevé dans le journal, même inconnu.
 *
 * Un identifiant que ce fichier ignore — une brique ajoutée au scraper avant
 * que le site n'en sache rien — est rendu tel quel plutôt qu'escamoté, et
 * **après** les huit connus : mieux vaut une ligne mal nommée en fin de graphe
 * qu'un étage numéro 0 en tête, ou pas d'étage du tout.
 */
export function describeStage(id: string): StageDescription {
  return (
    BY_ID.get(id) ?? {
      stage: id,
      number: STAGES.length + 1,
      label: id,
      actor: '',
      takes: '',
      gives: '',
    }
  );
}
