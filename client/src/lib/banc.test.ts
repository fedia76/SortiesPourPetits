/**
 * Ce que la console du banc décide.
 *
 * Une faute ici ne casse rien — elle rend les chiffres **flatteurs**, ce qui
 * est bien pire pour un banc de mesure. Deux endroits surtout :
 *
 * * l'appariement d'un relevé avec le corpus, où cacher une étiquette
 *   orpheline effacerait exactement ce qu'on cherche à voir ;
 * * le compte des corrections d'une chasse, seul chiffre qui dise si le corpus
 *   apprend quelque chose ou s'il vient de recopier la brique qu'il mesure.
 */
import { describe, expect, test } from 'vitest';

import type { EvalHunt, EvalHuntPage, EvalLink, EvalLinkResult } from '../types';
import {
  apparierReleve,
  basculer,
  cochees,
  corrections,
  enAttente,
  etatDeCompletude,
  motifsDeRejet,
  pageSuivanteTrouvee,
  phraseDePortee,
  precocher,
  restantes,
  resumeSortie,
  venueDeLEtiquette,
  type Choix,
} from './banc';

/** Ce qu'un run a relevé pour un lien. */
function releve(champs: Partial<EvalLinkResult> & { url: string }): EvalLinkResult {
  return {
    id: 1,
    text: 'Un spectacle',
    context: '',
    harvested: true,
    dropReason: '',
    position: 0,
    selected: null,
    selectReason: '',
    ...champs,
  };
}

/** Ce qu'un humain a dit d'un lien. */
function etiquette(champs: Partial<EvalLink> & { url: string }): EvalLink {
  return { id: 1, verdict: 'SORTIE', text: '', origin: 'HUMAIN', ...champs } as EvalLink;
}

// ═════════════════════════════════════════════ le relevé face au corpus

describe('apparier un relevé et ses étiquettes', () => {
  test('un lien relevé porte l’étiquette qu’on lui connaît', () => {
    const lignes = apparierReleve({
      links: [etiquette({ url: 'https://a.fr/x', id: 7 })],
      results: [releve({ url: 'https://a.fr/x', id: 3 })],
    });
    expect(lignes).toHaveLength(1);
    expect(lignes[0].result?.id).toBe(3);
    expect(lignes[0].label?.id).toBe(7);
  });

  test('un lien relevé sans étiquette est de la dette, et se voit', () => {
    const lignes = apparierReleve({ links: [], results: [releve({ url: 'https://a.fr/x' })] });
    expect(lignes).toHaveLength(1);
    expect(lignes[0].label).toBeNull();
  });

  test('une étiquette que le relevé ne porte pas est la mesure la plus intéressante', () => {
    // Elle dit qu'un lien qu'on savait là a disparu de ce que la brique rend.
    // La cacher effacerait précisément ce qu'on cherche.
    const lignes = apparierReleve({
      links: [etiquette({ url: 'https://a.fr/disparue' })],
      results: [releve({ url: 'https://a.fr/x' })],
    });
    expect(lignes).toHaveLength(2);
    const orpheline = lignes.find((l) => l.result === null);
    expect(orpheline?.label?.url).toBe('https://a.fr/disparue');
  });

  test('les orphelines viennent après le relevé, qui garde son ordre', () => {
    const lignes = apparierReleve({
      links: [etiquette({ url: 'https://a.fr/absente' })],
      results: [
        releve({ url: 'https://a.fr/b', position: 1 }),
        releve({ url: 'https://a.fr/a', position: 2 }),
      ],
    });
    expect(lignes.map((l) => l.result?.url ?? l.label?.url)).toEqual([
      'https://a.fr/b',
      'https://a.fr/a',
      'https://a.fr/absente',
    ]);
  });

  test('la ligne technique de la pagination n’est pas un lien de la page', () => {
    const lignes = apparierReleve({
      links: [],
      results: [
        releve({ url: 'https://a.fr/page/2', position: -1 }),
        releve({ url: 'https://a.fr/x', position: 0 }),
      ],
    });
    expect(lignes).toHaveLength(1);
    expect(lignes[0].result?.url).toBe('https://a.fr/x');
  });

  test('une page sans run affiche quand même ses étiquettes', () => {
    // `results` est absent tant qu'aucun run du banc n'a été joué dessus : la
    // page doit rester lisible et étiquetable.
    const lignes = apparierReleve({ links: [etiquette({ url: 'https://a.fr/x' })] });
    expect(lignes).toHaveLength(1);
    expect(lignes[0].result).toBeNull();
  });

  test('une page vide ne casse rien', () => {
    expect(apparierReleve({ links: [], results: [] })).toEqual([]);
  });
});

describe('les motifs de rejet', () => {
  const page = {
    results: [
      releve({ url: 'a', harvested: false, dropReason: 'navigation' }),
      releve({ url: 'b', harvested: false, dropReason: 'texte trop court' }),
      releve({ url: 'c', harvested: false, dropReason: 'navigation' }),
      releve({ url: 'd', harvested: false, dropReason: 'navigation' }),
      // Retenu : il n'a aucun motif à donner.
      releve({ url: 'e', harvested: true, dropReason: '' }),
      // La pagination n'est pas un lien écarté.
      releve({ url: 'f', position: -1, harvested: false, dropReason: 'pagination' }),
    ],
  };

  test('comptés, et du plus fréquent au moins fréquent', () => {
    expect(motifsDeRejet(page)).toEqual([
      ['navigation', 3],
      ['texte trop court', 1],
    ]);
  });

  test('ce qui a été retenu n’y figure pas', () => {
    expect(motifsDeRejet(page).map(([motif]) => motif)).not.toContain('');
    expect(motifsDeRejet(page).map(([motif]) => motif)).not.toContain('pagination');
  });
});

test('la page suivante trouvée est portée par la ligne technique', () => {
  expect(
    pageSuivanteTrouvee({
      results: [
        releve({ url: 'x', position: 0, selectReason: 'un lien ordinaire' }),
        releve({ url: 'y', position: -1, selectReason: 'https://a.fr/page/2' }),
      ],
    }),
  ).toBe('https://a.fr/page/2');
  expect(pageSuivanteTrouvee({ results: [releve({ url: 'x' })] })).toBe('');
  expect(pageSuivanteTrouvee({})).toBe('');
});

// ═══════════════════════════════════════════════ ce qu'une sortie affirme

describe('le résumé d’une sortie du corpus', () => {
  const vide = {
    dateStart: null,
    dateEnd: null,
    postalCode: null,
    ageMin: null,
    ageMax: null,
    audience: null,
  };

  test('une période, un code postal, un âge, un public', () => {
    expect(
      resumeSortie({
        ...vide,
        dateStart: '2026-10-01',
        dateEnd: '2026-10-05',
        postalCode: '76600',
        ageMin: 3,
        ageMax: 6,
        audience: 'ENFANTS',
      }),
    ).toBe('— du 2026-10-01 au 2026-10-05 · 76600 · 3 à 6 ans · jeune public');
  });

  test('une date unique ne se répète pas', () => {
    expect(resumeSortie({ ...vide, dateStart: '2026-10-01', dateEnd: '2026-10-01' })).toBe(
      '— le 2026-10-01',
    );
    expect(resumeSortie({ ...vide, dateStart: '2026-10-01' })).toBe('— le 2026-10-01');
  });

  test('une seule borne d’âge se dit quand même', () => {
    expect(resumeSortie({ ...vide, ageMin: 3 })).toBe('— dès 3 ans');
    expect(resumeSortie({ ...vide, ageMax: 6 })).toBe('— jusqu’à 6 ans');
  });

  test('zéro est un âge, pas une absence', () => {
    expect(resumeSortie({ ...vide, ageMin: 0, ageMax: 3 })).toBe('— 0 à 3 ans');
  });

  test('une étiquette vide le dit — ce n’est pas une sortie sans particularité', () => {
    expect(resumeSortie(vide)).toBe('— rien d’affirmé');
  });

  test('rien du tout ne rend rien du tout', () => {
    expect(resumeSortie(null)).toBe('');
    expect(resumeSortie(undefined)).toBe('');
  });
});

test('la portée d’un run se dit en une phrase', () => {
  expect(
    phraseDePortee({
      dateFrom: '2026-10-01',
      dateTo: '2026-10-31',
      postalPrefixes: ['76', '27'],
      maxLinks: 8,
      theme: 'sorties enfants',
    }),
  ).toBe('du 2026-10-01 au 2026-10-31 · départements 76, 27 · 8 liens au plus par page · « sorties enfants »');
  expect(phraseDePortee({})).toBe('');
  // Une seule borne de date ne décrit aucune fenêtre.
  expect(phraseDePortee({ dateFrom: '2026-10-01' })).toBe('');
});

test('l’origine d’une étiquette se lit en clair', () => {
  expect(venueDeLEtiquette('MODERATION')).toMatch(/modération/);
  expect(venueDeLEtiquette('HUMAIN')).toMatch(/console/);
});

test('l’état de complétude d’un panier', () => {
  expect(etatDeCompletude({ faits: 0, total: 10 })).toBe('vide');
  expect(etatDeCompletude({ faits: 10, total: 10 })).toBe('complete');
  expect(etatDeCompletude({ faits: 3, total: 10 })).toBe('');
  // Un panier sans rien à faire est complet, pas vide.
  expect(etatDeCompletude({ faits: 0, total: 0 })).toBe('vide');
});

// ═══════════════════════════════════════════════════════════ la chasse

function candidate(champs: Partial<EvalHuntPage> & { id: number }): EvalHuntPage {
  return {
    huntId: 1,
    url: `https://a.fr/${champs.id}`,
    foundUrl: '',
    title: '',
    query: '',
    proposed: null,
    signal: '',
    detail: '',
    confidence: '',
    asked: '',
    links: 0,
    dated: 0,
    heading: '',
    opening: '',
    chars: 0,
    archived: true,
    error: '',
    decision: 'EN_ATTENTE',
    decidedAt: null,
    natureId: null,
    createdAt: '',
    ...champs,
  } as EvalHuntPage;
}

function chasse(pages: EvalHuntPage[]): EvalHunt {
  return { id: 1, prompt: 'p', pages } as EvalHunt;
}

describe('la précoche', () => {
  test('propose ce que l’étage 2 a reconnu', () => {
    const pages = [candidate({ id: 1, proposed: 'AGENDA' }), candidate({ id: 2, proposed: 'SORTIE' })];
    expect(precocher([chasse(pages)], {})).toEqual({ 1: 'AGENDA', 2: 'SORTIE' });
  });

  test('ce que l’étage 2 n’a pas su reconnaître reste décoché', () => {
    // Lui donner « agenda », comme le fait le pipeline faute de mieux,
    // écrirait au corpus un repli d'orchestration au lieu de ce que la page
    // est — et le corpus mesurerait alors la brique contre elle-même.
    expect(precocher([chasse([candidate({ id: 1, proposed: null })])], {})).toEqual({});
  });

  test('ce qu’un humain a corrigé l’emporte sur la proposition', () => {
    // Sans quoi un rechargement effacerait son travail.
    const pages = [candidate({ id: 1, proposed: 'AGENDA' })];
    expect(precocher([chasse(pages)], { 1: 'SORTIE' })).toEqual({ 1: 'SORTIE' });
  });

  test('une candidate déjà tranchée sort de la précoche', () => {
    const pages = [
      candidate({ id: 1, proposed: 'AGENDA', decision: 'RETENUE' }),
      candidate({ id: 2, proposed: 'SORTIE', decision: 'ECARTEE' }),
      candidate({ id: 3, proposed: 'AUTRE' }),
    ];
    expect(precocher([chasse(pages)], { 1: 'AGENDA' })).toEqual({ 3: 'AUTRE' });
  });

  test('les choix d’une chasse disparue ne survivent pas', () => {
    // La précoche est **reposée**, pas fusionnée : garder un identifiant que
    // plus aucune page ne porte enverrait une décision dans le vide.
    expect(precocher([], { 42: 'AGENDA' })).toEqual({});
  });
});

describe('cocher et décocher', () => {
  test('cocher pose la nature', () => {
    expect(basculer({}, 1, 'AGENDA')).toEqual({ 1: 'AGENDA' });
  });

  test('recliquer la même nature décoche', () => {
    expect(basculer({ 1: 'AGENDA' }, 1, 'AGENDA')).toEqual({});
  });

  test('cliquer une autre nature remplace', () => {
    expect(basculer({ 1: 'AGENDA' }, 1, 'SORTIE')).toEqual({ 1: 'SORTIE' });
  });

  test('les autres pages ne bougent pas', () => {
    expect(basculer({ 1: 'AGENDA', 2: 'SORTIE' }, 1, 'AGENDA')).toEqual({ 2: 'SORTIE' });
  });

  test('l’objet de départ n’est pas modifié', () => {
    const avant: Choix = { 1: 'AGENDA' };
    basculer(avant, 2, 'SORTIE');
    expect(avant).toEqual({ 1: 'AGENDA' });
  });
});

describe('ce qu’une validation emporte', () => {
  const pages = [
    candidate({ id: 1, proposed: 'AGENDA' }),
    candidate({ id: 2, proposed: 'AGENDA' }),
    candidate({ id: 3, proposed: null }),
    candidate({ id: 4, proposed: 'SORTIE', decision: 'RETENUE' }),
  ];
  const c = chasse(pages);

  test('seules les candidates en attente comptent', () => {
    expect(enAttente(c).map((p) => p.id)).toEqual([1, 2, 3]);
  });

  test('les cochées partent au corpus, les autres restent en attente', () => {
    // Une page décochée parce que l'étage 2 n'a pas su n'est pas une page
    // qu'on a refusée : valider par paquets ne tranche à la place de personne.
    const choix: Choix = { 1: 'AGENDA', 3: 'SORTIE' };
    expect(cochees(c, choix).map((p) => p.id)).toEqual([1, 3]);
    expect(restantes(c, choix).map((p) => p.id)).toEqual([2]);
  });

  test('une page déjà tranchée n’est ni cochable ni écartable', () => {
    expect(cochees(c, { 4: 'SORTIE' })).toEqual([]);
    expect(restantes(c, {}).map((p) => p.id)).toEqual([1, 2, 3]);
  });
});

describe('les corrections — le seul chiffre qui dise si le banc apprend', () => {
  test('confirmer une proposition n’apprend rien', () => {
    const c = chasse([candidate({ id: 1, proposed: 'AGENDA' })]);
    expect(corrections(c, { 1: 'AGENDA' })).toBe(0);
  });

  test('démentir une proposition est une correction', () => {
    const c = chasse([candidate({ id: 1, proposed: 'AGENDA' })]);
    expect(corrections(c, { 1: 'SORTIE' })).toBe(1);
  });

  test('étiqueter ce que l’étage 2 n’a pas su reconnaître en est une aussi', () => {
    // L'absence de proposition est un aveu : le corriger apprend autant que
    // démentir.
    const c = chasse([candidate({ id: 1, proposed: null })]);
    expect(corrections(c, { 1: 'AGENDA' })).toBe(1);
  });

  test('ce qui n’est pas coché ne compte pas', () => {
    const c = chasse([candidate({ id: 1, proposed: 'AGENDA' }), candidate({ id: 2, proposed: null })]);
    expect(corrections(c, {})).toBe(0);
  });

  test('zéro correction sur tout un lot se voit', () => {
    // C'est le cas qu'il faut pouvoir lire : le corpus s'apprête à recopier
    // l'étage 2, et la mesure qui s'appuiera dessus le mesurera contre
    // lui-même.
    const pages = Array.from({ length: 30 }, (_, i) =>
      candidate({ id: i + 1, proposed: 'AGENDA' }),
    );
    const choix = Object.fromEntries(pages.map((p) => [p.id, 'AGENDA' as const]));
    expect(cochees(chasse(pages), choix)).toHaveLength(30);
    expect(corrections(chasse(pages), choix)).toBe(0);
  });
});
