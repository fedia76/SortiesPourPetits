<script setup lang="ts">
import { ref } from 'vue';
import { useRouter } from 'vue-router';
import { useAuthStore } from '../stores/auth';

const auth = useAuthStore();
const router = useRouter();

const displayName = ref('');
const email = ref('');
const password = ref('');
const error = ref('');
const loading = ref(false);

async function submit() {
  error.value = '';
  loading.value = true;
  try {
    await auth.register(email.value, password.value, displayName.value);
    router.push('/');
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Erreur d'inscription";
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <div class="container">
    <form class="form narrow card" @submit.prevent="submit">
      <h1>Inscription</h1>
      <p class="muted">Créez un compte pour proposer vos idées de sorties.</p>
      <p v-if="error" class="error">{{ error }}</p>
      <div class="field">
        <label for="name">Nom affiché</label>
        <input id="name" v-model="displayName" type="text" required minlength="2" maxlength="50" />
      </div>
      <div class="field">
        <label for="email">Email</label>
        <input id="email" v-model="email" type="email" required autocomplete="email" />
      </div>
      <div class="field">
        <label for="password">Mot de passe</label>
        <input
          id="password"
          v-model="password"
          type="password"
          required
          minlength="8"
          autocomplete="new-password"
        />
        <span class="hint">8 caractères minimum</span>
      </div>
      <button class="btn" type="submit" :disabled="loading">
        {{ loading ? 'Création…' : 'Créer mon compte' }}
      </button>
      <p class="muted">
        Déjà inscrit ?
        <RouterLink to="/connexion">Connectez-vous</RouterLink>
      </p>
    </form>
  </div>
</template>
