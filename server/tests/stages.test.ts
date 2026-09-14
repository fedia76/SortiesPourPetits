/**
 * L'accord entre le vocabulaire du scraper et celui du site.
 *
 * Le scraper est la source de vérité, et il la transporte : l'événement
 * `run_start` porte le graphe complet. Mais le site en garde une copie pour
 * tout ce que cet événement ne couvre pas — une exécution dont on a oublié le
 * journal détaillé, une exécution ancienne, et les motifs de refus, qui
 * désignent un étage sans qu'aucun run soit en jeu.
 *
 * Cette copie avait déjà divergé, en silence : elle ne comptait que sept
 * étages. `attribute` y manquait, `indexOf` rendait -1, et l'étage 7
 * s'affichait numéro 0 sans libellé, en tête du graphe. Rien ne pouvait le
 * dire, puisque rien ne comparait les deux fichiers.
 *
 * Ce test les compare — en lisant le fichier Python. C'est inhabituel, et
 * c'est assumé : les deux moitiés du dépôt ne partagent aucun outillage, et la
 * seule autre option était de continuer à espérer.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';

import { STAGES, STAGE_ORDER, describeStage, stageOf } from '../src/lib/stages';
import { REJECTION_MEANINGS, describeRejections } from '../src/lib/rejectionCodes';

const VOCABULAIRE_PYTHON = path.join(
  __dirname,
  '..',
  '..',
  'scraper',
  'sortiesbot',
  'stages',
  '__init__.py',
);

/**
 * Les étages déclarés côté scraper, lus dans `ORDER` puis dans `LABEL`.
 *
 * On ne lit que ces deux tables : ce sont les seules dont le site dépend
 * vraiment, et les seules dont la forme est assez stable pour être relue de
 * l'extérieur sans devenir un piège.
 */
function vocabulairePython(): { id: string; label: string }[] {
  const source = fs.readFileSync(VOCABULAIRE_PYTHON, 'utf8');

  const valeurs = new Map<string, string>();
  for (const [, nom, valeur] of source.matchAll(/^\s{4}([A-Z_]+) = "([a-z_]+)"$/gm)) {
    valeurs.set(nom, valeur);
  }

  const ordre = source.match(/^ORDER: tuple\[Stage, \.\.\.\] = \(([\s\S]*?)\n\)/m);
  assert.ok(ordre, 'ORDER doit se lire dans le fichier Python');
  const ids = [...ordre[1].matchAll(/Stage\.([A-Z_]+),/g)].map(([, nom]) => {
    const valeur = valeurs.get(nom);
    assert.ok(valeur, `Stage.${nom} doit avoir une valeur`);
    return valeur;
  });

  const bloc = source.match(/^LABEL: dict\[Stage, str\] = \{([\s\S]*?)\n\}/m);
  assert.ok(bloc, 'LABEL doit se lire dans le fichier Python');
  const libelles = new Map<string, string>();
  for (const [, nom, label] of bloc[1].matchAll(/Stage\.([A-Z_]+): "([^"]+)",/g)) {
    libelles.set(valeurs.get(nom) ?? nom, label);
  }

  return ids.map((id) => ({ id, label: libelles.get(id) ?? '' }));
}

test('le site connaît exactement les étages du scraper, dans le même ordre', () => {
  const python = vocabulairePython();

  assert.deepEqual(
    STAGES.map((s) => ({ id: s.stage, label: s.label })),
    python,
    'src/lib/stages.ts doit suivre sortiesbot/stages/__init__.py',
  );
});

test('les numéros suivent l’ordre, sans trou ni doublon', () => {
  assert.deepEqual(
    STAGES.map((s) => s.number),
    STAGES.map((_, i) => i + 1),
  );
  assert.equal(new Set(STAGE_ORDER).size, STAGES.length);
});

test('chaque étage dit qui le fait travailler', () => {
  for (const stage of STAGES) {
    assert.ok(
      ['modele', 'python', 'mixte'].includes(stage.actor),
      `${stage.stage} : « ${stage.actor} » n'est pas un acteur connu`,
    );
    assert.ok(stage.takes && stage.gives, `${stage.stage} doit dire ce qu'il prend et ce qu'il rend`);
  }
});

test("l'attribution est là — c'est précisément elle qui manquait", () => {
  const attribution = stageOf('attribute');
  assert.ok(attribution);
  assert.equal(attribution.number, 7);
  assert.equal(attribution.label, 'Attribution');
});

test('un étage inconnu est rendu tel quel, et rangé en fin de graphe', () => {
  // Le repli d'avant le numérotait 0, donc le plaçait **en tête**, sans nom.
  const inconnu = describeStage('une-brique-de-demain');
  assert.equal(inconnu.label, 'une-brique-de-demain');
  assert.ok(inconnu.number > STAGES.length);
  assert.equal(stageOf('une-brique-de-demain'), undefined);
});

// ───────────────────────────────────────────── les motifs de refus, en regard

test('chaque motif de refus met en cause un étage qui existe', () => {
  // `describeRejections` écarte silencieusement un identifiant inconnu : une
  // faute de frappe ferait donc disparaître une imputation sans rien dire, et
  // la page de qualité compterait sous « aucun étage » des refus parfaitement
  // imputés.
  for (const motif of REJECTION_MEANINGS) {
    for (const etage of motif.blames) {
      assert.ok(stageOf(etage), `${motif.code} met en cause « ${etage} », qui n'existe pas`);
    }
  }
});

test('aucune imputation ne se perd en chemin', () => {
  const decrits = describeRejections();
  assert.equal(decrits.length, REJECTION_MEANINGS.length);
  for (const [i, motif] of REJECTION_MEANINGS.entries()) {
    assert.equal(decrits[i].blames.length, motif.blames.length, `${motif.code}`);
  }
});

test('les motifs sans étage en cause le disent, et c’est voulu', () => {
  // Un doublon n'est la faute de personne : c'est le dédoublonnage qui ne sait
  // pas encore le voir. « Autre » non plus, par construction.
  const sansEtage = REJECTION_MEANINGS.filter((m) => m.blames.length === 0).map((m) => m.code);
  assert.deepEqual([...sansEtage].sort(), ['AUTRE', 'DOUBLON']);
});

test('chaque motif porte un libellé court et une précision', () => {
  for (const motif of REJECTION_MEANINGS) {
    assert.ok(motif.label.length > 0 && motif.label.length <= 30, `${motif.code} : libellé`);
    assert.ok(motif.hint.length > 0, `${motif.code} : précision`);
  }
});
