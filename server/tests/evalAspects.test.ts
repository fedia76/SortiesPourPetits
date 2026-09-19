/**
 * Le décompte aspect par aspect d'un run d'extraction.
 *
 * Le taux d'un run est une moyenne sur douze aspects très différents, et il
 * cache exactement ce qu'on veut savoir : **lequel lâche**. Douze aspects
 * médiocres et onze corrects pour un effondré donnent le même chiffre, et
 * n'appellent pas le même travail.
 *
 * Ce que ce fichier verrouille avant tout, c'est la séparation du **non jugé**.
 * Un aspect que le corpus n'étiquette nulle part n'est pas un aspect raté :
 * le compter comme une faute ferait accuser la brique d'un silence qui n'est
 * pas le sien, et le compter comme une réussite flatterait le taux.
 *
 * Exécution : `npm test`.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  acheverAspectTallies,
  cumulerAspects,
  emptyAspectTallies,
  extractScore,
} from '../src/lib/evalMetrics';

const ligne = (tallies: ReturnType<typeof emptyAspectTallies>, cle: string) => {
  const trouve = tallies.find((t) => t.key === cle);
  assert.ok(trouve, `aspect « ${cle} » absent`);
  return trouve;
};

test('les douze aspects sont là, dans l’ordre, et vides', () => {
  const t = emptyAspectTallies();
  assert.equal(t.length, 12);
  assert.equal(t[0].key, 'verdict');
  assert.deepEqual(
    t.map((a) => a.key).slice(0, 4),
    ['verdict', 'titre', 'description', 'tarif'],
  );
  assert.ok(t.every((a) => a.JUSTE === 0 && a.rate === null));
  // Le libellé voyage avec : la console ne doit pas retenir une seconde table.
  assert.ok(ligne(t, 'tarif').libelle.length > 0);
});

test('un aspect que le corpus n’étiquette pas reste non jugé', () => {
  const tallies = emptyAspectTallies();
  // Le corpus ne dit rien du cadre : **la clé est absente**, pas vide.
  // `setting: undefined` ne suffirait pas — `'setting' in objet` reste vrai
  // dès que la clé existe, et c'est ce test-là que `verdictAspect` applique
  // pour décider entre « vide à raison » et « personne n'a regardé ».
  const attendue = { title: 'Atelier' };
  const rendue = { title: 'Atelier', setting: 'INDOOR' };
  cumulerAspects(tallies, extractScore(attendue, rendue).byField);
  const cadre = ligne(tallies, 'cadre');
  assert.equal(cadre.inconnu, 1);
  assert.equal(cadre.JUSTE + cadre.FAUX + cadre.INVENTE + cadre.MANQUE, 0);
});

test('un aspect non jugé n’a pas de taux, plutôt qu’un taux de zéro', () => {
  const tallies = acheverAspectTallies(emptyAspectTallies());
  assert.equal(ligne(tallies, 'cadre').rate, null);
});

test('le taux d’un aspect ne porte que sur ce qui a été jugé', () => {
  const tallies = emptyAspectTallies();
  const cible = ligne(tallies, 'titre');
  cible.JUSTE = 3;
  cible.FAUX = 1;
  cible.inconnu = 96; // ne doit peser sur rien
  const acheve = acheverAspectTallies(tallies);
  assert.equal(ligne(acheve, 'titre').rate, 0.75);
});

test('un champ manqué et un champ inventé ne se confondent pas', () => {
  const tallies = emptyAspectTallies();
  // Le corpus annonce un titre, la brique rend vide → MANQUE.
  cumulerAspects(
    tallies,
    extractScore({ title: 'Le Petit Chaperon rouge' }, { title: '' }).byField,
  );
  // Le corpus dit que le titre est **vide**, la brique en rend un → INVENTE.
  // Nuance qui compte : une clé absente vaut « non jugé », pas « inventé ».
  cumulerAspects(
    tallies,
    extractScore({ title: '' }, { title: 'Navigation du site' }).byField,
  );
  const titre = ligne(tallies, 'titre');
  assert.equal(titre.MANQUE, 1);
  assert.equal(titre.INVENTE, 1);
  assert.equal(titre.FAUX, 0);
});

test('plusieurs fiches se cumulent sur le même aspect', () => {
  const tallies = emptyAspectTallies();
  for (const titre of ['Atelier', 'Atelier', 'Atelier']) {
    cumulerAspects(
      tallies,
      extractScore({ title: titre }, { title: titre }).byField,
    );
  }
  assert.equal(ligne(tallies, 'titre').JUSTE, 3);
});

test('une clé absente vaut « non jugé », une clé vide vaut « vide à raison »', () => {
  // La distinction est toute la raison d'être de `inconnu`, et elle ne se lit
  // nulle part ailleurs : les deux cas rendent une fiche vide côté brique.
  const absente = emptyAspectTallies();
  cumulerAspects(absente, extractScore({}, {}).byField);
  assert.equal(ligne(absente, 'titre').inconnu, 1);
  assert.equal(ligne(absente, 'titre').JUSTE, 0);

  const vide = emptyAspectTallies();
  cumulerAspects(vide, extractScore({ title: '' }, { title: '' }).byField);
  assert.equal(ligne(vide, 'titre').JUSTE, 1);
  assert.equal(ligne(vide, 'titre').inconnu, 0);
});

test('le cumul ignore une clé qui n’est pas un aspect', () => {
  const tallies = emptyAspectTallies();
  cumulerAspects(tallies, { pasUnAspect: 'FAUX' });
  assert.ok(tallies.every((t) => t.FAUX === 0));
});

test('un tarif jamais trouvé est MANQUÉ, plus FAUX', () => {
  // Le banc lisait « 111 tarifs faux » sur une brique qui, la plupart du
  // temps, n'avait rien trouvé : `free: false` affirmait « ce n'est pas
  // gratuit » là où il n'y avait qu'un silence. Les deux ne se corrigent pas
  // au même endroit — l'un demande de mieux détecter, l'autre de mieux
  // choisir — et le tableau ne les distinguait pas.
  const tallies = emptyAspectTallies();
  cumulerAspects(
    tallies,
    extractScore({ free: false, price: 8 }, { free: null, price: null }).byField,
  );
  const tarif = ligne(tallies, 'tarif');
  assert.equal(tarif.MANQUE, 1);
  assert.equal(tarif.FAUX, 0);
});

test('un tarif trouvé mais faux reste FAUX', () => {
  const tallies = emptyAspectTallies();
  cumulerAspects(tallies, extractScore({ free: false, price: 8 }, { free: false, price: 12 }).byField);
  assert.equal(ligne(tallies, 'tarif').FAUX, 1);
  assert.equal(ligne(tallies, 'tarif').MANQUE, 0);
});

test('un tarif trouvé et juste reste JUSTE', () => {
  const tallies = emptyAspectTallies();
  cumulerAspects(tallies, extractScore({ free: false, price: 8 }, { free: false, price: 8 }).byField);
  assert.equal(ligne(tallies, 'tarif').JUSTE, 1);
});

test('des dates jamais trouvées sont MANQUÉES, plus FAUSSES', () => {
  const tallies = emptyAspectTallies();
  cumulerAspects(
    tallies,
    extractScore(
      { permanent: false, dateStart: '2026-08-03', dateEnd: '2026-08-12' },
      { permanent: null, dateStart: '', dateEnd: '' },
    ).byField,
  );
  assert.equal(ligne(tallies, 'dates').MANQUE, 1);
  assert.equal(ligne(tallies, 'dates').FAUX, 0);
});

test('une sortie permanente reconnue reste JUSTE', () => {
  // `null` ne doit pas casser le cas où la brique se prononce vraiment.
  const tallies = emptyAspectTallies();
  cumulerAspects(tallies, extractScore({ permanent: true }, { permanent: true }).byField);
  assert.equal(ligne(tallies, 'dates').JUSTE, 1);
});

test('un `null` en face d’un booléen du corpus fait échouer l’aspect ENTIER', () => {
  // Le piège, gardé ici parce qu'il a coûté vingt fiches justes d'un coup.
  //
  // `verdictAspect` exige que **tous** les champs d'un aspect concordent. Le
  // corpus porte toujours `permanent` — `isPermanent` est une colonne du site,
  // jamais nulle. Une brique qui répond « je ne me prononce pas » sur ce
  // champ-là fait donc échouer l'aspect même quand ses dates sont parfaites.
  //
  // Dire « inconnu » est honnête quand on ne sait rien. Ça ne l'est plus quand
  // on sait : connaître une plage, c'est savoir que la sortie n'est pas
  // permanente.
  const dates = { dateStart: '2026-08-03', dateEnd: '2026-08-12' };

  const muet = emptyAspectTallies();
  cumulerAspects(
    muet,
    extractScore({ permanent: false, ...dates }, { permanent: null, ...dates }).byField,
  );
  assert.equal(ligne(muet, 'dates').FAUX, 1, 'des dates justes, et pourtant faux');

  const franc = emptyAspectTallies();
  cumulerAspects(
    franc,
    extractScore({ permanent: false, ...dates }, { permanent: false, ...dates }).byField,
  );
  assert.equal(ligne(franc, 'dates').JUSTE, 1);
});

test('une sortie d’un seul jour porte une date de fin des deux côtés', () => {
  // Le site stocke `end = end or start` (`payload._clean_dates`), donc le
  // corpus porte toujours une fin. Rendre une fin vide comptait faux toute
  // sortie d'un jour, quelles que soient ses dates par ailleurs.
  const tallies = emptyAspectTallies();
  cumulerAspects(
    tallies,
    extractScore(
      { permanent: false, dateStart: '2026-08-12', dateEnd: '2026-08-12' },
      { permanent: false, dateStart: '2026-08-12', dateEnd: '' },
    ).byField,
  );
  assert.equal(ligne(tallies, 'dates').FAUX, 1, 'la fin vide ne concorde pas');

  const entier = emptyAspectTallies();
  cumulerAspects(
    entier,
    extractScore(
      { permanent: false, dateStart: '2026-08-12', dateEnd: '2026-08-12' },
      { permanent: false, dateStart: '2026-08-12', dateEnd: '2026-08-12' },
    ).byField,
  );
  assert.equal(ligne(entier, 'dates').JUSTE, 1);
});
