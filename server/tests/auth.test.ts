/**
 * D'où vient le rôle de l'appelant — la seule chose que ce middleware décide.
 *
 * Le jeton de session le portait, et il est signé : impossible à falsifier,
 * donc on s'en contentait. Mais un jeton vit sept jours, et ce qu'il affirme
 * ne vieillit pas avec le compte. Retirer ses droits à un modérateur ne les
 * lui retirait pas : il gardait la file de modération, la console du scraper
 * et le banc jusqu'à l'expiration de son cookie, sans que rien dans
 * l'administration ne le laisse deviner.
 *
 * Ces tests posent donc systématiquement un jeton qui **dit autre chose** que
 * la base : c'est la base qui doit gagner.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import type { NextFunction, Request, Response } from 'express';
import { Role } from '@prisma/client';

import {
  attachUserWith,
  hashApiKey,
  signToken,
  type AuthLookups,
  type AuthUser,
} from '../src/middleware/auth';

/** Ce que le middleware a fait de la requête, une fois passé. */
interface Passage {
  user?: AuthUser;
  viaApiKey?: boolean;
  status?: number;
  body?: unknown;
  cookieEfface: boolean;
  suivant: boolean;
}

/** Une base qui contient ce qu'on lui dit, et qui compte ses lectures. */
function base(options: {
  user?: AuthUser | null;
  apiKey?: { id: number; revokedAt: Date | null; user: AuthUser } | null;
}) {
  const lectures = { user: 0, apiKey: 0, touched: [] as number[] };
  const lookups: AuthLookups = {
    async user() {
      lectures.user += 1;
      return options.user ?? null;
    },
    async apiKey() {
      lectures.apiKey += 1;
      return options.apiKey ?? null;
    },
    touchApiKey(id) {
      lectures.touched.push(id);
    },
  };
  return { lookups, lectures };
}

/** Joue le middleware sur une requête décrite par ses en-têtes et son cookie. */
async function passe(
  lookups: AuthLookups,
  entrant: { token?: string; authorization?: string },
): Promise<Passage> {
  const passage: Passage = { cookieEfface: false, suivant: false };
  const req = {
    headers: entrant.authorization ? { authorization: entrant.authorization } : {},
    cookies: entrant.token ? { token: entrant.token } : {},
  } as unknown as Request;
  const res = {
    status(code: number) {
      passage.status = code;
      return this;
    },
    json(body: unknown) {
      passage.body = body;
      return this;
    },
    clearCookie() {
      passage.cookieEfface = true;
      return this;
    },
  } as unknown as Response;
  const next = (() => {
    passage.suivant = true;
  }) as NextFunction;

  await attachUserWith(lookups)(req, res, next);
  passage.user = req.user;
  passage.viaApiKey = req.viaApiKey;
  return passage;
}

// ────────────────────────────────────────────────────────── cookie de session

test('le rôle vient de la base, pas du jeton', async () => {
  // Le jeton a été signé quand ce compte était modérateur. Il ne l'est plus.
  const jeton = signToken({ id: 7, role: Role.MODERATOR });
  const { lookups, lectures } = base({ user: { id: 7, role: Role.USER } });

  const passage = await passe(lookups, { token: jeton });

  assert.deepEqual(passage.user, { id: 7, role: Role.USER });
  assert.equal(lectures.user, 1, 'la base est consultée à chaque requête authentifiée');
});

test('une promotion prend effet sans attendre une reconnexion', async () => {
  const jeton = signToken({ id: 7, role: Role.USER });
  const { lookups } = base({ user: { id: 7, role: Role.ADMIN } });

  assert.equal((await passe(lookups, { token: jeton })).user?.role, Role.ADMIN);
});

test('un compte supprimé ne vaut plus rien, et son cookie est effacé', async () => {
  const jeton = signToken({ id: 7, role: Role.ADMIN });
  const { lookups } = base({ user: null });

  const passage = await passe(lookups, { token: jeton });

  assert.equal(passage.user, undefined);
  assert.ok(passage.cookieEfface);
  assert.ok(passage.suivant, 'la requête continue en anonyme, elle n’est pas refusée');
});

test('un jeton illisible laisse passer en anonyme, sans lire la base', async () => {
  const { lookups, lectures } = base({ user: { id: 7, role: Role.ADMIN } });

  const passage = await passe(lookups, { token: 'ceci-n-est-pas-un-jeton' });

  assert.equal(passage.user, undefined);
  assert.equal(lectures.user, 0);
  assert.ok(passage.suivant);
});

test('sans cookie, aucune lecture en base', async () => {
  const { lookups, lectures } = base({ user: { id: 7, role: Role.ADMIN } });

  const passage = await passe(lookups, {});

  assert.equal(passage.user, undefined);
  assert.equal(lectures.user, 0, 'le trafic public anonyme ne paie pas cette requête');
  assert.ok(passage.suivant);
});

test('une base injoignable est une panne, pas un visiteur anonyme', async () => {
  const jeton = signToken({ id: 7, role: Role.ADMIN });
  const lookups: AuthLookups = {
    async user() {
      throw new Error('base injoignable');
    },
    async apiKey() {
      return null;
    },
    touchApiKey() {},
  };

  // Rattraper ici dégraderait silencieusement un modérateur en visiteur. On
  // laisse remonter : le filet d'`asyncRoutes` rend 500, ce qui se voit.
  await assert.rejects(() => passe(lookups, { token: jeton }), /base injoignable/);
});

// ───────────────────────────────────────────────────────────────── clé d'API

test('une clé valide porte le rôle de son compte, relu en base', async () => {
  const { lookups, lectures } = base({
    apiKey: { id: 3, revokedAt: null, user: { id: 12, role: Role.MODERATOR } },
  });

  const passage = await passe(lookups, { authorization: 'Bearer spp_abc' });

  assert.deepEqual(passage.user, { id: 12, role: Role.MODERATOR });
  assert.equal(passage.viaApiKey, true);
  assert.deepEqual(lectures.touched, [3], 'l’usage est tracé');
});

test('une clé révoquée est refusée', async () => {
  const { lookups } = base({
    apiKey: { id: 3, revokedAt: new Date(), user: { id: 12, role: Role.ADMIN } },
  });

  const passage = await passe(lookups, { authorization: 'Bearer spp_abc' });

  assert.equal(passage.status, 401);
  assert.equal(passage.suivant, false, 'la requête s’arrête là');
});

test('une clé inconnue est refusée', async () => {
  const { lookups } = base({ apiKey: null });

  assert.equal((await passe(lookups, { authorization: 'Bearer spp_inconnue' })).status, 401);
});

test('un cookie accompagné d’une clé : c’est la clé qui parle', async () => {
  const jeton = signToken({ id: 7, role: Role.ADMIN });
  const { lookups } = base({
    user: { id: 7, role: Role.ADMIN },
    apiKey: { id: 3, revokedAt: null, user: { id: 12, role: Role.USER } },
  });

  const passage = await passe(lookups, { token: jeton, authorization: 'Bearer spp_abc' });

  assert.deepEqual(passage.user, { id: 12, role: Role.USER });
  assert.equal(passage.viaApiKey, true);
});

test('un Bearer qui n’est pas une clé du site retombe sur le cookie', async () => {
  const jeton = signToken({ id: 7, role: Role.USER });
  const { lookups } = base({ user: { id: 7, role: Role.MODERATOR } });

  const passage = await passe(lookups, {
    token: jeton,
    authorization: 'Bearer eyJhbGciOi.autre-chose',
  });

  assert.deepEqual(passage.user, { id: 7, role: Role.MODERATOR });
  assert.equal(passage.viaApiKey, undefined);
});

test('le hachage d’une clé est stable et ne rend jamais la clé', () => {
  const empreinte = hashApiKey('spp_secret');
  assert.equal(empreinte, hashApiKey('spp_secret'));
  assert.ok(!empreinte.includes('spp_'));
  assert.equal(empreinte.length, 64);
});
