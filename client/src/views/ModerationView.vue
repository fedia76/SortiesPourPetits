<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { api } from '../lib/api';
import type { EventItem } from '../types';
import { SETTING_LABELS } from '../types';

const events = ref<EventItem[]>([]);
const loading = ref(true);
const error = ref('');

async function load() {
  loading.value = true;
  try {
    const data = await api.get<{ events: EventItem[] }>('/api/moderation/pending');
    events.value = data.events;
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Erreur';
  } finally {
    loading.value = false;
  }
}

async function moderate(id: number, action: 'approve' | 'reject') {
  let reason: string | undefined;
  if (action === 'reject') {
    reason = prompt('Motif du refus (visible par l’auteur) :') ?? undefined;
    if (reason === undefined) return;
  }
  try {
    await api.post(`/api/moderation/${id}`, { action, reason });
    events.value = events.value.filter((e) => e.id !== id);
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Erreur';
  }
}

onMounted(load);
</script>

<template>
  <div class="container page">
    <h1>Modération</h1>
    <p class="muted">{{ events.length }} sortie(s) en attente d'approbation.</p>
    <p v-if="error" class="error">{{ error }}</p>

    <div v-if="!loading && events.length === 0" class="empty">
      <p>🎉 Rien à modérer, tout est à jour !</p>
    </div>

    <div v-for="e in events" :key="e.id" class="card" style="padding: 1.2rem; margin-bottom: 1rem">
      <div class="badges" style="margin-bottom: 0.4rem">
        <span class="badge price">{{ e.isFree ? 'Gratuit' : `${e.price} €` }}</span>
        <span class="badge">{{ e.ageMin }}–{{ e.ageMax }} ans</span>
        <span class="badge">{{ SETTING_LABELS[e.setting] }}</span>
      </div>
      <h3>
        <RouterLink :to="`/sorties/${e.id}`">{{ e.title }}</RouterLink>
      </h3>
      <p class="muted">
        {{ e.venue.name }} · {{ e.venue.city }} · du {{ e.dateStart }} au {{ e.dateEnd }} ·
        proposé par {{ e.author.displayName }}
      </p>
      <p style="white-space: pre-line">{{ e.description }}</p>
      <img
        v-if="e.photoUrl"
        :src="e.photoUrl"
        :alt="e.title"
        style="max-width: 280px; border-radius: 10px"
      />
      <div class="row" style="margin-top: 0.8rem">
        <button class="btn" @click="moderate(e.id, 'approve')">✓ Approuver</button>
        <button class="btn danger" @click="moderate(e.id, 'reject')">✕ Refuser</button>
      </div>
    </div>
  </div>
</template>
