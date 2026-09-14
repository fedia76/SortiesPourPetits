/**
 * Ce qu'on montre quand quelque chose a raté.
 *
 * La ligne qui décidait ça était recopiée quarante-huit fois, avec quatre
 * libellés de repli différents — et aucune des copies ne distinguait une
 * coupure réseau, qui est pourtant le cas le plus fréquent et le seul où le
 * visiteur peut faire quelque chose.
 */
import { describe, expect, test } from 'vitest';

import { ApiError } from './api';
import { demandeUneConnexion, estIntrouvable, messageDe } from './erreurs';

describe('le message affiché', () => {
  test('celui du serveur, quand il en donne un', () => {
    expect(messageDe(new ApiError(409, 'Cet événement a déjà été modéré'))).toBe(
      'Cet événement a déjà été modéré',
    );
  });

  test('celui de l’erreur, pour tout ce qui en est une', () => {
    expect(messageDe(new Error('Format de photo non supporté'))).toBe(
      'Format de photo non supporté',
    );
  });

  test('le repli, quand il n’y a rien à dire', () => {
    expect(messageDe(undefined)).toBe('Une erreur est survenue');
    expect(messageDe(null, 'Chargement impossible')).toBe('Chargement impossible');
    expect(messageDe({ pas: 'une erreur' }, 'Envoi impossible')).toBe('Envoi impossible');
    // Une `Error` sans message ne vaut pas mieux que pas d'erreur du tout.
    expect(messageDe(new Error(''), 'Chargement impossible')).toBe('Chargement impossible');
  });

  test('une chaîne levée telle quelle est lisible', () => {
    expect(messageDe('Le lieu n’est pas géolocalisé')).toBe('Le lieu n’est pas géolocalisé');
  });
});

describe('la coupure réseau', () => {
  test('se dit en français, et dit quoi faire', () => {
    // Le visiteur recevait « Failed to fetch », qui ne dit ni ce qui s'est
    // passé ni ce qu'il peut y faire.
    for (const message of [
      'Failed to fetch',
      'Load failed',
      'NetworkError when attempting to fetch resource.',
      'Network request failed',
    ]) {
      expect(messageDe(new TypeError(message))).toMatch(/Connexion au serveur impossible/);
    }
  });

  test('un vrai bug du front n’est pas maquillé en panne d’Internet', () => {
    // `fetch` lève un `TypeError`, mais un `undefined` déréférencé aussi :
    // s'en tenir au type enverrait le visiteur vérifier sa box pour un bug.
    const bug = new TypeError("Cannot read properties of undefined (reading 'title')");
    expect(messageDe(bug)).toBe("Cannot read properties of undefined (reading 'title')");
  });
});

describe('ce que la vue peut décider', () => {
  test('une session expirée se reconnaît', () => {
    // Sept jours de session expirent pendant qu'un onglet reste ouvert :
    // afficher « Authentification requise » n'aide personne.
    expect(demandeUneConnexion(new ApiError(401, 'Authentification requise'))).toBe(true);
    expect(demandeUneConnexion(new ApiError(403, 'Droits insuffisants'))).toBe(false);
    expect(demandeUneConnexion(new Error('Failed to fetch'))).toBe(false);
  });

  test('un introuvable est définitif, une coupure ne l’est pas', () => {
    // C'est ce qui distingue un suivi qu'il faut arrêter d'une panne passagère
    // qu'il faut endurer.
    expect(estIntrouvable(new ApiError(404, 'Exécution introuvable'))).toBe(true);
    expect(estIntrouvable(new ApiError(502, 'Erreur 502'))).toBe(false);
    expect(estIntrouvable(new TypeError('Failed to fetch'))).toBe(false);
  });
});
