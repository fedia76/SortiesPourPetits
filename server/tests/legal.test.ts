/**
 * Les pages légales, et la seule chose qui compte vraiment à leur sujet :
 * qu'elles s'affichent, partout, sans rien exiger du visiteur.
 *
 * Le texte vit en un seul endroit (`lib/legal.ts`) et sort à deux : le document
 * pré-rendu et l'API que la vue relit. Ce qui se teste ici, c'est justement le
 * lien entre les deux — qu'ils portent bien le **même** texte, et que le
 * serveur ne réponde pas 404 sur une adresse qu'il doit servir.
 *
 * Une mention légale absente n'est pas un défaut d'affichage : c'est une
 * obligation qui n'est pas remplie.
 */
import { test, describe, before } from 'node:test';
import assert from 'node:assert/strict';

// `lib/legal` ne dépend de rien — c'est du texte —, il s'importe donc
// normalement, et les cas peuvent s'écrire à partir de son contenu.
import { PAGES_LEGALES, pageLegale, pageLegaleParChemin } from '../src/lib/legal';

// `seo/pages`, lui, entraîne la configuration et l'accès à la base : il se
// charge à l'ouverture de la série, comme dans `seoHtml.test.ts`, et non à
// l'import de ce fichier.
type Pages = typeof import('../src/seo/pages');
type Html = typeof import('../src/seo/html');
let renderPage: Pages['renderPage'];
let escapeHtml: Html['escapeHtml'];

before(async () => {
  ({ renderPage } = await import('../src/seo/pages'));
  ({ escapeHtml } = await import('../src/seo/html'));
});

/** Un texte tel qu'il apparaît une fois posé dans le document. */
function pose(texte: string): RegExp {
  return new RegExp(escapeHtml(texte).replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
}

describe('les pages légales', () => {
  test('les deux pages attendues existent', () => {
    assert.deepEqual(
      PAGES_LEGALES.map((p) => p.chemin).sort(),
      ['/confidentialite', '/mentions-legales'],
    );
  });

  test('chaque page a un titre, une description et des sections remplies', () => {
    for (const page of PAGES_LEGALES) {
      assert.ok(page.titre.length > 0, `${page.slug} doit avoir un titre`);
      assert.ok(page.description.length > 0, `${page.slug} doit avoir une description`);
      assert.ok(page.sections.length > 0, `${page.slug} doit avoir des sections`);
      for (const section of page.sections) {
        assert.ok(section.titre.length > 0, `une section de ${page.slug} n'a pas de titre`);
        assert.ok(
          section.paragraphes.length > 0 && section.paragraphes.every((t) => t.trim().length > 0),
          `la section « ${section.titre} » de ${page.slug} a un paragraphe vide`,
        );
      }
    }
  });

  test("l'adresse de contact figure dans les deux pages", () => {
    for (const page of PAGES_LEGALES) {
      const texte = page.sections.flatMap((s) => s.paragraphes).join(' ');
      assert.match(
        texte,
        /@/,
        `${page.slug} doit porter une adresse de contact : sans elle, ni signalement ni exercice des droits`,
      );
    }
  });

  test('la page de confidentialité offre un moyen de refuser la mesure', () => {
    const page = pageLegale('confidentialite');
    assert.ok(page);
    assert.ok(
      page.sections.some((s) => s.action === 'opposition-audience'),
      "l'exemption de consentement suppose de pouvoir s'opposer : le bouton doit exister",
    );
  });

  test('une barre finale ne fait pas manquer la page', () => {
    assert.equal(pageLegaleParChemin('/mentions-legales/')?.slug, 'mentions-legales');
    assert.equal(pageLegaleParChemin('/mentions-legales')?.slug, 'mentions-legales');
  });

  test('un slug inconnu ne rend rien', () => {
    assert.equal(pageLegale('cgv'), undefined);
    assert.equal(pageLegaleParChemin('/cgv'), undefined);
  });

  for (const page of PAGES_LEGALES) {
    test(`${page.chemin} est servie en 200, lisible sans JavaScript`, async () => {
      const rendu = await renderPage('https://exemple.fr', page.chemin, {});

      assert.equal(rendu.status, 200, 'une mention légale ne doit jamais répondre 404');
      assert.match(rendu.head, new RegExp(page.titre));

      // La page ne se déclare pas elle-même hors index : la loi veut ces
      // pages trouvables, contrairement aux formulaires et aux écrans qui
      // demandent un compte.
      //
      // Ce n'est pas l'en-tête `robots` qui le dit — hors production, le site
      // entier passe en `noindex` et l'y chercher ne prouverait rien. C'est
      // l'adresse canonique : `buildHead` ne l'écrit que pour une page qu'on
      // ne demande pas d'ignorer.
      assert.match(
        rendu.head,
        new RegExp(`<link rel="canonical" href="https://exemple\\.fr${page.chemin}"`),
        'une page légale doit porter son adresse canonique, donc être indexable',
      );

      // Le corps porte le texte, et pas seulement un conteneur vide : c'est ce
      // qui rend la page lisible avant que Vue ne démarre, et sans lui.
      for (const section of page.sections) {
        // Comparé **échappé** : une apostrophe sort en `&#39;`, et c'est très
        // bien ainsi — une page légale n'a aucune raison de pouvoir injecter
        // quoi que ce soit dans le document.
        assert.match(
          rendu.body,
          pose(section.titre),
          `le corps pré-rendu doit porter la section « ${section.titre} »`,
        );
      }
    });

    test(`${page.chemin} transmet son texte à la vue sans appel réseau`, async () => {
      const rendu = await renderPage('https://exemple.fr', page.chemin, {});
      const attendu = rendu.state?.[`/api/legal/${page.slug}`] as { page?: unknown } | undefined;
      assert.deepEqual(
        attendu?.page,
        page,
        "l'état initial doit porter exactement ce que l'API répondrait",
      );
    });
  }
});
