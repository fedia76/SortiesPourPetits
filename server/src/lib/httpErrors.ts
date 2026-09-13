/**
 * Ce qu'une exception non rattrapée devient pour l'appelant.
 *
 * Le gestionnaire central renvoyait 500 « Erreur interne du serveur » à tout ce
 * qu'il ne reconnaissait pas. C'est juste pour un bug, et trompeur pour un refus
 * : un corps trop volumineux est une requête invalide, pas une panne. Rendu en
 * 500, il envoie chercher la cause dans le mauvais service — et le worker, qui
 * ne voit que le code, déclare la chasse « en échec (HTTP 500) » sans que la
 * ligne dise quoi que ce soit d'exploitable.
 *
 * Le classement vit ici, séparé d'`index.ts`, pour être éprouvé : c'est la
 * seule partie du gestionnaire qui décide quelque chose.
 */

/** Ce qu'on rend, et s'il faut en garder une trace dans le journal. */
export interface ReponseErreur {
  status: number;
  error: string;
  /** Vrai pour ce qui est notre faute : c'est ce qui mérite une trace. */
  log: boolean;
}

export function reponseErreur(err: Error): ReponseErreur {
  // Une photo refusée par multer, ou par nos propres contrôles de format.
  if (err.name === 'MulterError' || err.message.startsWith('Format de photo')) {
    return { status: 400, error: err.message, log: false };
  }
  // `body-parser` au-delà du plafond. Le dire en clair, avec le code qui va
  // avec : c'est l'appelant qui doit découper son envoi, pas nous qui sommes
  // tombés.
  if (err.name === 'PayloadTooLargeError') {
    return { status: 413, error: 'Corps de requête trop volumineux', log: false };
  }
  // JSON malformé : même raison, et ce n'est pas non plus une panne.
  if (err.name === 'SyntaxError' && 'body' in err) {
    return { status: 400, error: 'Corps de requête illisible (JSON malformé)', log: false };
  }
  return { status: 500, error: 'Erreur interne du serveur', log: true };
}
