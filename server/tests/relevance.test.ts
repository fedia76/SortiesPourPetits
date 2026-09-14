/**
 * Le classement d'une recherche : ce qui remonte, et pourquoi.
 *
 * C'est le calcul qui décide de ce qu'un visiteur voit en premier, et il
 * n'avait aucun test. Trois mesures s'y mêlent — la précision de l'âge, la
 * brièveté de la période, l'imminence — dont deux dépendent de ce qui a été
 * demandé : les régler « au jugé » se voit sur la page d'accueil et nulle part
 * ailleurs.
 *
 * Les tests portent sur les **rapports** entre les scores, pas sur leurs
 * valeurs absolues : les poids ont vocation à être retouchés, l'ordre
 * d'importance qu'ils encodent non.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  agePrecision,
  brevity,
  imminence,
  rankEvents,
  relevance,
  type Rankable,
} from '../src/lib/relevance';

/** `2026-10-01` → l'instant que Prisma rend pour une colonne DATE. */
function jour(iso: string): Date {
  return new Date(`${iso}T00:00:00.000Z`);
}

let prochainId = 1;

/** Une sortie réduite à ce qui la classe. Tout est facultatif. */
function sortie(champs: Partial<Rankable> = {}): Rankable {
  return {
    id: prochainId++,
    ageMin: null,
    ageMax: null,
    isPermanent: false,
    dateStart: null,
    dateEnd: null,
    ...champs,
  };
}

const proche = (n: number) => (valeur: number) => Math.abs(valeur - n) < 1e-9;

// ──────────────────────────────────────────────────────── la précision de l'âge

test("une tranche d'âge absente vaut « ouvert à tous », donc zéro", () => {
  assert.equal(agePrecision(sortie()), 0);
});

test("une tranche étroite vaut mieux qu'une tranche large", () => {
  const etroite = agePrecision(sortie({ ageMin: 3, ageMax: 5 }));
  const large = agePrecision(sortie({ ageMin: 0, ageMax: 12 }));
  assert.ok(etroite > large);
  assert.ok(proche(1 - 2 / 18)(etroite));
});

test("seule l'étendue compte, pas l'endroit où elle se situe", () => {
  assert.equal(
    agePrecision(sortie({ ageMin: 3, ageMax: 5 })),
    agePrecision(sortie({ ageMin: 12, ageMax: 14 })),
  );
});

test('une borne haute absente ouvre la tranche jusqu’à 18 ans', () => {
  // « à partir de 4 ans » accepte l'enfant sans être pensé pour lui.
  assert.ok(proche(1 - 14 / 18)(agePrecision(sortie({ ageMin: 4, ageMax: null }))));
});

test('une tranche d’un seul âge est la plus précise qui soit', () => {
  assert.equal(agePrecision(sortie({ ageMin: 4, ageMax: 4 })), 1);
});

// ─────────────────────────────────────────────────────────────── la brièveté

test('une sortie d’un seul jour est la plus rare qui soit', () => {
  assert.equal(brevity(sortie({ dateStart: jour('2026-10-01'), dateEnd: jour('2026-10-01') })), 1);
});

test('une semaine vaut la moitié d’une journée — c’est la demi-vie', () => {
  assert.equal(brevity(sortie({ dateStart: jour('2026-10-01'), dateEnd: jour('2026-10-08') })), 0.5);
});

test('une sortie permanente ne finit jamais : brièveté nulle', () => {
  assert.equal(brevity(sortie({ isPermanent: true })), 0);
});

test('des dates manquantes ne se devinent pas', () => {
  assert.equal(brevity(sortie({ dateStart: jour('2026-10-01'), dateEnd: null })), 0);
});

test("c'est la durée de l'affiche qui compte, pas le nombre de représentations", () => {
  // Un spectacle joué tous les dimanches de deux mois reste une offre qui
  // dure deux mois : les jours de représentation n'entrent pas dans `Rankable`.
  const long = brevity(sortie({ dateStart: jour('2026-07-01'), dateEnd: jour('2026-08-31') }));
  const court = brevity(sortie({ dateStart: jour('2026-07-01'), dateEnd: jour('2026-07-02') }));
  assert.ok(long < court);
});

// ────────────────────────────────────────────────────────────── l'imminence

test('une sortie qui commence le premier jour de la fenêtre est imminente', () => {
  assert.equal(imminence(sortie({ dateStart: jour('2026-10-01') }), '2026-10-01'), 1);
});

test('deux semaines plus tard, l’imminence est tombée de moitié', () => {
  assert.equal(imminence(sortie({ dateStart: jour('2026-10-15') }), '2026-10-01'), 0.5);
});

test('une sortie déjà commencée a lieu maintenant', () => {
  assert.equal(imminence(sortie({ dateStart: jour('2026-09-01') }), '2026-10-01'), 1);
});

test('une sortie permanente a toujours lieu maintenant', () => {
  assert.equal(imminence(sortie({ isPermanent: true }), '2026-10-01'), 1);
});

test("l'imminence se compte depuis la fenêtre demandée, pas depuis aujourd'hui", () => {
  // Une recherche pour les vacances de février ne doit pas ranger février par
  // ordre d'éloignement de septembre : tout y serait à égalité, très loin.
  const fevrier = sortie({ dateStart: jour('2027-02-10') });
  assert.ok(imminence(fevrier, '2027-02-08') > imminence(fevrier, '2026-09-14'));
});

// ─────────────────────────────────────────────────────────────── le score

test("sans âge demandé, ce critère se tait au lieu de départager au hasard", () => {
  const ciblee = sortie({ ageMin: 3, ageMax: 5, isPermanent: true });
  const ouverte = sortie({ isPermanent: true });
  assert.equal(relevance(ciblee, { from: '2026-10-01' }), relevance(ouverte, { from: '2026-10-01' }));
});

test("avec un âge demandé, la sortie ciblée passe devant", () => {
  const ctx = { age: 4, from: '2026-10-01' };
  const ciblee = sortie({ ageMin: 3, ageMax: 5, isPermanent: true });
  const ouverte = sortie({ isPermanent: true });
  assert.ok(relevance(ciblee, ctx) > relevance(ouverte, ctx));
});

test("l'âge pèse plus que la brièveté, qui pèse plus que l'imminence", () => {
  const ctx = { age: 4, from: '2026-10-01' };
  const base = { isPermanent: false, dateStart: jour('2026-10-01'), dateEnd: jour('2026-10-01') };

  const parfaite = relevance(sortie({ ...base, ageMin: 4, ageMax: 4 }), ctx);
  // Perdre la précision d'âge doit coûter plus cher que perdre la brièveté…
  const sansAge = relevance(sortie({ ...base }), ctx);
  // …et perdre la brièveté plus cher que perdre l'imminence.
  const sansBrievete = relevance(
    sortie({ ageMin: 4, ageMax: 4, dateStart: jour('2026-10-01'), dateEnd: jour('2027-10-01') }),
    ctx,
  );
  const sansImminence = relevance(
    sortie({ ageMin: 4, ageMax: 4, dateStart: jour('2027-10-01'), dateEnd: jour('2027-10-01') }),
    ctx,
  );

  assert.ok(parfaite - sansAge > parfaite - sansBrievete);
  assert.ok(parfaite - sansBrievete > parfaite - sansImminence);
});

/**
 * Ces deux tests fixent l'arbitrage réel entre « fait pour lui » et « ne
 * repassera pas », et ils ne disent pas la même chose selon qu'un âge a été
 * demandé ou non.
 *
 * Attention en retouchant les poids : l'en-tête du module annonce qu'« une
 * sortie tout public d'un seul jour peut passer devant une sortie très ciblée
 * qui dure deux mois ». Ce n'est vrai que **sans âge demandé** — avec
 * `WEIGHT_AGE = 6`, une tranche étroite l'emporte sur deux mois d'affiche dans
 * tous les cas testés ici. Le second test est donc la règle telle qu'elle
 * s'applique, pas telle qu'elle est racontée.
 */
test("sans âge demandé, la sortie qui ne repassera pas passe devant", () => {
  const ctx = { from: '2026-10-01' };
  const ponctuelle = sortie({ dateStart: jour('2026-10-03'), dateEnd: jour('2026-10-03') });
  const durable = sortie({
    ageMin: 4,
    ageMax: 5,
    dateStart: jour('2026-10-01'),
    dateEnd: jour('2026-12-01'),
  });
  assert.ok(relevance(ponctuelle, ctx) > relevance(durable, ctx));
});

test("avec un âge demandé, une tranche étroite l'emporte sur la brièveté", () => {
  const ctx = { age: 4, from: '2026-10-01' };
  const ponctuelle = sortie({ dateStart: jour('2026-10-03'), dateEnd: jour('2026-10-03') });
  const durable = sortie({
    ageMin: 4,
    ageMax: 5,
    dateStart: jour('2026-10-01'),
    dateEnd: jour('2026-12-01'),
  });
  assert.ok(relevance(durable, ctx) > relevance(ponctuelle, ctx));
});

// ─────────────────────────────────────────────────────────────── le classement

test('rankEvents rend les identifiants dans l’ordre d’affichage', () => {
  const ctx = { age: 4, from: '2026-10-01' };
  const lointaine = sortie({ dateStart: jour('2027-06-01'), dateEnd: jour('2027-08-31') });
  const ideale = sortie({ ageMin: 4, ageMax: 4, dateStart: jour('2026-10-02'), dateEnd: jour('2026-10-02') });
  const moyenne = sortie({ ageMin: 0, ageMax: 12, dateStart: jour('2026-10-05'), dateEnd: jour('2026-10-12') });

  assert.deepEqual(rankEvents([lointaine, moyenne, ideale], ctx), [ideale.id, moyenne.id, lointaine.id]);
});

test('les ex æquo se départagent par la date puis par l’identifiant', () => {
  const ctx = { from: '2026-10-01' };
  // Mêmes caractéristiques : seuls la date puis l'identifiant les séparent.
  const tard = sortie({ id: 1, dateStart: jour('2026-10-20'), dateEnd: jour('2026-10-20') });
  const tot = sortie({ id: 2, dateStart: jour('2026-10-20'), dateEnd: jour('2026-10-20') });
  const idem = sortie({ id: 3, dateStart: jour('2026-10-20'), dateEnd: jour('2026-10-20') });

  assert.deepEqual(rankEvents([idem, tot, tard], ctx), [1, 2, 3]);
});

test("l'ordre est total : deux pages ne montrent jamais deux fois la même sortie", () => {
  // Sans ordre total, une sortie peut apparaître page 1 **et** page 2, et une
  // autre nulle part. C'est la seule propriété dont dépend la pagination.
  const ctx = { age: 6, from: '2026-10-01' };
  const toutes = Array.from({ length: 30 }, (_, i) =>
    // Beaucoup d'ex æquo volontaires : un jour sur trois, trois tranches d'âge.
    sortie({
      ageMin: i % 3,
      ageMax: (i % 3) + 8,
      dateStart: jour(`2026-10-${String((i % 3) + 10).padStart(2, '0')}`),
      dateEnd: jour(`2026-10-${String((i % 3) + 12).padStart(2, '0')}`),
    }),
  );

  const classe = rankEvents(toutes, ctx);
  const page1 = classe.slice(0, 12);
  const page2 = classe.slice(12, 24);

  assert.equal(new Set(classe).size, toutes.length, 'aucune sortie perdue ni dupliquée');
  assert.equal(new Set([...page1, ...page2]).size, 24, 'les deux pages sont disjointes');
  // Et le classement est reproductible : la page 2 d'une seconde requête est
  // la même, quel que soit l'ordre dans lequel la base a rendu les lignes.
  const melange = [...toutes].reverse();
  assert.deepEqual(rankEvents(melange, ctx), classe);
});

test('une liste vide se classe sans broncher', () => {
  assert.deepEqual(rankEvents([], { from: '2026-10-01' }), []);
});
