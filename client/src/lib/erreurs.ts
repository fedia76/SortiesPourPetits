/**
 * Ce qu'on montre à quelqu'un quand quelque chose a raté.
 *
 * `catch (e)` attrape `unknown` : il faut donc, à chaque fois, décider ce qu'on
 * en tire. La ligne qui le faisait — `e instanceof Error ? e.message :
 * 'Erreur'` — était recopiée **quarante-huit fois**, dans vingt vues, avec
 * quatre libellés de repli différents selon l'humeur du moment.
 *
 * Ce n'est pas qu'une affaire de répétition. Aucune de ces copies ne
 * distinguait un cas qui mérite pourtant de l'être, et qui revient tous les
 * jours : une **coupure réseau**. `fetch` échoue alors avec un `TypeError:
 * Failed to fetch`, que le visiteur recevait tel quel — un message en anglais
 * qui ne dit ni ce qui s'est passé, ni quoi faire.
 */
import { ApiError } from './api';

/** Le repli, quand on n'a vraiment rien de mieux à dire. */
const GENERIQUE = 'Une erreur est survenue';

/**
 * Les messages que les navigateurs donnent à une requête qui n'est jamais
 * partie : Chrome, Safari, Firefox, et React Native pour la route.
 *
 * On teste le message **et** le type. `fetch` lève bien un `TypeError` dans ce
 * cas, mais un `TypeError` ordinaire — un `undefined` déréférencé trois lignes
 * plus haut — en est un aussi : s'en tenir au type ferait passer un bug du
 * front pour une panne d'Internet, et le visiteur irait vérifier sa box.
 */
const COUPURE = /failed to fetch|load failed|networkerror|network request failed/i;

/**
 * Ce que `fetch` lève quand la requête n'est jamais partie.
 *
 * Le seul cas où l'erreur n'a **rien** à voir avec le site : ni code de retour,
 * ni message du serveur, parce qu'il n'y a pas eu de serveur.
 */
function estUneCoupure(e: unknown): boolean {
  return e instanceof TypeError && COUPURE.test(e.message);
}

/**
 * Le message à afficher pour cette erreur.
 *
 * `repli` sert quand l'erreur ne dit rien d'exploitable — et il doit dire ce
 * que **cette** page essayait de faire, pas « Erreur ».
 */
export function messageDe(e: unknown, repli = GENERIQUE): string {
  if (estUneCoupure(e)) return 'Connexion au serveur impossible. Vérifiez votre accès à Internet.';
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error && e.message) return e.message;
  if (typeof e === 'string' && e) return e;
  return repli;
}

/**
 * Vrai si l'appelant n'est pas (ou plus) connecté.
 *
 * Une session de sept jours expire pendant qu'un onglet est ouvert : la vue
 * affiche alors « Authentification requise » au lieu de proposer de se
 * reconnecter, ce qui n'aide personne.
 */
export function demandeUneConnexion(e: unknown): boolean {
  return e instanceof ApiError && e.status === 401;
}

/**
 * Vrai si la chose demandée n'existe pas — et n'existera pas en réessayant.
 *
 * C'est ce qui distingue un suivi qu'il faut arrêter d'une coupure passagère
 * qu'il faut endurer : voir `AdminScraperRunView`, qui suit une exécution.
 */
export function estIntrouvable(e: unknown): boolean {
  return e instanceof ApiError && e.status === 404;
}
