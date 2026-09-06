/**
 * L'archive des pages du banc : le HTML tel que le site l'a servi ce jour-là.
 *
 * C'est ce qui fait la différence entre un banc et un instantané. Sans
 * l'archive, rejouer la mesure après avoir touché à `links_of` obligerait à
 * retélécharger la page ; on comparerait alors un nouveau code à une nouvelle
 * page, et l'écart ne dirait plus lequel des deux a bougé. Geler l'entrée sert
 * précisément à ne laisser bouger qu'une variable à la fois.
 *
 * ## Gzippé, et sur le disque
 *
 * Le HTML compresse à peu près huit fois. Le garder tel quel en base pèserait
 * pour rien, et une colonne `MEDIUMTEXT` chargée à chaque lecture d'un agenda
 * rendrait la console lente pour une donnée que personne ne regarde en
 * temps normal.
 *
 * Le worker envoie donc **déjà compressé**, en base64 : les octets voyagent
 * tels quels et sont écrits sans être déballés. Le serveur ne décompresse
 * qu'au moment où quelqu'un demande à relire la page.
 */
import crypto from 'crypto';
import fs from 'fs';
import path from 'path';
import zlib from 'zlib';
import { promisify } from 'util';
import { config } from '../config';

const gunzip = promisify(zlib.gunzip);

/** Les pages du banc vivent à part des photos : elles ne sont jamais servies en statique. */
function dir(): string {
  return path.join(config.uploadsDir, 'eval');
}

/**
 * Écrit une page archivée et rend son chemin, ou une chaîne vide si l'écriture
 * échoue.
 *
 * Une archive ratée ne fait pas échouer le compte rendu : le banc perdrait
 * alors la mesure — qui est le travail — pour avoir manqué le confort du
 * rejeu. La console dit quelles pages ne sont pas archivées.
 */
export async function saveEvalPage(gzipBase64: string): Promise<string> {
  try {
    await fs.promises.mkdir(dir(), { recursive: true });
    const name = `${crypto.randomBytes(16).toString('hex')}.html.gz`;
    await fs.promises.writeFile(path.join(dir(), name), Buffer.from(gzipBase64, 'base64'));
    return name;
  } catch {
    return '';
  }
}

/** Le HTML d'une page archivée, déballé. Nul si le fichier a disparu. */
export async function readEvalPage(name: string): Promise<string | null> {
  try {
    const raw = await fs.promises.readFile(path.join(dir(), path.basename(name)));
    return (await gunzip(raw)).toString('utf-8');
  } catch {
    return null;
  }
}

/**
 * Efface des pages archivées. Silencieux sur ce qui n'existe plus.
 *
 * Prisma efface les lignes en cascade, pas les fichiers : sans cet appel
 * explicite, chaque analyse relancée laisserait derrière elle un fichier que
 * plus rien ne référence.
 */
export async function deleteEvalPages(names: (string | null)[]): Promise<void> {
  await Promise.all(
    names
      .filter((name): name is string => !!name)
      .map((name) => fs.promises.unlink(path.join(dir(), path.basename(name))).catch(() => {})),
  );
}
