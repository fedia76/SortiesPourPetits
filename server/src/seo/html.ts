import fs from 'fs';
import path from 'path';
import { config } from '../config';

/**
 * Assemblage du document HTML servi aux visiteurs comme aux moteurs.
 *
 * Le principe tient en une phrase : tout le monde reçoit le même HTML. Servir
 * une version enrichie aux seuls robots — ce qu'on appelle le « rendu
 * dynamique » — demande de les reconnaître à leur signature, ce qu'on ne sait
 * pas faire de façon fiable, et ce que Google ne recommande plus. Le HTML
 * pré-rendu est donc celui que le navigateur affiche pendant que Vue démarre,
 * puis que Vue remplace en se montant sur `#app`.
 */

/** Texte quelconque → texte posable dans un nœud ou dans un attribut. */
export function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/**
 * Un objet, écrit de façon à ne pas pouvoir sortir de son `<script>`.
 *
 * `escapeHtml` est inutilisable ici — il casserait le JSON. On neutralise donc
 * les seuls caractères qui permettraient à une description de sortie de fermer
 * la balise et d'injecter du script : `<`, `>` et `&`, en échappement Unicode,
 * que `JSON.parse` relit à l'identique.
 */
function jsonInerte(data: unknown): string {
  return JSON.stringify(data)
    .replace(/</g, '\\u003c')
    .replace(/>/g, '\\u003e')
    .replace(/&/g, '\\u0026');
}

/** Un bloc de données structurées. */
export function jsonLdScript(data: unknown): string {
  return `<script type="application/ld+json">${jsonInerte(data)}</script>`;
}

/**
 * Ce que le serveur a déjà demandé à sa propre API, offert à l'application.
 *
 * Les clés sont des chemins d'API — « /api/events/509 » —, les valeurs ce que
 * cet appel aurait répondu. L'application les reprend au lieu de les redemander
 * (voir `client/src/lib/etatInitial.ts`), et c'est tout l'objet de ce bloc :
 * une page complète dès le premier affichage, sans un aller-retour réseau dont
 * dépendait, jusqu'ici, la moindre ligne de son contenu.
 *
 * Rien ne s'y trouve qu'un visiteur anonyme ne puisse déjà demander lui-même :
 * ce sont les réponses des routes publiques, à l'identique.
 */
export type InitialState = Record<string, unknown>;

/** L'identifiant du bloc, connu des deux côtés. */
export const STATE_ID = 'etat-initial';

export function stateScript(state: InitialState): string {
  return `<script type="application/json" id="${STATE_ID}">${jsonInerte(state)}</script>`;
}

/** Coupe proprement une description pour une balise `<meta>`. */
export function truncate(value: string, max = 160): string {
  const flat = value.replace(/\s+/g, ' ').trim();
  if (flat.length <= max) return flat;
  const cut = flat.slice(0, max - 1);
  const lastSpace = cut.lastIndexOf(' ');
  return `${(lastSpace > max / 2 ? cut.slice(0, lastSpace) : cut).trimEnd()}…`;
}

const HEAD_BLOCK = /<!--seo:head-->[\s\S]*?<!--\/seo:head-->/;
const BODY_MARK = '<!--seo:body-->';

let template: string | null = null;
let templateError = false;

/**
 * Le `index.html` du build, chargé une fois et gardé en mémoire.
 *
 * En production il ne change qu'au déploiement, qui redémarre l'API : le
 * relire à chaque requête ne rachèterait rien. En développement le front est
 * servi par Vite sur son propre port, donc l'absence du fichier n'est pas une
 * anomalie — on le signale une fois et l'API continue de répondre à son API.
 */
function loadTemplate(): string | null {
  if (template !== null || templateError) return template;
  const file = path.join(config.clientDir, 'index.html');
  try {
    template = fs.readFileSync(file, 'utf8');
    if (!HEAD_BLOCK.test(template) || !template.includes(BODY_MARK)) {
      console.warn(
        `[seo] ${file} ne porte plus les marqueurs <!--seo:head--> / <!--seo:body--> :` +
          ' les pages seront servies sans pré-rendu.',
      );
    }
    return template;
  } catch {
    templateError = true;
    console.warn(`[seo] ${file} introuvable : pas de pré-rendu (normal en développement).`);
    return null;
  }
}

/** Ce qu'une page pré-rendue fournit au gabarit. */
export interface RenderedPage {
  status: number;
  /** Balises à poser dans le `<head>`, déjà échappées. */
  head: string;
  /** Contenu de `#app`, affiché jusqu'à ce que Vue prenne la main. */
  body: string;
  /** Les réponses d'API que l'application n'aura pas à redemander. */
  state?: InitialState;
}

/**
 * Injecte une page dans le gabarit. `null` si le gabarit manque.
 *
 * Les deux remplacements passent par une **fonction** et non par une chaîne,
 * et c'est tout sauf un détail de style : `String.replace` interprète `$&`,
 * `` $` ``, `$'` et `$1` dans une chaîne de remplacement. `escapeHtml`
 * n'échappe pas le dollar — il n'a aucune raison de le faire, ce n'est pas un
 * caractère HTML —, donc une sortie intitulée « Atelier 5$' » faisait recopier
 * tout le reste du gabarit à l'intérieur du `<head>`, marqueur
 * `<!--seo:body-->` compris. Le corps de la page n'était alors jamais rempli.
 * Une fonction de remplacement rend le texte tel quel, sans rien interpréter.
 */
export function renderDocument(page: RenderedPage): string | null {
  const html = loadTemplate();
  if (html === null) return null;
  const head =
    page.state && Object.keys(page.state).length
      ? `${page.head}\n    ${stateScript(page.state)}`
      : page.head;
  return html.replace(HEAD_BLOCK, () => head).replace(BODY_MARK, () => page.body);
}
