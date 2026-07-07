import { NextFunction, Request, Response } from 'express';
import jwt from 'jsonwebtoken';
import { Role } from '@prisma/client';
import { config } from '../config';

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

/** Décode le cookie de session s'il existe, sans exiger d'être connecté. */
export function attachUser(req: Request, _res: Response, next: NextFunction) {
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
