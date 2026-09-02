/**
 * Le titre et la description de la page, tenus à jour pendant la navigation.
 *
 * Le serveur pré-rend le document d'entrée avec ses métadonnées ; à partir du
 * deuxième clic, plus rien ne recharge la page et c'est à l'application de les
 * corriger. Sans cela, l'onglet, l'historique et le lien qu'on partage
 * gardent le titre de la page par laquelle on est arrivé.
 */

const SITE_NAME = 'SortiesPourPetits';

function setMeta(selector: string, attribute: string, name: string, content: string) {
  let tag = document.head.querySelector<HTMLMetaElement>(selector);
  if (!tag) {
    tag = document.createElement('meta');
    tag.setAttribute(attribute, name);
    document.head.appendChild(tag);
  }
  tag.content = content;
}

function setCanonical(url: string) {
  let link = document.head.querySelector<HTMLLinkElement>('link[rel="canonical"]');
  if (!link) {
    link = document.createElement('link');
    link.rel = 'canonical';
    document.head.appendChild(link);
  }
  link.href = url;
}

export interface PageSeo {
  /** Sans le nom du site : il est ajouté ici, une bonne fois. */
  title: string;
  description?: string;
  /** Chemin canonique. Par défaut, l'adresse courante sans ses paramètres. */
  path?: string;
  noindex?: boolean;
}

export function setPageSeo({ title, description, path, noindex }: PageSeo) {
  const full = title === SITE_NAME ? title : `${title} — ${SITE_NAME}`;
  document.title = full;
  setMeta('meta[property="og:title"]', 'property', 'og:title', full);

  if (description) {
    setMeta('meta[name="description"]', 'name', 'description', description);
    setMeta('meta[property="og:description"]', 'property', 'og:description', description);
  }

  const url = `${window.location.origin}${path ?? window.location.pathname}`;
  setCanonical(url);
  setMeta('meta[property="og:url"]', 'property', 'og:url', url);

  // On n'ajoute jamais `index` : quand le serveur a mis la page en `noindex` —
  // parce que le site entier n'est pas indexable, par exemple — l'application
  // n'a pas à revenir sur sa décision.
  if (noindex) setMeta('meta[name="robots"]', 'name', 'robots', 'noindex, nofollow');
}
