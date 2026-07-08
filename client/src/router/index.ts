import { createRouter, createWebHistory } from 'vue-router';
import { useAuthStore } from '../stores/auth';

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'home', component: () => import('../views/HomeView.vue') },
    { path: '/sorties/:id(\\d+)', name: 'event', component: () => import('../views/EventDetailView.vue') },
    { path: '/connexion', name: 'login', component: () => import('../views/LoginView.vue') },
    { path: '/inscription', name: 'register', component: () => import('../views/RegisterView.vue') },
    {
      path: '/proposer',
      name: 'propose',
      component: () => import('../views/EventFormView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/sorties/:id(\\d+)/modifier',
      name: 'edit-event',
      component: () => import('../views/EventFormView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/mes-sorties',
      name: 'my-events',
      component: () => import('../views/MyEventsView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/moderation',
      name: 'moderation',
      component: () => import('../views/ModerationView.vue'),
      meta: { requiresAuth: true, requiresModerator: true },
    },
    {
      path: '/admin',
      name: 'admin',
      component: () => import('../views/AdminUsersView.vue'),
      meta: { requiresAuth: true, requiresAdmin: true },
    },
    {
      path: '/admin/categories',
      name: 'admin-categories',
      component: () => import('../views/AdminCategoriesView.vue'),
      meta: { requiresAuth: true, requiresAdmin: true },
    },
    { path: '/:pathMatch(.*)*', redirect: '/' },
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

export default router;
