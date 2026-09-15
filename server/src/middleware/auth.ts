import crypto from 'crypto';
import { NextFunction, Request, Response } from 'express';
import jwt from 'jsonwebtoken';
import { Role } from '@prisma/client';
import { config } from '../config';
import { prisma } from '../db';

export interface AuthUser {
  id: number;
  role: Role;
}

declare global {
  // eslint-disable-next-line @typescript-eslint/no-namespace
  namespace Express {
    interface Request {
      user?: AuthUser;
      /**
       * L'appelant est un programme (clé d'API), pas un navigateur.
       *
       * Le rôle ne suffit pas à le dire — le scraper agit avec le compte d'un
       * humain, et cet humain peut aussi remplir le formulaire. Certains champs
       * ne sont crédibles que dans un sens : un formulaire ne sait pas d'où il
       * tient un lien, un scraper si.
       */
      viaApiKey?: boolean;
    }
  }
}

const ROLE_LEVEL: Record<Role, number> = {
  USER: 0,
  MODERATOR: 1,
  ADMIN: 2,
};

export function signToken(user: AuthUser): string {
  return jwt.sign({ id: user.id, role: user.role }, config.jwtSecret, {
    expiresIn: '7d',
  });
}

// Le préfixe permet de reconnaître une clé qui fuite dans un log ou un dépôt.
const API_KEY_PREFIX = 'spp_';

export function hashApiKey(key: string): string {
  return crypto.createHash('sha256').update(key).digest('hex');
}

/** Génère une clé d'API. Le clair n'est retourné qu'ici : seul le hash est stocké. */
export function generateApiKey(): { key: string; keyHash: string } {
  const key = API_KEY_PREFIX + crypto.randomBytes(32).toString('hex');
  return { key, keyHash: hashApiKey(key) };
}

/**
 * Ce que le cookie et la clé d'API ont besoin de retrouver en base.
 *
 * Une interface, et pas un appel direct à Prisma, pour une seule raison : le
 * choix de la **source du rôle** est ce que ce module décide, et c'est donc ce
 * qu'il faut pouvoir éprouver sans base de données.
 */
export interface AuthLookups {
  /** Le compte, tel qu'il est **maintenant**. `null` s'il a été supprimé. */
  user(id: number): Promise<AuthUser | null>;
  /** La clé, son état de révocation et le compte qu'elle porte. */
  apiKey(keyHash: string): Promise<{ id: number; revokedAt: Date | null; user: AuthUser } | null>;
  /** Trace d'usage d'une clé. Ne doit jamais retarder ni faire échouer l'appel. */
  touchApiKey(id: number): void;
}

const prismaLookups: AuthLookups = {
  user: (id) => prisma.user.findUnique({ where: { id }, select: { id: true, role: true } }),
  apiKey: (keyHash) =>
    prisma.apiKey.findUnique({
      where: { keyHash },
      select: { id: true, revokedAt: true, user: { select: { id: true, role: true } } },
    }),
  touchApiKey: (id) => {
    prisma.apiKey.update({ where: { id }, data: { lastUsedAt: new Date() } }).catch(() => {});
  },
};

/**
 * Identifie l'appelant sans exiger d'être connecté :
 * - header `Authorization: Bearer spp_…` (programmes tiers) — une clé
 *   présentée mais invalide ou révoquée est refusée ;
 * - sinon cookie de session (client web), anonyme si absent ou invalide.
 *
 * ## Le rôle vient de la base, dans les deux cas
 *
 * Le jeton de session **porte** le rôle : il est signé, donc il ne se falsifie
 * pas, et on s'en contentait. Mais il fige aussi ce rôle pour les sept jours
 * de sa validité. Retirer ses droits à un modérateur ne les lui retirait donc
 * pas : il gardait l'accès à la file de modération, à la console du scraper et
 * au banc jusqu'à ce que son cookie expire de lui-même, et rien dans
 * l'interface d'administration ne le laissait deviner. Supprimer le compte
 * n'y changeait rien non plus.
 *
 * La clé d'API, elle, relisait déjà la base à chaque appel et se révoque donc
 * à la seconde. Deux modèles de sécurité contradictoires cohabitaient dans
 * cette fonction ; c'est le plus faible qui couvrait la console.
 *
 * Le coût est d'une lecture par requête **authentifiée** — la fréquentation
 * anonyme, qui est l'essentiel du trafic public, ne paie rien puisqu'elle ne
 * présente pas de cookie. Le jeton ne sert donc plus qu'à dire *qui* appelle ;
 * ce qu'il a le droit de faire se demande à la base.
 */
export function attachUserWith(lookups: AuthLookups) {
  return async function attachUser(req: Request, res: Response, next: NextFunction) {
    const header = req.headers.authorization;
    if (header?.startsWith(`Bearer ${API_KEY_PREFIX}`)) {
      const apiKey = await lookups.apiKey(hashApiKey(header.slice('Bearer '.length)));
      if (!apiKey || apiKey.revokedAt) {
        res.status(401).json({ error: "Clé d'API invalide ou révoquée" });
        return;
      }
      req.user = { id: apiKey.user.id, role: apiKey.user.role };
      req.viaApiKey = true;
      // Trace d'usage, sans retarder la requête.
      lookups.touchApiKey(apiKey.id);
      next();
      return;
    }

    // `cookie-parser` ne type pas ce qu'il a lu : un cookie « token »
    // fabriqué à la main peut porter n'importe quoi, un tableau compris.
    const token: unknown = (req.cookies as Record<string, unknown> | undefined)?.token;
    if (typeof token !== 'string') {
      next();
      return;
    }

    let payload: AuthUser;
    try {
      // `jwt.verify` rend `any`. Seul l'identifiant sert ensuite : le rôle
      // vient de la base, et c'est tout l'objet de cette fonction.
      payload = jwt.verify(token, config.jwtSecret) as AuthUser;
    } catch {
      // Jeton invalide ou expiré : on continue en anonyme.
      next();
      return;
    }

    // Volontairement hors du `try` ci-dessus : une base injoignable est une
    // panne, pas un visiteur anonyme. La rattraper ici dégraderait
    // silencieusement un modérateur en visiteur, ce qui est la pire des deux
    // réponses — le filet d'`asyncRoutes` rend 500, et c'est la bonne.
    const user = await lookups.user(payload.id);
    if (user) {
      req.user = { id: user.id, role: user.role };
    } else {
      // Compte supprimé : le cookie ne désigne plus personne, autant le dire
      // au navigateur plutôt que de le laisser le représenter sept jours.
      res.clearCookie('token');
    }
    next();
  };
}

export const attachUser = attachUserWith(prismaLookups);

export function requireAuth(req: Request, res: Response, next: NextFunction) {
  if (!req.user) {
    res.status(401).json({ error: 'Authentification requise' });
    return;
  }
  next();
}

/** Rôles hiérarchiques : un admin a aussi les droits d'un modérateur. */
export function requireRole(minRole: Role) {
  return (req: Request, res: Response, next: NextFunction) => {
    if (!req.user) {
      res.status(401).json({ error: 'Authentification requise' });
      return;
    }
    if (ROLE_LEVEL[req.user.role] < ROLE_LEVEL[minRole]) {
      res.status(403).json({ error: 'Droits insuffisants' });
      return;
    }
    next();
  };
}

export function hasRole(user: AuthUser | undefined, minRole: Role): boolean {
  return !!user && ROLE_LEVEL[user.role] >= ROLE_LEVEL[minRole];
}
