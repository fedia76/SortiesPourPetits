/**
 * La balise de mesure d'audience, et les deux façons de la rendre inoffensive.
 *
 * Elle part dans le `<head>` de **toutes** les pages : ce qu'elle contient est
 * donc lu par chaque visiteur, et une valeur de configuration mal formée s'y
 * voit tout de suite. Deux propriétés valent d'être tenues par un test plutôt
 * que par la relecture :
 *
 * 1. rien de configuré, rien de posé. C'est l'état du développement et d'une
 *    préproduction — la garantie qu'ils ne comptent pas dans les chiffres du
 *    site sans qu'on ait à y penser.
 * 2. un `data-domains` vide ne doit jamais sortir. Ce n'est pas une absence de
 *    contrainte : le script comparerait le nom d'hôte courant à une liste ne
 *    contenant que la chaîne vide, ne s'y trouverait pas, et se tairait
 *    partout. Une mesure qui ne mesure rien et ne dit pas pourquoi.
 *
 * La configuration se lit à l'appel, pas à l'import : les cas la déplacent
 * donc directement, ce qui évite de rejouer l'import d'un module pour chacun.
 */
import { test, describe, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { config } from '../src/config';
import { audienceTag } from '../src/seo/audience';
import { buildHead } from '../src/seo/meta';

const initiale = { audience: { ...config.audience }, publicBaseUrl: config.publicBaseUrl };

afterEach(() => {
  config.audience = { ...initiale.audience };
  config.publicBaseUrl = initiale.publicBaseUrl;
});

/** La balise produite pour cette configuration. */
function baliseAvec(audience: Partial<typeof config.audience>, publicBaseUrl = ''): string {
  config.audience = { scriptUrl: '', websiteId: '', hostUrl: '', ...audience };
  config.publicBaseUrl = publicBaseUrl;
  return audienceTag();
}

describe("la balise de mesure d'audience", () => {
  test('rien de configuré : aucune balise', () => {
    assert.equal(baliseAvec({}), '');
  });

  test("un script sans identifiant de site ne sait où rien déposer : pas de balise", () => {
    assert.equal(baliseAvec({ scriptUrl: '/mesure/mesure.js' }, 'https://exemple.fr'), '');
  });

  test("un identifiant sans script ne se charge nulle part : pas de balise", () => {
    assert.equal(baliseAvec({ websiteId: 'abc-123' }, 'https://exemple.fr'), '');
  });

  test('configurée : la balise porte le script, le site, la collecte et le domaine', () => {
    const balise = baliseAvec(
      {
        websiteId: 'abc-123',
        scriptUrl: '/mesure/mesure.js',
        hostUrl: 'https://exemple.fr/mesure',
      },
      'https://exemple.fr',
    );
    assert.match(balise, /^<script defer /);
    assert.match(balise, /src="\/mesure\/mesure\.js"/);
    assert.match(balise, /data-website-id="abc-123"/);
    assert.match(balise, /data-host-url="https:\/\/exemple\.fr\/mesure"/);
    assert.match(balise, /data-domains="exemple\.fr"/);
    // La page de confidentialité annonce que le « Do Not Track » du navigateur
    // est respecté, et l'exemption de consentement suppose un moyen de s'y
    // opposer. L'attribut est ce qui rend les deux vrais : il se teste.
    assert.match(balise, /data-do-not-track="true"/);
    assert.match(balise, /<\/script>$/);
  });

  test("l'adresse de collecte est facultative : le script vise alors son propre dossier", () => {
    const balise = baliseAvec(
      { websiteId: 'abc-123', scriptUrl: '/mesure/mesure.js' },
      'https://exemple.fr',
    );
    assert.doesNotMatch(balise, /data-host-url/);
  });

  test('sans adresse publique exploitable, pas de data-domains du tout', () => {
    for (const base of ['', 'pas-une-url']) {
      const balise = baliseAvec(
        { websiteId: 'abc-123', scriptUrl: '/mesure/mesure.js' },
        base,
      );
      assert.ok(balise !== '', `la balise doit exister pour PUBLIC_BASE_URL=${base || '(vide)'}`);
      assert.doesNotMatch(
        balise,
        /data-domains/,
        `un data-domains vide ferait taire la mesure partout (PUBLIC_BASE_URL=${base || '(vide)'})`,
      );
    }
  });

  // Les cas ci-dessus éprouvent la fabrication de la balise ; celui-ci éprouve
  // qu'elle arrive à destination. C'est un assemblage séparé, et une balise
  // parfaite qui n'est jamais posée ne mesure rien.
  test('la balise atteint le <head> assemblé, sur une page indexable comme sur une page ignorée', () => {
    config.audience = {
      websiteId: 'abc-123',
      scriptUrl: '/mesure/mesure.js',
      hostUrl: 'https://exemple.fr/mesure',
    };
    config.publicBaseUrl = 'https://exemple.fr';

    for (const noindex of [false, true]) {
      const head = buildHead('https://exemple.fr', {
        title: 'Une sortie',
        description: 'Une description',
        path: '/sorties/12',
        noindex,
      });
      assert.match(
        head,
        /data-website-id="abc-123"/,
        `la page ${noindex ? 'ignorée des moteurs' : 'indexable'} doit porter la balise`,
      );
    }
  });

  test('rien de configuré : le <head> assemblé ne porte aucune balise', () => {
    config.audience = { websiteId: '', scriptUrl: '', hostUrl: '' };
    const head = buildHead('https://exemple.fr', {
      title: 'Une sortie',
      description: 'Une description',
      path: '/sorties/12',
    });
    assert.doesNotMatch(head, /data-website-id/);
  });

  test('une valeur de configuration ne peut pas sortir de son attribut', () => {
    const balise = baliseAvec(
      { websiteId: '"><script>alert(1)</script>', scriptUrl: '/mesure/mesure.js' },
      'https://exemple.fr',
    );
    assert.doesNotMatch(balise, /<script>alert/);
    assert.match(balise, /data-website-id="&quot;&gt;&lt;script&gt;/);
  });
});
