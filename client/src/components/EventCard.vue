<script setup lang="ts">
import { computed } from 'vue';
import type { EventItem } from '../types';
import { SETTING_LABELS } from '../types';

const props = defineProps<{ event: EventItem }>();

const priceLabel = computed(() =>
  props.event.isFree ? 'Gratuit' : `${props.event.price} €`,
);

const dateLabel = computed(() => {
  const fmt = (d: string) => new Date(d).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' });
  return props.event.dateStart === props.event.dateEnd
    ? fmt(props.event.dateStart)
    : `${fmt(props.event.dateStart)} → ${fmt(props.event.dateEnd)}`;
});
</script>

<template>
  <RouterLink :to="`/sorties/${event.id}`" class="event-card card">
    <img v-if="event.photoUrl" :src="event.photoUrl" :alt="event.title" class="photo" loading="lazy" />
    <div v-else class="photo placeholder">🎠</div>
    <div class="body">
      <div class="badges">
        <span class="badge price">{{ priceLabel }}</span>
        <span class="badge">{{ event.ageMin }}–{{ event.ageMax }} ans</span>
        <span class="badge">{{ SETTING_LABELS[event.setting] }}</span>
        <span v-if="event.distanceKm !== undefined" class="badge">📍 {{ event.distanceKm }} km</span>
      </div>
      <h3>{{ event.title }}</h3>
      <div class="muted">{{ event.venue.name }} · {{ event.venue.city }}</div>
      <div class="muted">📅 {{ dateLabel }}</div>
    </div>
  </RouterLink>
</template>
