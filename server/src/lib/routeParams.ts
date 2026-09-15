/**
 * Lire un identifiant dans une adresse. Une fonction, et une seule.
 *
 * Il y en avait trois façons dans le même serveur : `Number.isInteger` après
 * coup dans la plupart des routes, un motif `:id(\d+)` sur le chemin dans
 * celles du banc, et **rien du tout** dans deux routes de `events.ts`. Là,
 * `PUT /api/events/abc` envoyait `NaN` à Prisma, qui refuse : le visiteur
 * recevait « Erreur interne du serveur » pour une adresse qu'il avait mal
 * tapée, et la trace partait au journal comme si le site était en panne.
 *
 * Les routes du banc gardent leurs motifs de chemin — `:id(\d+)`,
 * `:kind(agenda|sortie|nature)` —, mais parce qu'ils **distinguent des
 * routes**, pas parce qu'ils valident. À savoir si on met un jour la main sur
 * Express 5 : les motifs de chemin y ont été retirés, et ces déclarations y
 * deviendraient des chemins littéraux, en silence.
 */

/**
 * Un identifiant de ligne, ou `null` si ce n'en est pas un.
 *
 * Strict à dessein : que des chiffres. `Number` accepte volontiers `« -5 »`,
 * `« 1e3 »`, `« 0x10 »` et `«  12  »`, qui ne désignent aucune ligne et
 * n'apparaissent dans aucune adresse que le site fabrique.
 */
export function parseId(raw: unknown): number | null {
  if (typeof raw !== 'string' || !/^\d+$/.test(raw)) return null;
  const id = Number(raw);
  return Number.isSafeInteger(id) && id > 0 ? id : null;
}
