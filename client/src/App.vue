<script setup lang="ts">
import { useRouter } from 'vue-router';
import { useAuthStore } from './stores/auth';

const auth = useAuthStore();
const router = useRouter();

async function logout() {
  await auth.logout();
  router.push('/');
}
</script>

<template>
  <header class="site-header">
    <div class="inner">
      <RouterLink to="/" class="logo">Sorties<span>PourPetits</span></RouterLink>
      <nav class="nav">
        <RouterLink to="/">Explorer</RouterLink>
        <RouterLink v-if="auth.isLoggedIn" to="/proposer">Proposer une sortie</RouterLink>
        <RouterLink v-if="auth.isLoggedIn" to="/mes-sorties">Mes sorties</RouterLink>
        <RouterLink v-if="auth.isModerator" to="/moderation">Modération</RouterLink>
        <RouterLink v-if="auth.isAdmin" to="/admin">Admin</RouterLink>
        <template v-if="auth.isLoggedIn">
          <span class="muted">{{ auth.user!.displayName }}</span>
          <button class="btn ghost small" @click="logout">Déconnexion</button>
        </template>
        <template v-else>
          <RouterLink to="/connexion">Connexion</RouterLink>
          <RouterLink to="/inscription" class="btn small" style="color: #fff">Inscription</RouterLink>
        </template>
      </nav>
    </div>
  </header>

  <main>
    <RouterView />
  </main>

  <footer class="site-footer">
    SortiesPourPetits — des idées de sorties avec des enfants en Île-de-France 🎈
  </footer>
</template>
