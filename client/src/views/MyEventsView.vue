<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { api } from '../lib/api';
import type { EventItem } from '../types';
import { STATUS_LABELS } from '../types';

const events = ref<EventItem[]>([]);
const loading = ref(true);

onMounted(async () => {
  try {
    const data = await api.get<{ events: EventItem[] }>('/api/events/mine');
    events.value = data.events;
  } finally {
    loading.value = false;
  }
});
</script>

<template>
  <div class="container page">
    <h1>Mes sorties</h1>

    <div v-if="!loading && events.length === 0" class="empty">
      <p>Vous n'avez pas encore proposé de sortie.</p>
      <RouterLink to="/proposer" class="btn">Proposer ma première sortie</RouterLink>
    </div>

    <div v-if="events.length" class="table-wrap card">
      <table>
        <thead>
          <tr>
            <th>Titre</th>
            <th>Dates</th>
            <th>Statut</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="e in events" :key="e.id">
            <td>
              <RouterLink :to="`/sorties/${e.id}`">{{ e.title }}</RouterLink>
              <div v-if="e.status === 'REJECTED' && e.rejectionReason" class="muted">
                Motif : {{ e.rejectionReason }}
              </div>
            </td>
            <td>{{ e.dateStart }} → {{ e.dateEnd }}</td>
            <td><span :class="`badge status-${e.status}`">{{ STATUS_LABELS[e.status] }}</span></td>
            <td>
              <RouterLink :to="`/sorties/${e.id}/modifier`" class="btn ghost small">Modifier</RouterLink>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
