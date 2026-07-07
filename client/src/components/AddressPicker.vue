<script setup lang="ts">
import { ref, watch } from 'vue';
import { searchAddress, type GeoSuggestion } from '../lib/geocode';

const props = defineProps<{
  modelValue: string;
  placeholder?: string;
}>();

const emit = defineEmits<{
  'update:modelValue': [value: string];
  select: [suggestion: GeoSuggestion];
}>();

const query = ref(props.modelValue);
const suggestions = ref<GeoSuggestion[]>([]);
const open = ref(false);
let debounce: ReturnType<typeof setTimeout> | undefined;

watch(
  () => props.modelValue,
  (v) => {
    if (v !== query.value) query.value = v;
  },
);

function onInput() {
  emit('update:modelValue', query.value);
  clearTimeout(debounce);
  debounce = setTimeout(async () => {
    suggestions.value = await searchAddress(query.value);
    open.value = suggestions.value.length > 0;
  }, 250);
}

function pick(s: GeoSuggestion) {
  query.value = s.label;
  emit('update:modelValue', s.label);
  emit('select', s);
  open.value = false;
}

function close() {
  // Petit délai pour laisser le clic sur une suggestion aboutir.
  setTimeout(() => (open.value = false), 150);
}
</script>

<template>
  <div class="autocomplete">
    <input
      v-model="query"
      type="text"
      :placeholder="placeholder ?? 'Tapez une adresse…'"
      autocomplete="off"
      @input="onInput"
      @focus="onInput"
      @blur="close"
    />
    <ul v-if="open">
      <li v-for="s in suggestions" :key="s.label" @mousedown.prevent="pick(s)">
        {{ s.label }}
      </li>
    </ul>
  </div>
</template>
