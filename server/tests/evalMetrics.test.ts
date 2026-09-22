/**
 * La mesure du banc, éprouvée sans base de données.
 *
 * Ce fichier existe parce que `evalMetrics.ts` s'annonçait lui-même comme « la
 * seule partie du banc dont une erreur fausserait silencieusement tous les
 * chiffres » — et n'avait aucun test. Deux fautes y vivaient, invisibles parce
 * qu'un chiffre faux a exactement l'air d'un chiffre :
 *
 *   * la **description** était comparée à la lettre, donc toute paraphrase du
 *     modérateur comptait FAUX — un aspect sur douze perdu à chaque fiche ;
 *   * les **jours de représentation** comparaient les « dimanches » du modèle
 *     aux dates calculées par le site, donc toute sortie récurrente comptait
 *     MANQUÉ.
 *
 * Les tests qui portent la mention « la faute d'hier » sont ceux-là : ils
 * échouent sur le code d'avant. Le reste verrouille les règles dont tout
 * dépend, et dont aucune ne se voit à l'œil nu dans un tableau de bord :
 *
 *   * une clé **absente** de l'étiquette n'est pas une valeur vide. L'une dit
 *     « personne n'a regardé », l'autre « la page n'en dit rien » — et sans
 *     cette dissymétrie une invention devient indiscernable d'un champ jamais
 *     relu ;
 *   * un lien **non étiqueté** sort des dénominateurs au lieu de compter contre
 *     la brique : sinon le banc punit ses propres trous ;
 *   * un lien que le dépouillement n'a **pas soumis** au tri ne compte pas
 *     contre le tri : sinon l'étage 4 paie les fautes de l'étage 3 ;
 *   * une page **plafonnée** sort du rappel : sinon on mesure `max_links`.
 *
 * Exécution : `npm test` (le lanceur de Node, chargé par tsx — aucune
 * dépendance de plus, et c'est délibéré : une mesure qu'on n'ose pas installer
 * est une mesure qu'on n'exécute pas).
 *
 * Le motif du script npm n'est pas entre guillemets, et il ne doit pas l'être :
 * c'est au shell de le développer. Le lanceur de Node 20 ne développe pas les
 * motifs lui-même — il cherche alors un fichier nommé « tests/*.test.ts » et la
 * CI échoue, là où une machine en Node 22 ne voit rien.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  ASPECTS,
  accuracy,
  audienceOf,
  couverture,
  criteresParEtage,
  emptyTally,
  extractScore,
  fold,
  harvestLines,
  harvestScore,
  aspectsDetail,
  readDetail,
  readScore,
  relevanceDetail,
  relevanceOf,
  selectLines,
  selectScore,
  sortieMuette,
  sumHarvest,
  sumSelect,
  verdictAspect,
  verdictOf,
  type FicheRendue,
  type LabelledLink,
  type RunScope,
} from '../src/lib/evalMetrics';

// ═════════════════════════════════════════════════════ le repli des valeurs

test('le repli compare deux écritures de la même chose', () => {
  // Un banc qui compterait « Musée Rodin » et « musee rodin » comme un
  // désaccord mesurerait sa propre sévérité, pas la brique.
  assert.equal(fold('Musée Rodin'), fold('musee   rodin'));
  assert.equal(fold("L'Île-aux-Enfants"), 'l ile aux enfants');
  assert.equal(fold(''), '');
});

test('un champ que le corpus ne porte pas ne rend aucun verdict', () => {
  assert.equal(verdictOf(undefined, 'Le Petit Prince'), null);
});

test('les quatre verdicts d’un champ', () => {
  assert.equal(verdictOf('Le Petit Prince', 'le petit prince'), 'JUSTE');
  assert.equal(verdictOf('Le Petit Prince', 'Le Roi Lion'), 'FAUX');
  // La page n'en dit rien, le modèle a écrit quelque chose.
  assert.equal(verdictOf('', 'Théâtre municipal'), 'INVENTE');
  assert.equal(verdictOf('Théâtre municipal', ''), 'MANQUE');
  // Vide des deux côtés : la brique a eu raison de se taire.
  assert.equal(verdictOf('', ''), 'JUSTE');
});

test('l’exactitude ignore ce que le corpus n’a pas étiqueté', () => {
  assert.equal(accuracy({ ...emptyTally(), JUSTE: 3, FAUX: 1, inconnu: 8 }), 0.75);
  // Aucun champ jugé : `null`, et non zéro — un corpus muet ne doit ni flatter
  // ni accabler.
  assert.equal(accuracy(emptyTally()), null);
});

// ═══════════════════════════════════════════ étage 3 — le dépouillement

const lien = (url: string, verdict: LabelledLink['verdict'] = 'SORTIE'): LabelledLink => ({
  url,
  verdict,
});

test('le dépouillement compte les deux erreurs séparément', () => {
  const labels = [lien('/a'), lien('/b'), lien('/nav', 'AUTRE')];
  const results = [
    { url: '/a', harvested: true },
    { url: '/b', harvested: false },
    { url: '/nav', harvested: true },
  ];

  const score = harvestScore(labels, results);

  assert.equal(score.found, 1);
  // La sortie perdue : le ratage cher, et celui que personne ne voit jamais.
  assert.equal(score.missed, 1);
  // Le bruit : un appel payant à l'étage 4 pour rien.
  assert.equal(score.noise, 1);
  assert.equal(score.recall, 0.5);
  assert.equal(score.precision, 0.5);
});

test('un lien retenu que personne n’a étiqueté est une dette, pas une faute', () => {
  // Le compter comme du bruit accuserait la brique d'un trou du corpus. Il sort
  // donc du dénominateur de la précision, et son nombre s'affiche.
  const score = harvestScore([lien('/a')], [
    { url: '/a', harvested: true },
    { url: '/inconnu', harvested: true },
  ]);

  assert.equal(score.unlabelled, 1);
  assert.equal(score.precision, 1);
});

test('sans sortie étiquetée, le rappel se tait', () => {
  const score = harvestScore([lien('/nav', 'AUTRE')], [{ url: '/nav', harvested: false }]);

  assert.equal(score.recall, null);
  assert.equal(score.precision, null);
});

test('le repli des pages additionne les comptes et recalcule les taux', () => {
  const total = sumHarvest([
    { found: 2, missed: 0, noise: 1, unlabelled: 0, recall: 1, precision: 2 / 3 },
    { found: 1, missed: 1, noise: 0, unlabelled: 2, recall: 0.5, precision: 1 },
  ]);

  assert.equal(total.found, 3);
  assert.equal(total.missed, 1);
  assert.equal(total.unlabelled, 2);
  // Le taux d'ensemble, et non la moyenne des taux — une page de deux liens ne
  // pèse pas autant qu'une page de deux cents.
  assert.equal(total.recall, 0.75);
  assert.equal(total.precision, 0.75);
});

// ═════════════════════════════════════════════ étage 4 — la pertinence

const FENETRE: RunScope = {
  dateFrom: '2026-09-01',
  dateTo: '2026-09-30',
  postalPrefixes: ['75', '93'],
};

test('le public se déduit de l’âge quand personne ne l’a dit', () => {
  assert.equal(audienceOf({ ageMax: 10 }), 'ENFANTS');
  assert.equal(audienceOf({ ageMin: 18 }), 'ADULTES');
  // Rien d'exploitable : on ne devine pas.
  assert.equal(audienceOf({}), null);
  // L'étiquette explicite l'emporte sur la déduction.
  assert.equal(audienceOf({ ageMax: 10, audience: 'ADULTES' }), 'ADULTES');
});

test('un lien qui n’est pas une sortie est hors recherche', () => {
  assert.equal(relevanceOf(lien('/p2', 'PAGINATION'), FENETRE), 'HORS_RECHERCHE');
  assert.equal(relevanceOf(lien('/chateaux', 'SOUS_AGENDA'), FENETRE), 'HORS_RECHERCHE');
});

test('une sortie que personne n’a décrite est indécidable', () => {
  // Le seul silence qui compte : il n'y a rien à quoi comparer, donc rien à
  // conclure — ni pour, ni contre. C'est une dette de corpus, pas un jugement.
  assert.equal(relevanceOf({ verdict: 'SORTIE', sortie: null }, FENETRE), 'INDECIDABLE');
});

test('une sortie occupe une plage, pas un point', () => {
  // Du 15 août au 15 décembre : commencée avant la fenêtre, finie après, donc
  // bien dedans. La juger sur son seul premier jour l'écarterait à tort.
  const aCheval = {
    verdict: 'SORTIE' as const,
    sortie: { dateStart: '2026-08-15', dateEnd: '2026-12-15', postalCode: '75011' },
  };

  assert.equal(relevanceOf(aCheval, FENETRE), 'PERTINENTE');
});

test('hors fenêtre et hors zone s’écartent, chacun pour sa raison', () => {
  const apres = { verdict: 'SORTIE' as const, sortie: { dateStart: '2027-01-10' } };
  const avant = { verdict: 'SORTIE' as const, sortie: { dateStart: '2026-01-10', dateEnd: '2026-02-10' } };
  const ailleurs = {
    verdict: 'SORTIE' as const,
    sortie: { dateStart: '2026-09-10', postalCode: '76600' },
  };

  assert.equal(relevanceOf(apres, FENETRE), 'HORS_RECHERCHE');
  assert.equal(relevanceOf(avant, FENETRE), 'HORS_RECHERCHE');
  assert.equal(relevanceOf(ailleurs, FENETRE), 'HORS_RECHERCHE');
});

test('un concert pour adultes est hors recherche, même dans la fenêtre', () => {
  const adultes = {
    verdict: 'SORTIE' as const,
    sortie: { dateStart: '2026-09-10', postalCode: '75011', ageMin: 18 },
  };

  assert.equal(relevanceOf(adultes, FENETRE), 'HORS_RECHERCHE');
});

test('une sortie décrite qui ne rencontre aucun réglage reste indécidable', () => {
  // Elle est décrite, mais rien de ce qu'elle affirme ne croise ce que ce run
  // demandait : il n'y a pas de quoi trancher, et prétendre le contraire
  // fabriquerait un reproche.
  const muette = { verdict: 'SORTIE' as const, sortie: { postalCode: '' } };

  assert.equal(relevanceOf(muette, {}), 'INDECIDABLE');
});

// ══════════════════════════════════════════════ étage 4 — le tri, mesuré

test('le tri n’est jugé que sur ce qu’on lui a soumis', () => {
  // Une sortie que l'étage 3 avait déjà perdue ne doit pas compter « manquée »
  // pour l'étage 4, qui ne l'a jamais vue : sinon son rappel baisserait chaque
  // fois que le dépouillement s'améliorerait.
  const labels = [
    { ...lien('/vue'), sortie: { dateStart: '2026-09-10', postalCode: '75011' } },
    { ...lien('/jamais-soumise'), sortie: { dateStart: '2026-09-11', postalCode: '75011' } },
  ];
  const results = [
    { url: '/vue', selected: true },
    { url: '/jamais-soumise', selected: null },
  ];

  const score = selectScore(labels, results, FENETRE);

  assert.equal(score.found, 1);
  assert.equal(score.missed, 0);
  assert.equal(score.recall, 1);
});

test('écarter à raison est du travail bien fait, et ça se compte', () => {
  const labels = [
    { ...lien('/concert'), sortie: { dateStart: '2026-09-10', ageMin: 18 } },
    { ...lien('/atelier'), sortie: { dateStart: '2026-09-12', postalCode: '93100' } },
    { ...lien('/nav', 'AUTRE') },
  ];
  const results = [
    { url: '/concert', selected: false },
    { url: '/atelier', selected: true },
    { url: '/nav', selected: true },
  ];

  const score = selectScore(labels, results, FENETRE);

  assert.equal(score.rightlyDropped, 1);
  assert.equal(score.found, 1);
  assert.equal(score.noise, 1);
  assert.equal(score.precision, 0.5);
});

test('sur une page plafonnée, le rappel se tait', () => {
  // Le tri a pris exactement son quota : « écarté à tort » et « tronqué » sont
  // indiscernables du relevé. Un rappel calculé là-dessus mesurerait
  // `max_links`, pas le modèle.
  const labels = [
    { ...lien('/a'), sortie: { dateStart: '2026-09-02', postalCode: '75001' } },
    { ...lien('/b'), sortie: { dateStart: '2026-09-03', postalCode: '75002' } },
    { ...lien('/c'), sortie: { dateStart: '2026-09-04', postalCode: '75003' } },
  ];
  const results = [
    { url: '/a', selected: true },
    { url: '/b', selected: true },
    { url: '/c', selected: false },
  ];

  const score = selectScore(labels, results, { ...FENETRE, maxLinks: 2 });

  assert.equal(score.cappedPages, 1);
  assert.equal(score.recall, null);
  // La précision, elle, reste calculable : ce qu'il a retenu, il l'a retenu de
  // son plein gré, plafond ou pas.
  assert.equal(score.precision, 1);
});

test('le rappel d’un run ignore ses pages plafonnées', () => {
  // Les additionner d'abord ferait rentrer le plafond dans le dénominateur par
  // la porte de derrière : une page où le tri a pris ses huit liens et en a
  // laissé douze compterait douze manquées, alors qu'il n'avait plus le droit
  // d'en prendre un seul.
  const libre = {
    found: 1,
    missed: 1,
    noise: 0,
    unlabelled: 0,
    rightlyDropped: 0,
    undecidable: 0,
    cappedPages: 0,
    recall: 0.5,
    precision: 1,
  };
  const saturee = { ...libre, found: 2, missed: 12, cappedPages: 1, recall: null };

  const total = sumSelect([libre, saturee]);

  assert.equal(total.missed, 13); // affiché : ce qui s'est passé
  assert.equal(total.recall, 0.5); // compté : là où le modèle avait les mains libres
  assert.equal(total.cappedPages, 1);
  assert.equal(total.precision, 1);
});

// ═══════════════════════════════════════════════ étage 5 — la lecture

const LU = {
  text: 'Le Petit Prince au théâtre municipal de Rouen, tous les mercredis à 14h30.',
  imageUrl: 'https://theatre.exemple.fr/affiche.jpg',
  dates: '["2026-08-05","2026-08-12"]',
  truncated: false,
  tooShort: false,
};

test('un texte dont le corpus ne dit rien n’est pas jugé', () => {
  const score = readScore({}, LU);

  assert.equal(score.textOk, null);
  assert.equal(score.imageOk, null);
  assert.equal(score.datesOk, null);
});

test('les fragments attendus disent si le texte porte bien la sortie', () => {
  const bon = readScore({ markers: ['théâtre municipal', 'mercredis'] }, LU);
  const ampute = readScore({ markers: ['théâtre municipal', '12 rue des Arts'] }, LU);

  assert.equal(bon.textOk, true);
  assert.equal(bon.markersFound, 2);
  assert.equal(ampute.textOk, false);
  assert.equal(ampute.markersMissing, 1);
});

test('une illustration et des dates se comparent à ce que la page porte', () => {
  assert.equal(readScore({ image: 'https://theatre.exemple.fr/affiche.jpg' }, LU).imageOk, true);
  // Un logo rendu là où la page porte une affiche.
  assert.equal(readScore({ image: 'https://theatre.exemple.fr/affiche.jpg' }, {
    ...LU,
    imageUrl: 'https://theatre.exemple.fr/logo.png',
  }).imageOk, false);
  // « La page n'en porte pas » est une étiquette de plein droit : sans elle,
  // une image inventée serait indiscernable d'un champ jamais relu.
  assert.equal(readScore({ image: '' }, LU).imageOk, false);
  assert.equal(
    readScore({ declaredDates: ['2026-08-12', '2026-08-05'] }, LU).datesOk,
    true,
  );
  assert.equal(readScore({ declaredDates: ['2026-08-05'] }, LU).datesOk, false);
});

test('les deux signaux qui n’attendent personne restent rendus', () => {
  const score = readScore({}, { ...LU, truncated: true, tooShort: true });

  assert.equal(score.truncated, true);
  assert.equal(score.tooShort, true);
});

// ═══════════════════════════════════════════ étage 6 — la fiche, champ par champ

function aspect(key: string) {
  const found = ASPECTS.find((a) => a.key === key);
  assert.ok(found, `aspect inconnu : ${key}`);
  return found;
}

function verdict(key: string, attendue: FicheRendue, rendue: FicheRendue) {
  return verdictAspect(aspect(key), attendue, rendue);
}

test('un aspect dont le corpus ne porte aucun champ ne rend rien', () => {
  // Personne n'a regardé. Le comparer reprocherait à la brique d'avoir rendu
  // quelque chose sur quoi le corpus se tait.
  assert.equal(verdict('tarif', {}, { free: false, price: 8 }), null);
});

test('les quatre verdicts d’un aspect', () => {
  assert.equal(verdict('titre', { title: 'Le Petit Prince' }, { title: 'le petit prince' }), 'JUSTE');
  assert.equal(verdict('titre', { title: 'Le Petit Prince' }, { title: 'Le Roi Lion' }), 'FAUX');
  assert.equal(verdict('titre', { title: '' }, { title: 'Le Roi Lion' }), 'INVENTE');
  assert.equal(verdict('titre', { title: 'Le Petit Prince' }, { title: '' }), 'MANQUE');
  assert.equal(verdict('titre', { title: '' }, { title: '' }), 'JUSTE');
});

test('deux colonnes qui disent un seul fait ne comptent qu’une faute', () => {
  // `free` et `price` sont un seul tarif : les juger séparément compterait deux
  // fois la même erreur.
  assert.equal(verdict('tarif', { free: false, price: 8 }, { free: false, price: 8 }), 'JUSTE');
  assert.equal(verdict('tarif', { free: false, price: 8 }, { free: true, price: null }), 'FAUX');
  // Un prix perdu alors que la fiche affirme « payant » compte FAUX et non
  // MANQUÉ : `free: false` est une valeur, donc l'aspect est renseigné. Les deux
  // pèsent pareil dans le taux — seul le rangement diffère, et c'est le
  // rangement qu'il faudra revoir si on veut séparer l'oubli de l'erreur.
  assert.equal(verdict('tarif', { free: false, price: 8 }, { free: false, price: null }), 'FAUX');
  // Le vrai MANQUÉ : le run n'a rien rendu du tout sur cet aspect.
  assert.equal(verdict('tarif', { free: true, price: null }, {}), 'MANQUE');
});

test('une sortie gratuite n’a pas de prix, et les deux écritures se valent', () => {
  // « Gratuit » et « gratuit, 0 € » sont la même phrase écrite deux fois. La
  // mesure les comptait FAUX l'une contre l'autre, et le site n'enregistre
  // jamais de prix pour une sortie gratuite : **toute** fiche rendue avec
  // `price: 0` sur une gratuité comptait faux, quel que soit le modèle.
  assert.equal(verdict('tarif', { free: true, price: null }, { free: true, price: 0 }), 'JUSTE');
  assert.equal(verdict('tarif', { free: true, price: 0 }, { free: true, price: null }), 'JUSTE');
  assert.equal(verdict('tarif', { free: true, price: 0 }, { free: true, price: 0 }), 'JUSTE');
});

test('la gratuité ne pardonne le prix que si les deux l’affirment', () => {
  // Un désaccord sur `free` reste un désaccord, et c'est alors le tarif entier
  // qui se juge — prix compris. Sans quoi « gratuit » contre « 8 € » passerait.
  assert.equal(verdict('tarif', { free: true, price: null }, { free: false, price: 8 }), 'FAUX');
  assert.equal(verdict('tarif', { free: false, price: 0 }, { free: true, price: null }), 'FAUX');
  // Et un prix reste jugé quand la sortie est payante des deux côtés.
  assert.equal(verdict('tarif', { free: false, price: 8 }, { free: false, price: 12 }), 'FAUX');
});

test('le détail n’affiche que les champs réellement jugés', () => {
  // Sinon un « juste » porterait deux valeurs différentes côte à côte, et on
  // passerait une heure à chercher l'erreur qui n'existe pas.
  const detail = aspectsDetail({ free: true, price: null }, { free: true, price: 0 });
  const tarif = detail.find((aspect) => aspect.key === 'tarif');
  assert.equal(tarif?.verdict, 'JUSTE');
  assert.ok(!tarif?.rendu.includes('price'), `le prix ne devait pas être montré : ${tarif?.rendu}`);
});

test('un faux qui dit quelque chose n’est pas un vide', () => {
  // `false` et `0` **disent** : gratuit, et zéro an. Les traiter en silence
  // ferait compter MANQUÉ une gratuité correctement lue.
  assert.equal(verdict('tarif', { free: true, price: null }, { free: true, price: null }), 'JUSTE');
  assert.equal(verdict('age', { ageMin: 0, ageMax: 3 }, { ageMin: 0, ageMax: 3 }), 'JUSTE');
});

test('une date se compare à son jour', () => {
  assert.equal(
    verdict(
      'dates',
      { permanent: false, dateStart: '2026-08-03', dateEnd: '2026-08-23' },
      { permanent: false, dateStart: '2026-08-03T00:00:00.000Z', dateEnd: '2026-08-23' },
    ),
    'JUSTE',
  );
});

test('la faute d’hier : une paraphrase de la description n’est pas une faute', () => {
  // Deux reformulations de la même page sont toutes les deux justes. La
  // comparaison à la lettre fabriquait une faute à chaque fiche moissonnée — un
  // aspect sur douze perdu, silencieusement, pour rien.
  const corpus = { description: 'Un spectacle de marionnettes pour enfants au théâtre de Rouen.' };
  const rendue = { description: 'Marionnettes à voir en famille dès 3 ans, au théâtre municipal.' };

  assert.equal(verdict('description', corpus, rendue), 'JUSTE');
});

test('la description se juge quand même sur la présence', () => {
  // C'est tout ce qu'une référence peut trancher, et ce n'est pas rien : une
  // page décrite qui ne rend rien, une page muette qui rend un texte.
  assert.equal(verdict('description', { description: 'Un spectacle.' }, { description: '' }), 'MANQUE');
  assert.equal(verdict('description', { description: '' }, { description: 'Un spectacle.' }), 'INVENTE');
});

test('la faute d’hier : une récurrence se compare après le calendrier', () => {
  // Le corpus porte les dates que le site a calculées ; le modèle rend des
  // « mercredis ». Comparer les deux comptait MANQUÉ toute sortie récurrente —
  // on reprochait à l'étage 6 une conversion qui a lieu deux étages plus loin.
  const corpus = { dates: ['2026-08-05', '2026-08-12', '2026-08-19'] };
  const rendue = {
    weekdays: ['mercredi'],
    dates: [],
    resolvedDates: ['2026-08-19', '2026-08-05', '2026-08-12'],
  };

  assert.equal(verdict('jours', corpus, rendue), 'JUSTE');
});

test('un calendrier qui diverge reste une faute', () => {
  // La correction ne doit pas absoudre : trois mercredis contre vingt et un
  // jours, c'est faux, et ça se voit.
  const corpus = { dates: ['2026-08-05', '2026-08-12', '2026-08-19'] };

  assert.equal(verdict('jours', corpus, { resolvedDates: [] }), 'MANQUE');
  assert.equal(verdict('jours', corpus, { resolvedDates: ['2026-08-06'] }), 'FAUX');
});

test('aucun calendrier des deux côtés est un accord', () => {
  // Liste vide veut dire « tous les jours de la plage » : c'est la convention du
  // site, pas une absence de réponse.
  assert.equal(verdict('jours', { dates: [] }, { resolvedDates: [] }), 'JUSTE');
});

test('un run joué avant le calendrier résolu retombe sur ce qu’il portait', () => {
  // Sa fiche n'a pas la clé : la traiter comme vide compterait MANQUÉ ce que
  // personne n'avait mesuré. Un run d'aujourd'hui, lui, porte toujours la clé.
  const corpus = { dates: ['2026-08-05'] };

  assert.equal(verdict('jours', corpus, { dates: ['2026-08-05'] }), 'JUSTE');
});

test('les jours de la semaine ne sont jugés que si un humain les a étiquetés', () => {
  // L'étiquette reprise d'une sortie publiée porte `dates` mais jamais
  // `weekdays`, que le site ne reçoit pas.
  const repriseDuSite = { dates: ['2026-08-05'] };
  assert.equal(
    verdict('jours', repriseDuSite, { weekdays: ['samedi'], resolvedDates: ['2026-08-05'] }),
    'JUSTE',
  );

  // Saisis à la main, ils comptent.
  const saisi = { dates: [], weekdays: ['mercredi'] };
  assert.equal(verdict('jours', saisi, { weekdays: ['mercredi'], resolvedDates: [] }), 'JUSTE');
  assert.equal(verdict('jours', saisi, { weekdays: ['samedi'], resolvedDates: [] }), 'FAUX');
});

test('le relevé d’une fiche rend les douze aspects, connus ou non', () => {
  const corpus: FicheRendue = {
    relevant: true,
    several: false,
    title: 'Le Petit Prince',
    free: false,
    price: 8,
  };
  const rendue: FicheRendue = {
    relevant: true,
    several: false,
    title: 'Le Petit Prince',
    free: false,
    price: 12,
    setting: 'INDOOR',
  };

  const { tally, byField } = extractScore(corpus, rendue);

  assert.equal(Object.keys(byField).length, ASPECTS.length);
  assert.equal(tally.JUSTE, 2); // le verdict de page, et le titre
  assert.equal(tally.FAUX, 1); // le tarif
  // Neuf aspects dont le corpus ne dit rien — dont `cadre`, que le modèle a
  // rempli. Un trou du corpus, jamais une faute de la brique.
  assert.equal(tally.inconnu, ASPECTS.length - 3);
  assert.equal(byField.cadre, null);
});

// ═══════════════════════════════════════ ce qu'une étiquette couvre

test('la couverture se dérive du code de mesure, pas d’une liste écrite à la main', () => {
  // Deux compteurs écrits à la main ont déjà menti, dont un qui annonçait
  // « 6/6 » sur six champs choisis arbitrairement quand l'étage 6 en juge douze.
  const etiquette: FicheRendue = { dateStart: '2026-09-10', venuePostalCode: '75011', title: 'X' };

  const c = couverture(etiquette, null);

  assert.deepEqual(c.tri, { faits: 2, total: 3 });
  assert.deepEqual(c.lecture, { faits: 0, total: 3 });
  assert.equal(c.extraction.total, ASPECTS.length);
  // Trois aspects touchés : les dates, l'adresse, le titre.
  assert.equal(c.extraction.faits, 3);
});

test('le public compte pour la couverture du tri, qu’il soit dit ou déduit', () => {
  assert.equal(couverture({}, 'ENFANTS').tri.faits, 1);
  assert.equal(couverture({ ageMax: 10 }, null).tri.faits, 1);
});

test('la console reçoit la liste que la mesure applique', () => {
  const etages = criteresParEtage();

  assert.deepEqual(etages.map((e) => e.etage), [4, 5, 6]);
  // Le dénominateur affiché est celui de la mesure : ajouter un aspect à
  // `ASPECTS` déplace le compteur tout seul.
  assert.equal(etages[2].criteres.length, ASPECTS.length);
  assert.ok(etages[2].criteres.every((c) => c.libelle && c.champs.length > 0));
});

// ═══════════════════════════════════ le détail : la ligne qui a fait le chiffre
//
// Un taux du banc est une conclusion. Une conclusion qu'on ne peut pas remonter
// jusqu'à la ligne qui l'a produite ne laisse le choix qu'entre la croire et la
// jeter — et ces tests-ci verrouillent la seule chose qui rende le détail
// digne de foi : **il additionne au total**. Deux comptes séparés, l'un pour
// afficher et l'autre pour expliquer, divergent au premier changement de règle.

test('le détail du dépouillement additionne à son score', () => {
  const labels = [lien('/a'), lien('/b'), lien('/nav', 'AUTRE'), lien('/pied', 'AUTRE')];
  const results = [
    { url: '/a', harvested: true },
    { url: '/b', harvested: false },
    { url: '/nav', harvested: true },
    { url: '/pied', harvested: false },
    { url: '/inconnu', harvested: true },
  ];

  const lignes = harvestLines(labels, results);
  const score = harvestScore(labels, results);
  const compte = (cas: string) => lignes.filter((l) => l.cas === cas).length;

  assert.equal(compte('TROUVEE'), score.found);
  assert.equal(compte('MANQUEE'), score.missed);
  assert.equal(compte('BRUIT'), score.noise);
  assert.equal(compte('SANS_ETIQUETTE'), score.unlabelled);
  // Le lien correctement laissé de côté : du travail bien fait, qu'aucun
  // compteur du dépouillement ne porte, et qui doit quand même se voir.
  assert.equal(compte('ECARTEE_A_RAISON'), 1);
  assert.equal(lignes.length, 5);
});

test('le détail du tri additionne à son score, plafond compris', () => {
  const scope: RunScope = { dateFrom: '2026-09-01', dateTo: '2026-09-30', maxLinks: 1 };
  const labels: LabelledLink[] = [
    { url: '/dedans', verdict: 'SORTIE', sortie: { dateStart: '2026-09-10', ageMax: 8 } },
    { url: '/apres', verdict: 'SORTIE', sortie: { dateStart: '2026-12-10', ageMax: 8 } },
    { url: '/nue', verdict: 'SORTIE' },
    { url: '/jamais-vue', verdict: 'SORTIE', sortie: { dateStart: '2026-09-12' } },
  ];
  const results = [
    { url: '/dedans', selected: true },
    { url: '/apres', selected: false },
    { url: '/nue', selected: false },
    // Jamais soumise au tri : l'étage 3 l'avait déjà perdue.
    { url: '/jamais-vue', selected: null },
  ];

  const { lignes, plafonnee } = selectLines(labels, results, scope);
  const score = selectScore(labels, results, scope);
  const cas = (url: string) => lignes.find((l) => l.url === url)!.cas;

  assert.equal(plafonnee, true);
  assert.equal(cas('/dedans'), 'TROUVEE');
  assert.equal(cas('/apres'), 'ECARTEE_A_RAISON');
  assert.equal(cas('/nue'), 'INDECIDABLE');
  assert.equal(cas('/jamais-vue'), 'NON_SOUMISE');
  assert.equal(lignes.filter((l) => l.cas === 'TROUVEE').length, score.found);
  assert.equal(lignes.filter((l) => l.cas === 'ECARTEE_A_RAISON').length, score.rightlyDropped);
  assert.equal(lignes.filter((l) => l.cas === 'INDECIDABLE').length, score.undecidable);
  // La page est au plafond : la ligne trouvée le porte, sinon le détail
  // montrerait un chiffre que le rappel affiché ne compte pas.
  assert.equal(lignes.find((l) => l.url === '/dedans')!.horsTaux, true);
  assert.equal(score.recall, null);
});

test('la raison nomme ce qui a écarté le lien, et pas seulement qu’il l’est', () => {
  const scope: RunScope = { dateFrom: '2026-09-01', dateTo: '2026-09-30', postalPrefixes: ['75'] };

  // Une raison qui dirait « hors recherche » n'apprendrait rien : c'est la
  // dimension fautive qu'on vient chercher, parce que c'est elle qui se règle.
  const tard = relevanceDetail(
    { verdict: 'SORTIE', sortie: { dateStart: '2026-12-01', ageMax: 6 } },
    scope,
  );
  assert.equal(tard.relevance, 'HORS_RECHERCHE');
  assert.match(tard.raison, /2026-12-01/);

  const ailleurs = relevanceDetail(
    { verdict: 'SORTIE', sortie: { dateStart: '2026-09-10', postalCode: '76600', ageMax: 6 } },
    scope,
  );
  assert.match(ailleurs.raison, /76600/);

  const adultes = relevanceDetail({ verdict: 'SORTIE', sortie: { ageMin: 18 } }, scope);
  assert.match(adultes.raison, /adultes/);

  const nue = relevanceDetail({ verdict: 'SORTIE' }, scope);
  assert.equal(nue.relevance, 'INDECIDABLE');
  assert.match(nue.raison, /aucune sortie n'est attachée/);

  // Et la conclusion reste exactement celle d'avant : le détail explique la
  // mesure, il ne la change pas.
  for (const label of [
    { verdict: 'SORTIE' as const, sortie: { dateStart: '2026-09-10', ageMax: 6 } },
    { verdict: 'AUTRE' as const },
    { verdict: 'SORTIE' as const, sortie: { ageMin: 18 } },
  ]) {
    assert.equal(relevanceDetail(label, scope).relevance, relevanceOf(label, scope));
  }
});

test('la lecture dit quel fragment manque, pas seulement qu’il en manque un', () => {
  const detail = readDetail(
    { markers: ['Atelier modelage', '8 €'], image: 'https://x/affiche.jpg', declaredDates: ['2026-09-10'] },
    {
      text: 'Venez à l’atelier  MODELAGE de la saison',
      imageUrl: 'https://x/logo.png',
      dates: '[]',
      truncated: false,
      tooShort: false,
    },
  );

  assert.deepEqual(detail.fragments.trouves, ['Atelier modelage']);
  assert.deepEqual(detail.fragments.manquants, ['8 €']);
  assert.equal(detail.fragments.verdict, false);
  // Les deux valeurs comparées : « l'image est fausse » sans elles n'indique
  // pas si c'est le logo qui a été pris pour l'affiche.
  assert.equal(detail.image.attendu, 'https://x/affiche.jpg');
  assert.equal(detail.image.rendu, 'https://x/logo.png');
  assert.deepEqual(detail.dates.attendues, ['2026-09-10']);
  assert.deepEqual(detail.dates.rendues, []);
});

test('l’extraction montre les deux valeurs comparées, aspect par aspect', () => {
  const attendue: FicheRendue = { title: 'Le Petit Prince', free: false, price: 8 };
  const rendue: FicheRendue = { title: 'Le Petit Prince', free: false, price: 12, setting: 'INTERIEUR' };

  const aspects = aspectsDetail(attendue, rendue);
  const par = (key: string) => aspects.find((a) => a.key === key)!;

  assert.equal(aspects.length, ASPECTS.length);
  assert.equal(par('titre').verdict, 'JUSTE');
  assert.equal(par('tarif').verdict, 'FAUX');
  // La pièce à conviction : 8 contre 12. Sans elle, « faux » est une
  // accusation sans pièce jointe.
  assert.match(par('tarif').attendu, /8/);
  assert.match(par('tarif').rendu, /12/);
  // Le corpus ne dit rien du cadre : pas de verdict, et l'attendu reste vide
  // plutôt que de se lire comme un vide étiqueté.
  assert.equal(par('cadre').verdict, null);
  assert.equal(par('cadre').attendu, '');
});


test('les deux indécidables ne se confondent pas : rien d’attaché, ou rien d’affirmé', () => {
  const scope: RunScope = { dateFrom: '2026-09-01', dateTo: '2026-09-30', postalPrefixes: ['75'] };

  // Les mêler a coûté cher : la console disait « la sortie n'existe pas » d'un
  // lien dont la sortie était au corpus, et on cherchait à créer ce qui existait
  // déjà. Les deux dettes ne se soldent pas du même geste — l'une en rattachant,
  // l'autre en étiquetant.
  const sansRien = relevanceDetail({ verdict: 'SORTIE' }, scope);
  const attacheeMuette = relevanceDetail({ verdict: 'SORTIE', sortie: {} }, scope);

  assert.equal(sansRien.relevance, 'INDECIDABLE');
  assert.equal(attacheeMuette.relevance, 'INDECIDABLE');
  assert.notEqual(sansRien.raison, attacheeMuette.raison);
  assert.match(attacheeMuette.raison, /au corpus/);

  // Une sortie reprise de la modération arrive **avec son public** et sans rien
  // d'autre : elle n'est pas muette, et elle suffit à trancher. C'est ce qui
  // fait qu'un corpus moissonné mesure l'étage 4 dès le premier run, sans
  // attendre que quiconque ait étiqueté quoi que ce soit.
  assert.equal(sortieMuette({ audience: 'ENFANTS' }), false);
  assert.equal(
    relevanceDetail({ verdict: 'SORTIE', sortie: { audience: 'ENFANTS' } }, scope).relevance,
    'PERTINENTE',
  );
  assert.equal(sortieMuette({}), true);
  assert.equal(sortieMuette({ dateStart: '2026-09-10' }), false);
  // « jusqu'à 0 an » est une affirmation, pas un silence : la requête des dettes
  // le testait avec `!ageMax` et rangeait donc cette sortie-là parmi les muettes,
  // quand la mesure, elle, en déduisait « enfants ». Deux listes de champs, deux
  // comptes différents — d'où un seul test, ici, pour les deux.
  assert.equal(sortieMuette({ ageMax: 0 }), false);
});
