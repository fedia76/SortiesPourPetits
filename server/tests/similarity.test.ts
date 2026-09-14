/**
 * La détection de doublons proposée au modérateur.
 *
 * L'outil ne décide rien — il note et il explique — mais c'est lui qui met une
 * sortie sous les yeux de quelqu'un ou l'y soustrait, et il n'avait aucun test.
 * Un seuil mal placé ne casse rien : il rend juste le doublon invisible, ce qui
 * est exactement ce qu'on ne verrait jamais.
 *
 * Les valeurs absolues des poids ne sont pas verrouillées ici — elles ont
 * vocation à être retouchées. Ce qui l'est : les rapports entre les signaux,
 * les bornes du score, et ce que le modérateur lit comme motif.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  normalize,
  periodsOverlap,
  rankSimilar,
  scoreSimilarity,
  significantWords,
  similarityRatio,
  type ComparableEvent,
} from '../src/lib/similarity';

function jour(iso: string): Date {
  return new Date(`${iso}T00:00:00.000Z`);
}

/** Une sortie réduite à ce qui la compare. Deux appels sans argument sont identiques. */
function sortie(champs: Partial<ComparableEvent> = {}): ComparableEvent {
  return {
    title: 'Atelier poterie pour enfants',
    description: 'Un atelier de poterie où les enfants façonnent leur premier bol.',
    venueId: 1,
    categoryId: 1,
    createdById: 1,
    isPermanent: false,
    dateStart: jour('2026-10-01'),
    dateEnd: jour('2026-10-31'),
    ...champs,
  };
}

// ────────────────────────────────────────────────────────── la normalisation

test('accents, casse et ponctuation disparaissent', () => {
  assert.equal(normalize("Fête de l'Été"), 'fete de l ete');
  assert.equal(normalize('  Théâtre :  Marionnettes !  '), 'theatre marionnettes');
});

test('les mots significatifs excluent les mots outils et les doublons', () => {
  assert.deepEqual(significantWords("La Fête de l'Été à Rouen"), ['fete', 'ete', 'rouen']);
  assert.deepEqual(significantWords('Cirque et cirque'), ['cirque']);
});

test('les mots de moins de trois lettres ne distinguent rien', () => {
  assert.deepEqual(significantWords('Zoo de la ZA 12'), ['zoo']);
});

// ───────────────────────────────────────────────────── la ressemblance de texte

test('deux titres identiques à la casse et aux accents près valent 1', () => {
  assert.equal(similarityRatio('Le Petit Prince', 'le petit prince'), 1);
  assert.equal(similarityRatio('Fête foraine', 'FETE FORAINE'), 1);
});

test('une faute de frappe ne casse pas le rapprochement', () => {
  // C'est tout l'intérêt des bigrammes face à une égalité stricte.
  assert.ok(similarityRatio('Spectacle de marionnettes', 'Spectacle de marionettes') > 0.95);
});

test("l'ordre des mots et les mots en trop sont tolérés", () => {
  const ratio = similarityRatio('Ferme pédagogique de Gally', 'La ferme de Gally');
  assert.ok(ratio > 0.6 && ratio < 0.7, `attendu ~0,63, obtenu ${ratio}`);
});

test('deux titres sans rapport restent très bas', () => {
  assert.ok(similarityRatio('Atelier poterie', 'Concert de jazz') < 0.2);
});

test('un texte vide ou trop court ne ressemble à rien', () => {
  assert.equal(similarityRatio('', 'Atelier'), 0);
  assert.equal(similarityRatio('Atelier', '   '), 0);
  // Un seul caractère : pas de bigramme à comparer, sauf égalité exacte.
  assert.equal(similarityRatio('a', 'a'), 1);
  assert.equal(similarityRatio('ab', 'a'), 0);
});

// ────────────────────────────────────────────────────── le chevauchement de dates

test('deux périodes qui se touchent se chevauchent', () => {
  const a = sortie({ dateStart: jour('2026-10-01'), dateEnd: jour('2026-10-10') });
  const b = sortie({ dateStart: jour('2026-10-10'), dateEnd: jour('2026-10-20') });
  assert.equal(periodsOverlap(a, b), true);
});

test('deux périodes disjointes ne se chevauchent pas', () => {
  const a = sortie({ dateStart: jour('2026-10-01'), dateEnd: jour('2026-10-10') });
  const b = sortie({ dateStart: jour('2026-10-11'), dateEnd: jour('2026-10-20') });
  assert.equal(periodsOverlap(a, b), false);
});

test('une sortie permanente est toujours en cours', () => {
  const permanente = sortie({ isPermanent: true, dateStart: null, dateEnd: null });
  const ponctuelle = sortie({ dateStart: jour('2030-01-01'), dateEnd: jour('2030-01-02') });
  assert.equal(periodsOverlap(permanente, ponctuelle), true);
  assert.equal(periodsOverlap(ponctuelle, permanente), true);
});

test('une borne manquante est une borne ouverte', () => {
  const sansFin = sortie({ dateStart: jour('2026-10-01'), dateEnd: null });
  const bienApres = sortie({ dateStart: jour('2030-01-01'), dateEnd: jour('2030-01-02') });
  assert.equal(periodsOverlap(sansFin, bienApres), true);
});

// ──────────────────────────────────────────────────────────────── la note

test('le doublon parfait sature à 100', () => {
  const { score, reasons } = scoreSimilarity(sortie(), sortie());
  assert.equal(score, 100);
  assert.ok(reasons.includes('Même lieu'));
  assert.ok(reasons.includes('Même catégorie'));
  assert.ok(reasons.includes('Même auteur'));
  assert.ok(reasons.includes('Périodes qui se chevauchent'));
});

test('deux sorties sans rien de commun tombent très bas', () => {
  const autre = sortie({
    title: 'Concert de musique classique',
    description: 'Une soirée symphonique au conservatoire, pour public averti.',
    venueId: 2,
    categoryId: 2,
    createdById: 2,
    dateStart: jour('2027-03-01'),
    dateEnd: jour('2027-03-02'),
  });
  assert.ok(scoreSimilarity(sortie(), autre).score < 15);
});

test('des périodes différentes freinent le score au lieu de l’ignorer', () => {
  // Sans ce coup de frein, un lieu qui programme beaucoup noie le vrai doublon
  // sous ses autres évènements, tous crédités du même lieu.
  const memePeriode = scoreSimilarity(sortie(), sortie()).score;
  const autrePeriode = scoreSimilarity(
    sortie(),
    sortie({ dateStart: jour('2027-05-01'), dateEnd: jour('2027-05-02') }),
  );
  assert.ok(autrePeriode.score < memePeriode);
  assert.ok(autrePeriode.reasons.includes('Périodes différentes'));
});

test('un lieu proche compte moins qu’un lieu identique, et d’autant moins qu’il est loin', () => {
  const ailleurs = (km: number) => scoreSimilarity(sortie(), sortie({ venueId: 2 }), km, 5).score;
  const memeLieu = scoreSimilarity(sortie(), sortie()).score;

  assert.ok(ailleurs(0.2) < memeLieu);
  assert.ok(ailleurs(0.2) > ailleurs(2) && ailleurs(2) > ailleurs(4.9));
  assert.equal(ailleurs(5), ailleurs(10), 'au-delà du rayon, la proximité n’apporte plus rien');
});

test('la distance est affichée dans le motif, en mètres si elle est courte', () => {
  assert.ok(
    scoreSimilarity(sortie(), sortie({ venueId: 2 }), 0.35, 5).reasons.includes('Lieu à 350 m'),
  );
  assert.ok(
    scoreSimilarity(sortie(), sortie({ venueId: 2 }), 2.45, 5).reasons.includes('Lieu à 2,5 km'),
  );
});

test('la distance n’est rendue que si les lieux diffèrent', () => {
  assert.equal(scoreSimilarity(sortie(), sortie(), 0).distanceKm, undefined);
  assert.equal(scoreSimilarity(sortie(), sortie({ venueId: 2 }), 1.2, 5).distanceKm, 1.2);
});

test('un titre proche est annoncé, un titre lointain reste muet', () => {
  const proche = scoreSimilarity(sortie(), sortie({ title: 'Atelier poterie pour les enfants' }));
  assert.ok(proche.reasons.some((r) => r.startsWith('Titre proche à')));

  const lointain = scoreSimilarity(sortie(), sortie({ title: 'Concert symphonique' }));
  assert.ok(!lointain.reasons.some((r) => r.startsWith('Titre proche à')));
});

test('le score est un entier entre 0 et 100', () => {
  const scores = [
    scoreSimilarity(sortie(), sortie()).score,
    scoreSimilarity(sortie(), sortie({ venueId: 2, title: 'Rien à voir du tout' })).score,
    scoreSimilarity(sortie(), sortie({ venueId: 2 }), 3.7, 5).score,
  ];
  for (const score of scores) {
    assert.ok(Number.isInteger(score), `${score} doit être entier`);
    assert.ok(score >= 0 && score <= 100);
  }
});

// ───────────────────────────────────────────────────────────── le classement

test('rankSimilar garde les plus ressemblants, au-dessus du seuil et dans la limite', () => {
  const examinee = sortie();
  const jumelle = { ...sortie(), id: 10 };
  const voisine = { ...sortie({ venueId: 2, title: 'Atelier poterie enfants' }), id: 11 };
  const etrangere = {
    ...sortie({
      venueId: 3,
      categoryId: 9,
      createdById: 9,
      title: 'Conférence sur la fiscalité',
      description: 'Une réunion d’information destinée aux professionnels du secteur.',
      dateStart: jour('2028-01-01'),
      dateEnd: jour('2028-01-02'),
    }),
    id: 12,
  };

  const classe = rankSimilar(examinee, [etrangere, voisine, jumelle], new Map([[2, 1.0]]), {
    radiusKm: 5,
    minScore: 30,
    limit: 5,
  });

  assert.deepEqual(classe.map((r) => r.event.id), [10, 11]);
  assert.ok(classe[0].similarity.score > classe[1].similarity.score);
});

test('la limite tronque après le classement, pas avant', () => {
  const examinee = sortie();
  const candidats = [
    { ...sortie({ title: 'Sans aucun rapport ici', venueId: 4 }), id: 1 },
    { ...sortie(), id: 2 },
  ];
  const classe = rankSimilar(examinee, candidats, new Map(), {
    radiusKm: 5,
    minScore: 0,
    limit: 1,
  });
  assert.deepEqual(classe.map((r) => r.event.id), [2], 'le meilleur, pas le premier venu');
});

test('un seuil trop haut ne propose rien plutôt que n’importe quoi', () => {
  const classe = rankSimilar(sortie(), [{ ...sortie({ venueId: 7 }), id: 1 }], new Map(), {
    radiusKm: 5,
    minScore: 100,
    limit: 5,
  });
  assert.deepEqual(classe, []);
});

test('un lieu hors du rayon n’a pas de distance, et n’en invente pas', () => {
  // `distanceByVenueId` ne contient que les lieux du rayon : les autres
  // arrivent avec `undefined`, et ne doivent pas être crédités de proximité.
  const loin = { ...sortie({ venueId: 99 }), id: 1 };
  const [premier] = rankSimilar(sortie(), [loin], new Map(), {
    radiusKm: 5,
    minScore: 0,
    limit: 5,
  });
  assert.equal(premier.similarity.distanceKm, undefined);
  assert.ok(!premier.similarity.reasons.some((r) => r.startsWith('Lieu à')));
});
