/**
 * L'assemblage du document pré-rendu, et le piège qu'il cachait.
 *
 * `String.replace` interprète `$&`, `` $` ``, `$'` et `$1` **dans la chaîne de
 * remplacement**. `escapeHtml` ne touche pas au dollar — il n'a aucune raison
 * de le faire, ce n'est pas un caractère HTML — donc le titre d'une sortie
 * pouvait piloter l'assemblage du gabarit. Une fiche « Atelier 5$' euros »
 * faisait recopier tout le reste du document à l'intérieur du `<head>`,
 * marqueur `<!--seo:body-->` compris : le corps n'était alors jamais rempli, et
 * le visiteur recevait une page vide en attendant que Vue démarre.
 *
 * Ce n'est pas une injection — le contenu reste échappé — mais c'est une sortie
 * du site, approuvée par la modération, qui casse le rendu de sa propre page.
 * Le test porte donc sur les caractères, pas sur une adresse ou un scénario.
 */
import { test, before } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

// Le gabarit est lu depuis `config.clientDir`, résolu à l'import du module de
// configuration : il faut donc poser la variable d'environnement avant.
const dossier = fs.mkdtempSync(path.join(os.tmpdir(), 'spp-seo-'));
const GABARIT =
  '<!doctype html><html><head><!--seo:head--><!--/seo:head--></head>' +
  '<body><div id="app"><!--seo:body--></div></body></html>';
fs.writeFileSync(path.join(dossier, 'index.html'), GABARIT);
process.env.CLIENT_DIR = dossier;

type Html = typeof import('../src/seo/html');
let escapeHtml: Html['escapeHtml'];
let renderDocument: Html['renderDocument'];

before(async () => {
  ({ escapeHtml, renderDocument } = await import('../src/seo/html'));
});

/** Le document rendu pour une page qui transmet cet état initial. */
function renduAvecEtat(state: Record<string, unknown>): string {
  const document = renderDocument({
    status: 200,
    head: '<title>Peu importe</title>',
    body: '<h1>Peu importe</h1>',
    state,
  });
  assert.ok(document !== null, 'le gabarit de test doit être trouvé');
  return document;
}

/** Le JSON du bloc d'état, tel que le navigateur le lira. */
function etatRelu(document: string): unknown {
  const bloc = /<script type="application\/json" id="etat-initial">([\s\S]*?)<\/script>/.exec(
    document,
  );
  assert.ok(bloc, 'le document doit porter son état initial');
  return JSON.parse(bloc[1]);
}

/** Le document rendu pour une page dont le titre est `titre`. */
function rendu(titre: string): string {
  const document = renderDocument({
    status: 200,
    head: `<title>${escapeHtml(titre)}</title>`,
    body: `<h1>${escapeHtml(titre)}</h1>`,
  });
  assert.ok(document !== null, 'le gabarit de test doit être trouvé');
  return document;
}

test('un titre ordinaire se pose dans le head et dans le corps', () => {
  const document = rendu('Atelier poterie');
  assert.match(document, /<head><title>Atelier poterie<\/title><\/head>/);
  assert.match(document, /<h1>Atelier poterie<\/h1>/);
});

/**
 * Les quatre motifs que `String.replace` interprète. `$'` est le plus
 * destructeur — il insère tout ce qui suit le motif remplacé — mais les autres
 * mutilent le document tout autant.
 */
for (const motif of ["$'", '$&', '$`', '$1']) {
  test(`un titre contenant « ${motif} » n'altère pas le gabarit`, () => {
    const titre = `Atelier 5${motif} euros`;
    const document = rendu(titre);

    // Le corps a bien été rempli : c'est ce que « $' » emportait, en
    // recopiant le marqueur au lieu de le laisser se faire remplacer.
    assert.ok(
      !document.includes('<!--seo:body-->'),
      'le marqueur du corps doit avoir été remplacé, pas recopié',
    );
    assert.ok(
      !document.includes('<!--seo:head-->'),
      'le bloc du head doit avoir été remplacé, pas recopié',
    );

    // Le titre arrive intact, dollar compris, dans les deux emplacements.
    assert.ok(document.includes(`<title>${escapeHtml(titre)}</title>`));
    assert.ok(document.includes(`<h1>${escapeHtml(titre)}</h1>`));

    // Et le document garde sa forme : une seule fois chaque balise.
    assert.equal(document.match(/<\/html>/g)?.length, 1);
    assert.equal(document.match(/<head>/g)?.length, 1);
  });
}

test('le corps aussi est à l’abri : les deux remplacements sont concernés', () => {
  const document = renderDocument({
    status: 200,
    head: '<title>Sans surprise</title>',
    body: "<p>Tarif : 8$' l’entrée</p>",
  });
  assert.ok(document !== null);
  assert.ok(document.includes("<p>Tarif : 8$' l’entrée</p>"));
  assert.match(document, /<\/body><\/html>$/);
});

/**
 * L'état initial : ce que le serveur a déjà demandé à sa propre API, offert à
 * l'application pour qu'elle n'ait pas à le redemander.
 *
 * Trois exigences, et elles tiennent toutes à ce que ce bloc est du texte posé
 * dans un document : il doit se relire à l'identique, il ne doit pas pouvoir
 * sortir de son `<script>`, et il ne doit pas pouvoir piloter l'assemblage du
 * gabarit — même piège que le titre, puisqu'il passe par le même `replace`.
 */
test("l'état initial se relit à l'identique", () => {
  const etat = { '/api/events/509': { event: { id: 509, title: 'Atelier poterie' } } };
  assert.deepEqual(etatRelu(renduAvecEtat(etat)), etat);
});

test("une description ne peut pas fermer le script de l'état", () => {
  const etat = {
    '/api/events/1': { event: { description: 'Fin </script><script>alert(1)</script>' } },
  };
  const document = renduAvecEtat(etat);
  const bloc = /id="etat-initial">([\s\S]*?)<\/script>/.exec(document);
  assert.ok(bloc);

  // Aucun `<` ni `&` ne survit dans le bloc : il n'y a donc pas de balise à
  // fermer, et le texte se relit pourtant tel quel.
  assert.ok(!bloc[1].includes('<'), 'aucun « < » ne doit rester dans le bloc');
  assert.ok(!bloc[1].includes('&'), 'aucun « & » ne doit rester dans le bloc');
  assert.deepEqual(etatRelu(document), etat);
  assert.ok(!document.includes('<script>alert(1)</script>'));
});

test("un dollar dans l'état n'altère pas le gabarit", () => {
  const etat = { "/api/events/2": { event: { title: "Atelier 5$' euros" } } };
  const document = renduAvecEtat(etat);
  assert.ok(!document.includes('<!--seo:body-->'), 'le corps doit avoir été rempli');
  assert.deepEqual(etatRelu(document), etat);
  assert.equal(document.match(/<\/html>/g)?.length, 1);
});

test("une page sans état ne pose pas de bloc vide", () => {
  const document = renderDocument({
    status: 404,
    head: '<title>Page introuvable</title>',
    body: '<h1>Page introuvable</h1>',
  });
  assert.ok(document !== null);
  assert.ok(!document.includes('id="etat-initial"'));
  assert.ok(!renduAvecEtat({}).includes('id="etat-initial"'));
});
