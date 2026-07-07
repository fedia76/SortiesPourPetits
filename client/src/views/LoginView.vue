<script setup lang="ts">
import { ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useAuthStore } from '../stores/auth';

const auth = useAuthStore();
const route = useRoute();
const router = useRouter();

const email = ref('');
const password = ref('');
const error = ref('');
const loading = ref(false);

async function submit() {
  error.value = '';
  loading.value = true;
  try {
    await auth.login(email.value, password.value);
    router.push((route.query.redirect as string) ?? '/');
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Erreur de connexion';
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <div class="container">
    <form class="form narrow card" @submit.prevent="submit">
      <h1>Connexion</h1>
      <p v-if="error" class="error">{{ error }}</p>
      <div class="field">
        <label for="email">Email</label>
        <input id="email" v-model="email" type="email" required autocomplete="email" />
      </div>
      <div class="field">
        <label for="password">Mot de passe</label>
        <input id="password" v-model="password" type="password" required autocomplete="current-password" />
      </div>
      <button class="btn" type="submit" :disabled="loading">
        {{ loading ? 'Connexion…' : 'Se connecter' }}
      </button>
      <p class="muted">
        Pas encore de compte ?
        <RouterLink to="/inscription">Inscrivez-vous</RouterLink>
      </p>
    </form>
  </div>
</template>
