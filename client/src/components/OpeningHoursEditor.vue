<script setup lang="ts">
import type { OpeningHour } from '../types';
import { DAY_NAMES } from '../types';

const props = defineProps<{ modelValue: OpeningHour[] }>();
const emit = defineEmits<{ 'update:modelValue': [value: OpeningHour[]] }>();

function add() {
  emit('update:modelValue', [
    ...props.modelValue,
    { dayOfWeek: 2, openTime: '10:00', closeTime: '18:00' },
  ]);
}

function remove(index: number) {
  emit('update:modelValue', props.modelValue.filter((_, i) => i !== index));
}

function update(index: number, patch: Partial<OpeningHour>) {
  emit(
    'update:modelValue',
    props.modelValue.map((h, i) => (i === index ? { ...h, ...patch } : h)),
  );
}
</script>

<template>
  <div class="opening-hours-editor">
    <div v-for="(h, i) in modelValue" :key="i" class="line">
      <select
        :value="h.dayOfWeek"
        @change="update(i, { dayOfWeek: Number(($event.target as HTMLSelectElement).value) })"
      >
        <option v-for="(name, d) in DAY_NAMES" :key="d" :value="d">{{ name }}</option>
      </select>
      <input
        type="time"
        :value="h.openTime"
        @change="update(i, { openTime: ($event.target as HTMLInputElement).value })"
      />
      <span>→</span>
      <input
        type="time"
        :value="h.closeTime"
        @change="update(i, { closeTime: ($event.target as HTMLInputElement).value })"
      />
      <button type="button" class="btn ghost small" @click="remove(i)">✕</button>
    </div>
    <button type="button" class="btn secondary small" @click="add">+ Ajouter un créneau</button>
  </div>
</template>
