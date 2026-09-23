import { config } from '../config';
import { escapeHtml } from './html';

/**
 * La balise de mesure d'audience, posée dans le `<head>` de chaque page.
 *
 * Elle est écrite **ici**, côté serveur, et non dans le `index.html` du front,
 * pour une raison simple : l'identifiant du site est propre à l'installation.
 * Dans le gabarit, il faudrait reconstruire le front pour le changer, et le
 * développement comme une préproduction porteraient la même balise — donc
 * compteraient dans les mêmes chiffres. Lue dans l'environnement du serveur,
 * la configuration se change avec un redémarrage, et **son absence suffit à
 * ne rien mesurer du tout** : c'est l'état par défaut, celui du développement.
 *
 * Ce que le script fait, et qu'on n'a donc pas à coder :
 *
 * - les changements de page de l'application. Il enrobe `history.pushState` et
 *   `replaceState`, ce que fait vue-router à chaque navigation. Il n'y a rien
 *   à brancher sur le routeur.
 * - les recherches. Elles vivent dans la *query string* (voir
 *   `client/src/lib/searchQuery.ts`), donc dans l'adresse, donc dans la page
 *   vue : aucun événement à poser pour savoir ce que les gens cherchent.
 * - les clics sur les liens marqués. Le script écoute le clic sur `document`
 *   en phase de capture et remonte au `[data-umami-event]` le plus proche :
 *   un lien rendu par Vue après coup est donc couvert comme les autres.
 *
 * Sur la vie privée : le script ne pose aucun cookie et ne construit pas
 * d'identifiant durable. C'est ce qui permet de s'en tenir aux quatre critères
 * d'exemption de consentement de la CNIL — mesure d'audience seule, pas de
 * recoupement, pas de suivi d'un site à l'autre, information et opposition —
 * et donc de mesurer sans bandeau. Ce n'est vrai que tant qu'on ne branche
 * rien d'autre dessus.
 *
 * Les deux derniers critères ne se décrètent pas, ils s'outillent : l'information
 * est la page de confidentialité, et l'opposition tient en deux moyens — le
 * « Do Not Track » du navigateur, que `data-do-not-track` fait respecter ici,
 * et le bouton de refus de cette même page.
 */
export function audienceTag(): string {
  const { scriptUrl, websiteId, hostUrl } = config.audience;

  // Les deux sont indispensables : un script sans identifiant de site ne sait
  // pas où déposer ce qu'il mesure, et un identifiant sans script ne mesure
  // rien. À défaut de l'un ou de l'autre, on ne pose pas de balise — c'est le
  // cas du développement, et c'est voulu.
  if (!scriptUrl || !websiteId) return '';

  // Calculé avant d'être utilisé : un `data-domains` **vide** ne serait pas
  // une absence de contrainte, mais une contrainte impossible à satisfaire —
  // le script comparerait le nom d'hôte courant à une liste ne contenant que
  // la chaîne vide, ne s'y trouverait pas, et se tairait partout.
  const domaine = hostDeBase();

  const attributs = [
    `src="${escapeHtml(scriptUrl)}"`,
    `data-website-id="${escapeHtml(websiteId)}"`,
    // Le script déduit sinon l'adresse de collecte du dossier d'où il est
    // servi. Ça tomberait juste, mais autant ne pas faire dépendre la collecte
    // d'une convention de nommage : elle est écrite.
    hostUrl ? `data-host-url="${escapeHtml(hostUrl)}"` : '',
    // Le domaine attendu, quand on le connaît. Une page de ce site recopiée
    // ailleurs — un cache, un agrégateur, un site qui nous encadre — porterait
    // la balise et viendrait gonfler les chiffres avec un trafic qui n'est pas
    // le nôtre. Cette ligne la fait se taire ailleurs qu'à la maison.
    domaine ? `data-domains="${escapeHtml(domaine)}"` : '',
    // Le « Do Not Track » du navigateur, honoré — le script l'ignore par
    // défaut, il faut le lui demander. Ce n'est pas une politesse : l'exemption
    // de consentement de la CNIL suppose que le visiteur puisse s'opposer à la
    // mesure, et une case à cocher dans son navigateur est le seul moyen qui ne
    // lui demande rien de particulier. La page de confidentialité le promet ;
    // cette ligne est ce qui tient la promesse.
    //
    // Elle coûte les visiteurs qui l'ont activé. C'est le prix de l'exemption,
    // et il est petit devant un bandeau de consentement.
    'data-do-not-track="true"',
  ].filter(Boolean);

  return `<script defer ${attributs.join(' ')}></script>`;
}

/** Le nom d'hôte de `PUBLIC_BASE_URL`, ou rien si elle est inexploitable. */
function hostDeBase(): string {
  try {
    return new URL(config.publicBaseUrl).hostname;
  } catch {
    return '';
  }
}
