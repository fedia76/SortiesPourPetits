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
  const attendue = { title: 'Atelier' } as never;
  const rendue = { title: 'Atelier', setting: 'INDOOR' } as never;
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
    extractScore({ title: 'Le Petit Chaperon rouge' } as never, { title: '' } as never).byField,
  );
  // Le corpus dit que le titre est **vide**, la brique en rend un → INVENTE.
  // Nuance qui compte : une clé absente vaut « non jugé », pas « inventé ».
  cumulerAspects(
    tallies,
    extractScore({ title: '' } as never, { title: 'Navigation du site' } as never).byField,
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
      extractScore({ title: titre } as never, { title: titre } as never).byField,
    );
  }
  assert.equal(ligne(tallies, 'titre').JUSTE, 3);
});

test('une clé absente vaut « non jugé », une clé vide vaut « vide à raison »', () => {
  // La distinction est toute la raison d'être de `inconnu`, et elle ne se lit
  // nulle part ailleurs : les deux cas rendent une fiche vide côté brique.
  const absente = emptyAspectTallies();
  cumulerAspects(absente, extractScore({} as never, {} as never).byField);
  assert.equal(ligne(absente, 'titre').inconnu, 1);
  assert.equal(ligne(absente, 'titre').JUSTE, 0);

  const vide = emptyAspectTallies();
  cumulerAspects(vide, extractScore({ title: '' } as never, { title: '' } as never).byField);
  assert.equal(ligne(vide, 'titre').JUSTE, 1);
  assert.equal(ligne(vide, 'titre').inconnu, 0);
});

test('le cumul ignore une clé qui n’est pas un aspect', () => {
  const tallies = emptyAspectTallies();
  cumulerAspects(tallies, { pasUnAspect: 'FAUX' } as never);
  assert.ok(tallies.every((t) => t.FAUX === 0));
});
