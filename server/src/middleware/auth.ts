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
 * Identifie l'appelant sans exiger d'être connecté :
 * - header `Authorization: Bearer spp_…` (programmes tiers) — le rôle est relu
 *   en base à chaque appel, une clé présentée mais invalide est refusée ;
 * - sinon cookie de session (client web), anonyme si absent ou invalide.
 */
export async function attachUser(req: Request, res: Response, next: NextFunction) {
  const header = req.headers.authorization;
  if (header?.startsWith(`Bearer ${API_KEY_PREFIX}`)) {
    try {
      const apiKey = await prisma.apiKey.findUnique({
        where: { keyHash: hashApiKey(header.slice('Bearer '.length)) },
        select: { id: true, revokedAt: true, user: { select: { id: true, role: true } } },
      });
      if (!apiKey || apiKey.revokedAt) {
        res.status(401).json({ error: "Clé d'API invalide ou révoquée" });
        return;
      }
      req.user = { id: apiKey.user.id, role: apiKey.user.role };
      // Trace d'usage, sans retarder la requête.
      prisma.apiKey
        .update({ where: { id: apiKey.id }, data: { lastUsedAt: new Date() } })
        .catch(() => {});
      next();
    } catch (err) {
      next(err);
    }
    return;
  }

  const token = req.cookies?.token;
  if (token) {
    try {
      const payload = jwt.verify(token, config.jwtSecret) as AuthUser;
      req.user = { id: payload.id, role: payload.role };
    } catch {
      // Token invalide ou expiré : on continue en anonyme.
    }
  }
  next();
}

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
