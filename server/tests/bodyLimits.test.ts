/**
 * Le plafond de corps des requêtes, éprouvé sur une vraie application Express.
 *
 * Ce fichier existe parce que la règle qu'il verrouille est invisible à la
 * lecture : un `express.json({ limit })` posé sur une route **ne s'applique
 * pas** si un `express.json()` global a été monté avant lui. Le code compile,
 * la route a l'air d'avoir son plafond, et elle a celui du parseur global.
 *
 * Le banc a vécu des semaines ainsi : ses comptes rendus portent du HTML
 * gzippé, donc dépassent les 100 ko par défaut, et repartaient en « Erreur
 * interne du serveur ». Aucune chasse ne pouvait aboutir. Rien ne l'aurait dit
 * avant que quelqu'un ne lise les journaux des deux services en même temps.
 *
 * On monte donc l'application comme `index.ts` la monte — mêmes fonctions, pas
 * une copie de la règle — et on la questionne par le réseau : c'est le seul
 * niveau où le bug était observable.
 */
import { test, after } from 'node:test';
import assert from 'node:assert/strict';
import express from 'express';
import type { NextFunction, Request, Response as ExpressResponse } from 'express';
import type { AddressInfo } from 'node:net';

import { mountJsonParsers } from '../src/lib/bodyLimits';
import { reponseErreur } from '../src/lib/httpErrors';

const app = express();
mountJsonParsers(app);
// Deux routes qui ne font rien d'autre que dire ce qu'elles ont reçu : le sujet
// est le parseur, pas ce qu'il y a derrière.
app.post('/api/eval/hunts/1/pages', (req, res) => res.json({ octets: JSON.stringify(req.body).length }));
app.post('/api/events', (req, res) => res.json({ octets: JSON.stringify(req.body).length }));
app.use((err: Error, _req: Request, res: ExpressResponse, _next: NextFunction) => {
  const { status, error } = reponseErreur(err);
  res.status(status).json({ error });
});

const server = app.listen(0);
after(() => server.close());
const port = () => (server.address() as AddressInfo).port;

/** Poste un corps JSON d'environ `ko` kilo-octets. */
async function poste(chemin: string, ko: number): Promise<Response> {
  return fetch(`http://127.0.0.1:${port()}${chemin}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ pages: [{ html: 'x'.repeat(ko * 1024) }] }),
  });
}

test('le banc accepte un compte rendu bien au-delà du plafond par défaut', async () => {
  // 5 Mo : le pire cas d'un paquet de chasse — cinq pages d'un mégaoctet de
  // HTML gzippé en base64. C'est exactement ce qui repartait en 500.
  const res = await poste('/api/eval/hunts/1/pages', 5 * 1024);
  assert.equal(res.status, 200);
});

test('le reste du site garde son plafond serré', async () => {
  // `POST /api/events` est ouvert : lui donner les 12 Mo du banc ferait d'un
  // correctif du banc une surface d'attaque sur le site.
  const res = await poste('/api/events', 300);
  assert.equal(res.status, 413);
});

test('un corps trop gros est une requête refusée, pas une panne', async () => {
  // Le 500 d'avant envoyait chercher la cause dans le mauvais service : le
  // worker n'affichait que « HTTP 500 — Erreur interne du serveur ».
  const res = await poste('/api/eval/hunts/1/pages', 13 * 1024);
  assert.equal(res.status, 413);
  const corps = (await res.json()) as { error: string };
  assert.equal(corps.error, 'Corps de requête trop volumineux');
});

test('un JSON malformé ne passe pas non plus pour une panne', async () => {
  const res = await fetch(`http://127.0.0.1:${port()}/api/events`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: '{"pas du json"',
  });
  assert.equal(res.status, 400);
});

test('une photo refusée reste un 400, avec son motif', () => {
  const err = new Error('Format de photo non accepté');
  assert.deepEqual(reponseErreur(err), {
    status: 400,
    error: 'Format de photo non accepté',
    log: false,
  });
});

test('ce qui reste inconnu est une panne, et se journalise', () => {
  const { status, log } = reponseErreur(new TypeError('x is not a function'));
  assert.equal(status, 500);
  assert.equal(log, true);
});
