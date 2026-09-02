import { createRouter, createWebHistory } from 'vue-router';
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

router.beforeEach(async (to) => {
  const auth = useAuthStore();
  await auth.init();
  if (to.meta.requiresAuth && !auth.isLoggedIn) {
    return { name: 'login', query: { redirect: to.fullPath } };
  }
  if (to.meta.requiresModerator && !auth.isModerator) return { name: 'home' };
  if (to.meta.requiresAdmin && !auth.isAdmin) return { name: 'home' };
});

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
