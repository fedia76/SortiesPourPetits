/**
 * Les plafonds de corps des requêtes JSON, et **l'ordre dans lequel ils sont
 * posés** — qui est tout le sujet.
 *
 * ## Pourquoi ce fichier existe
 *
 * Express applique le premier parseur monté, pas le plus proche de la route.
 * Un `express.json()` global suivi d'un `express.json({ limit })` déclaré sur
 * une route ne donne donc pas à cette route un plafond plus haut : le parseur
 * global a déjà lu — ou refusé — le corps quand celui de la route s'exécute.
 * Le second ne fait rien, et il ne le dit pas.
 *
 * C'est exactement ce qui est arrivé au banc : ses routes portaient un
 * `express.json({ limit: '12mb' })` que rien n'appliquait, et tout compte rendu
 * dépassant les 100 ko du plafond par défaut repartait en « Erreur interne du
 * serveur ». Aucune chasse ne pouvait aboutir — ses paquets de pages portent du
 * HTML gzippé, donc dépassent toujours —, et une capture échouait dès que la
 * page était un peu grosse. Le banc semblait marcher par moments.
 *
 * D'où la règle, tenue en un seul endroit : **le parseur large d'abord, le
 * parseur global ensuite**. `body-parser` marque la requête une fois le corps
 * lu (`req._body`), et le parseur global se retire alors de lui-même. Le reste
 * du site garde donc son plafond serré — ce qui est le but : le banc est
 * authentifié et ne parle qu'au worker, là où `POST /api/events` est ouvert.
 */
import express, { Express } from 'express';

/**
 * Ce qu'une route du banc accepte.
 *
 * Le worker envoie jusqu'à cinq pages par paquet (`HUNT_BATCH`), chacune
 * portant au plus 1 Mo de HTML gzippé en base64 (`EVAL_MAX_HTML_B64`) : 5 Mo
 * dans le pire des cas, et cette marge couvre aussi les captures d'agendas
 * paginés.
 */
export const EVAL_BODY_LIMIT = '12mb';

/** Le préfixe qui a droit au plafond large. Les routes du banc, et elles seules. */
export const EVAL_PREFIX = '/api/eval';

/**
 * Monte les parseurs JSON de l'application, dans le seul ordre qui marche.
 *
 * À appeler avant tout routeur : un parseur monté après un routeur ne voit
 * jamais les requêtes qu'il traite.
 */
export function mountJsonParsers(app: Express): void {
  app.use(EVAL_PREFIX, express.json({ limit: EVAL_BODY_LIMIT }));
  app.use(express.json());
}
