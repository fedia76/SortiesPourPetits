/**
 * Le filet qui manquait sous les gestionnaires asynchrones.
 *
 * Express 4 n'attend pas ses gestionnaires. Un `async (req, res) => …` qui
 * rejette ne rejoint donc **pas** le gestionnaire d'erreur monté en bas
 * d'`index.ts` : la promesse rejetée devient un `unhandledRejection`, et Node
 * tue le processus depuis la version 15. Le résultat, vu du navigateur, n'est
 * pas un 500 mais un **502** — le serveur n'a rien répondu du tout, parce
 * qu'il n'existait plus.
 *
 * Ce n'est pas une hypothèse : c'est arrivé. Un alias `signal` — mot réservé
 * de MySQL — dans une requête d'une page d'administration a éteint le site
 * public, et systemd le relançait juste à temps pour qu'un rechargement le
 * retue.
 *
 * ## Enrober plutôt que rattraper route par route
 *
 * Le serveur compte une centaine de gestionnaires asynchrones. Leur demander à
 * chacun un `try/catch` serait un rappel à ne jamais oublier, sur toutes les
 * routes à venir, pour une garantie qu'un seul oubli suffirait à perdre. On
 * l'installe donc une fois, à l'endroit où les routes se déclarent.
 *
 * Rien ne change pour qui écrit une route : elle reste un `async` ordinaire,
 * et une exception y part désormais vers le gestionnaire d'erreur commun, qui
 * répond 500 et journalise. Le site, lui, reste debout.
 *
 * ## Ce que le filet ne fait pas
 *
 * Il ne masque rien : l'erreur est journalisée par `index.ts` exactement comme
 * une erreur synchrone l'a toujours été. Il ne transforme pas non plus un bug
 * en fonctionnement normal — une route qui échoue échoue, elle rend 500. Il
 * empêche seulement qu'elle emporte le reste du site avec elle.
 */
import { Router, type NextFunction, type Request, type RequestHandler, type Response } from 'express';

/** Les méthodes par lesquelles une route se déclare sur un routeur. */
const METHODS = ['get', 'post', 'put', 'patch', 'delete', 'all', 'use'] as const;

type Method = (typeof METHODS)[number];

/**
 * Enrobe un gestionnaire pour que son rejet rejoigne `next(err)`.
 *
 * Deux cas laissés intacts, et ce sont les bons :
 *
 * * un **gestionnaire d'erreur** — quatre paramètres — n'a pas à être enrobé :
 *   il *est* la destination, et l'enrober changerait sa signature, donc
 *   Express cesserait de le reconnaître comme tel ;
 * * un gestionnaire **synchrone** ne rend pas de promesse ; on le laisse
 *   passer sans allocation inutile, tout en attrapant quand même ce qu'il
 *   lève, ce qu'Express faisait déjà.
 */
export function safe(handler: RequestHandler): RequestHandler {
  if (handler.length >= 4) return handler;
  return function wrapped(req: Request, res: Response, next: NextFunction) {
    try {
      const out: unknown = handler(req, res, next);
      // On ne teste pas `instanceof Promise` : un `then`-able suffit, et
      // certaines couches en rendent qui n'en sont pas.
      if (out && typeof (out as PromiseLike<unknown>).then === 'function') {
        void Promise.resolve(out).catch(next);
      }
    } catch (err) {
      next(err);
    }
  };
}

/**
 * Un routeur dont tout gestionnaire déclaré est enrobé.
 *
 * À utiliser à la place de `Router()` dans les fichiers de routes. Le reste du
 * code ne change pas : les surcharges d'Express — chemin optionnel, plusieurs
 * gestionnaires, sous-routeur monté par `use` — continuent de fonctionner,
 * puisqu'on ne touche qu'aux arguments qui sont des fonctions.
 */
export function safeRouter(): Router {
  const router = Router();
  for (const method of METHODS) {
    const original = router[method].bind(router) as (...args: unknown[]) => unknown;
    // Le typage d'Express pour ces méthodes est une pile de surcharges qu'on
    // ne peut pas reproduire ; on réinstalle donc la méthode telle quelle et
    // on se contente de filtrer les arguments.
    (router as unknown as Record<Method, unknown>)[method] = (...args: unknown[]) =>
      original(...args.map((arg) => (typeof arg === 'function' ? safe(arg as RequestHandler) : arg)));
  }
  return router;
}
