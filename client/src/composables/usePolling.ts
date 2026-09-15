import { onMounted, onUnmounted } from 'vue';

/**
 * Interroger le serveur à intervalle régulier, et **s'arrêter quand personne
 * ne regarde**.
 *
 * Quatre vues suivaient une exécution en cours avec leur propre `setInterval`,
 * recopié à l'identique : même intervalle codé en dur, même `clearInterval`
 * dans `onUnmounted`, même absence de la seule chose qui manquait vraiment —
 * un onglet oublié sur la console du scraper frappait l'API toutes les cinq
 * secondes jusqu'au lendemain, pour une page que personne n'avait sous les
 * yeux.
 *
 * `document.hidden` répond à cette question, et le navigateur prévient quand
 * elle change. La reprise relance **tout de suite** : revenir sur l'onglet
 * doit montrer l'état d'aujourd'hui, pas attendre le prochain battement.
 *
 * Le sondage s'arrête aussi de lui-même — `stop()` — ce dont chaque vue a
 * besoin : une exécution terminée ne bouge plus, et continuer à la demander
 * est du bruit.
 */
export interface Polling {
  /** Arrête définitivement. Sans effet s'il est déjà arrêté. */
  stop(): void;
  /** Relance après un `stop()`, ou après un changement de cible. */
  start(): void;
}

export function usePolling(tick: () => unknown, intervalMs: number): Polling {
  let timer: ReturnType<typeof setInterval> | undefined;
  let arrete = false;

  const battre = () => {
    if (arrete || document.hidden) return;
    // Chaque vue gère ses propres erreurs — c'est elle qui sait quoi en dire à
    // l'écran. Reste ce qu'elle n'aurait pas rattrapé : le laisser filer en
    // rejet non traité l'enterrerait dans la console du navigateur sous un
    // message qui ne nomme pas la vue. On le dit, et on continue de battre :
    // une coupure réseau ne doit pas figer une console pour de bon.
    Promise.resolve(tick()).catch((err: unknown) => {
      console.error('[sondage] un rafraîchissement a échoué', err);
    });
  };

  const armer = () => {
    if (arrete || timer !== undefined) return;
    timer = setInterval(battre, intervalMs);
  };

  const desarmer = () => {
    clearInterval(timer);
    timer = undefined;
  };

  const surVisibilite = () => {
    if (document.hidden) {
      desarmer();
      return;
    }
    armer();
    // L'onglet revient au premier plan : ce qu'il affiche date d'avant sa mise
    // en veille, et attendre l'intervalle le laisserait mentir jusque-là.
    battre();
  };

  onMounted(() => {
    document.addEventListener('visibilitychange', surVisibilite);
    if (!document.hidden) armer();
  });

  onUnmounted(() => {
    document.removeEventListener('visibilitychange', surVisibilite);
    desarmer();
  });

  return {
    stop() {
      arrete = true;
      desarmer();
    },
    start() {
      arrete = false;
      if (!document.hidden) armer();
    },
  };
}
