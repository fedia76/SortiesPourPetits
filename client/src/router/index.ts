import { createRouter, createWebHistory, type RouteLocationNormalized } from 'vue-router';
import { useAuthStore } from '../stores/auth';
import { setPageSeo } from '../lib/seo';

/**
 * `title` et `noindex` accompagnent les pages qui ne produisent pas
 * elles-mêmes leurs métadonnées. `noindex` y est systématique : ce sont des
 * formulaires et des écrans qui demandent un compte — rien qu'un moteur ait à
 * garder, et le serveur le leur dit déjà (voir `server/src/seo/routes.ts`).
 */
const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'home', component: () => import('../views/HomeView.vue') },
    {
      path: '/sorties/:id(\\d+)',
      name: 'event',
      component: () => import('../views/EventDetailView.vue'),
    },
    // Après la fiche, et volontairement : les chiffres désignent une sortie,
    // le reste une zone. Le serveur applique la même règle.
    {
      path: '/sorties/:slug([a-z0-9][a-z0-9-]*)',
      name: 'area',
      component: () => import('../views/AreaView.vue'),
    },
    {
      path: '/connexion',
      name: 'login',
      component: () => import('../views/LoginView.vue'),
      meta: { title: 'Connexion', noindex: true },
    },
    {
      path: '/inscription',
      name: 'register',
      component: () => import('../views/RegisterView.vue'),
      meta: { title: 'Inscription', noindex: true },
    },
    {
      path: '/proposer',
      name: 'propose',
      component: () => import('../views/EventFormView.vue'),
      meta: { title: 'Proposer une sortie', noindex: true, requiresAuth: true },
    },
    {
      path: '/sorties/:id(\\d+)/modifier',
      name: 'edit-event',
      component: () => import('../views/EventFormView.vue'),
      meta: { title: 'Modifier une sortie', noindex: true, requiresAuth: true },
    },
    {
      path: '/mes-sorties',
      name: 'my-events',
      component: () => import('../views/MyEventsView.vue'),
      meta: { title: 'Mes sorties', noindex: true, requiresAuth: true },
    },
    {
      path: '/moderation',
      name: 'moderation',
      component: () => import('../views/ModerationView.vue'),
      meta: { title: 'Modération', noindex: true, requiresAuth: true, requiresModerator: true },
    },
    {
      path: '/cles-api',
      name: 'api-keys',
      component: () => import('../views/ApiKeysView.vue'),
      meta: { title: "Clés d'API", noindex: true, requiresAuth: true, requiresModerator: true },
    },
    {
      path: '/admin/scraper',
      name: 'admin-scraper',
      component: () => import('../views/AdminScraperView.vue'),
      meta: {
        title: 'Recherche automatique',
        noindex: true,
        requiresAuth: true,
        requiresModerator: true,
      },
    },
    {
      path: '/admin/scraper/agregateurs',
      name: 'admin-scraper-aggregators',
      component: () => import('../views/AdminAggregatorsView.vue'),
      meta: {
        title: 'Agrégateurs',
        noindex: true,
        requiresAuth: true,
        requiresModerator: true,
      },
    },
    {
      path: '/admin/scraper/stats',
      name: 'admin-scraper-stats',
      component: () => import('../views/AdminScraperStatsView.vue'),
      meta: {
        title: 'Statistiques du scraping',
        noindex: true,
        requiresAuth: true,
        requiresModerator: true,
      },
    },
    {
      path: '/admin/scraper/qualite',
      name: 'admin-scraper-quality',
      component: () => import('../views/AdminScraperQualityView.vue'),
      meta: {
        title: 'Qualité du scraping',
        noindex: true,
        requiresAuth: true,
        requiresModerator: true,
      },
    },
    {
      path: '/admin/scraper/memoire',
      name: 'admin-scraper-memory',
      component: () => import('../views/AdminScraperMemoryView.vue'),
      meta: {
        title: 'Mémoire du scraper',
        noindex: true,
        requiresAuth: true,
        requiresModerator: true,
      },
    },
    {
      path: '/admin/scraper/runs/:id(\\d+)',
      name: 'admin-scraper-run',
      component: () => import('../views/AdminScraperRunView.vue'),
      meta: { title: 'Exécution', noindex: true, requiresAuth: true, requiresModerator: true },
    },
    {
      path: '/admin/scraper/runs/:id(\\d+)/debug',
      name: 'admin-scraper-run-debug',
      component: () => import('../views/AdminScraperRunDebugView.vue'),
      meta: {
        title: "Débogage d'une exécution",
        noindex: true,
        requiresAuth: true,
        requiresModerator: true,
      },
    },
    {
      path: '/admin',
      name: 'admin',
      component: () => import('../views/AdminUsersView.vue'),
      meta: { title: 'Administration', noindex: true, requiresAuth: true, requiresAdmin: true },
    },
    {
      path: '/admin/categories',
      name: 'admin-categories',
      component: () => import('../views/AdminCategoriesView.vue'),
      meta: { title: 'Catégories', noindex: true, requiresAuth: true, requiresAdmin: true },
    },
    {
      path: '/admin/zones',
      name: 'admin-areas',
      component: () => import('../views/AdminAreasView.vue'),
      meta: { title: 'Zones', noindex: true, requiresAuth: true, requiresAdmin: true },
    },
    // Le banc fabrique la vérité de référence sur laquelle les mesures
    // s'appuieront : administrateur, et pas modérateur comme le reste de la
    // console du scraper. Une vérité que plusieurs mains modifient sans se
    // concerter n'en est plus une.
    {
      path: '/admin/evaluation',
      name: 'admin-eval',
      component: () => import('../views/AdminEvalView.vue'),
      meta: { title: "Banc d'évaluation", noindex: true, requiresAuth: true, requiresAdmin: true },
    },
    {
      path: '/admin/evaluation/mesures',
      name: 'admin-eval-runs',
      component: () => import('../views/AdminEvalRunsView.vue'),
      meta: { title: 'Mesures du banc', noindex: true, requiresAuth: true, requiresAdmin: true },
    },
    // Les pages légales : publiques, indexables, et servies par le serveur
    // avant que Vue ne démarre. Une mention légale doit rester lisible quand
    // le JavaScript ne s'exécute pas — c'est même tout l'intérêt de l'imposer.
    // `legalSlug` dit à la vue lequel des deux textes afficher ; il vaut aussi
    // l'adresse de l'appel d'API, et le serveur écrit sa réponse dans le
    // document (voir `server/src/seo/pages.ts`).
    {
      path: '/mentions-legales',
      name: 'legal-notice',
      component: () => import('../views/LegalView.vue'),
      meta: { title: 'Mentions légales', legalSlug: 'mentions-legales' },
    },
    {
      path: '/confidentialite',
      name: 'privacy',
      component: () => import('../views/LegalView.vue'),
      meta: { title: 'Politique de confidentialité', legalSlug: 'confidentialite' },
    },
    // Une adresse inconnue affichait l'accueil, par redirection : le visiteur
    // n'y comprenait rien, et le serveur, lui, répond 404 sur cette adresse.
    {
      path: '/:pathMatch(.*)*',
      name: 'not-found',
      component: () => import('../views/NotFoundView.vue'),
    },
  ],
  scrollBehavior: () => ({ top: 0 }),
});

/**
 * Qui a le droit d'ouvrir cette page.
 *
 * Ce garde ne **protège** rien : le serveur relit le rôle en base à chaque
 * requête, et c'est lui la barrière. Il évite seulement d'ouvrir un écran qui
 * répondrait 403 à sa première requête — et, pour ce qui demande un compte,
 * il retient l'adresse voulue pour y ramener après la connexion.
 *
 * Exporté pour être éprouvé sans monter vingt-six vues.
 */
export async function gardeDAcces(to: RouteLocationNormalized) {
  const auth = useAuthStore();
  await auth.init();
  if (to.meta.requiresAuth && !auth.isLoggedIn) {
    return { name: 'login', query: { redirect: to.fullPath } };
  }
  if (to.meta.requiresModerator && !auth.isModerator) return { name: 'home' };
  if (to.meta.requiresAdmin && !auth.isAdmin) return { name: 'home' };
}

router.beforeEach(gardeDAcces);

/**
 * Le titre d'une page, posé dès la navigation confirmée.
 *
 * L'accueil et la fiche d'une sortie n'en déclarent pas : le leur dépend de ce
 * qu'ils chargent, et ils l'écrivent eux-mêmes une fois les données arrivées.
 */
router.afterEach((to) => {
  const title = to.meta.title as string | undefined;
  if (title) setPageSeo({ title, noindex: to.meta.noindex === true });
});

export default router;
