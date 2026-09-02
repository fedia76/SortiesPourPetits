<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import AddressPicker from '../components/AddressPicker.vue';
import type { GeoSuggestion } from '../lib/geocode';
import { api } from '../lib/api';
import type { Category, EventInput, EventItem, Setting } from '../types';
import { dayLabel, hasCoordinates, hasPrice } from '../types';

const route = useRoute();
const router = useRouter();

const editId = computed(() => (route.name === 'edit-event' ? Number(route.params.id) : null));

/**
 * La page où la recherche automatique avait repéré la sortie, quand ce n'est
 * pas celle qu'on propose. Affichée, jamais modifiable : c'est un fait sur la
 * façon dont la sortie est arrivée ici, pas un champ de la fiche. Corriger le
 * lien source au-dessus ne réécrit pas d'où il vient.
 */
const foundOn = ref('');

const form = reactive({
  title: '',
  description: '',
  sourceUrl: '',
  isFree: false,
  price: '' as string | number,
  ageMin: '' as string | number,
  ageMax: '' as string | number,
  isPermanent: false,
  dateStart: '',
  dateEnd: '',
  /** Jours de représentation. Vide = tous les jours de la période. */
  dates: [] as string[],
  openTime: '',
  closeTime: '',
  setting: '' as Setting | '',
  categoryId: null as number | null,
  venueName: '',
  address: '',
  city: '',
  postalCode: '',
  lat: null as number | null,
  lng: null as number | null,
});

/**
 * Le calendrier travaille en objets `Date`, la sortie en `AAAA-MM-JJ`.
 *
 * La conversion se fait sur les composantes locales, jamais par
 * `toISOString()` : depuis Paris, minuit local est 22 h UTC la veille, et le
 * 3 septembre sélectionné repartirait en `2026-09-02`. Toutes les dates de
 * représentation seraient décalées d'un jour, sans le moindre message.
 */
function dateToDay(value: Date): string {
  const deuxChiffres = (n: number) => String(n).padStart(2, '0');
  return `${value.getFullYear()}-${deuxChiffres(value.getMonth() + 1)}-${deuxChiffres(value.getDate())}`;
}

/** Midi plutôt que minuit : aucun changement d'heure ne peut faire basculer le jour. */
function dayToDate(day: string): Date {
  return new Date(`${day}T12:00:00`);
}

/**
 * Les dates telles que `<v-date-picker multiple>` les veut.
 *
 * Il rend un tableau d'objets `Date` ; on le filtre plutôt que de le croire,
 * son type déclaré étant `unknown[]`.
 */
const selectedDates = computed<unknown[]>({
  get: () => form.dates.map(dayToDate),
  set: (value) => {
    form.dates = value
      .filter((v): v is Date => v instanceof Date)
      .map(dateToDay)
      .sort();
  },
});

/** Bornes du calendrier : le serveur refuse une date hors de la période. */
const periodStart = computed(() => (form.dateStart ? dayToDate(form.dateStart) : undefined));
const periodEnd = computed(() => (form.dateEnd ? dayToDate(form.dateEnd) : undefined));

/**
 * Dates devenues hors période — la période a été resserrée après coup.
 *
 * Le calendrier ne peut plus les montrer, et le serveur refusera la sortie
 * entière : mieux vaut les nommer ici que de laisser tomber un message
 * d'erreur à l'enregistrement.
 */
const outOfPeriod = computed(() =>
  form.dates.filter(
    (d) => (form.dateStart && d < form.dateStart) || (form.dateEnd && d > form.dateEnd),
  ),
);

function removeDate(day: string) {
  form.dates = form.dates.filter((d) => d !== day);
}

function dropOutOfPeriod() {
  form.dates = form.dates.filter((d) => !outOfPeriod.value.includes(d));
}

const photo = ref<File | null>(null);
const photoPreview = ref('');
const existingPhotoUrl = ref<string | null>(null);
const error = ref('');
const loading = ref(false);
const categories = ref<Category[]>([]);

function onAddressSelect(s: GeoSuggestion) {
  form.address = s.name || s.label;
  form.city = s.city;
  form.postalCode = s.postcode;
  form.lat = s.lat;
  form.lng = s.lng;
}

function onPhotoChange(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0] ?? null;
  photo.value = file;
  photoPreview.value = file ? URL.createObjectURL(file) : '';
}

async function submit() {
  error.value = '';
  if (form.lat === null || form.lng === null) {
    error.value = "Sélectionnez l'adresse du lieu dans les suggestions (pour la géolocalisation).";
    return;
  }
  if (form.categoryId === null) {
    error.value = 'Choisissez une catégorie.';
    return;
  }
  const payload: EventInput = {
    title: form.title,
    description: form.description,
    sourceUrl: form.sourceUrl.trim() === '' ? null : form.sourceUrl.trim(),
    isFree: form.isFree,
    price: form.isFree || form.price === '' ? null : Number(form.price),
    ageMin: form.ageMin === '' ? null : Number(form.ageMin),
    ageMax: form.ageMax === '' ? null : Number(form.ageMax),
    isPermanent: form.isPermanent,
    dateStart: form.isPermanent || form.dateStart === '' ? null : form.dateStart,
    dateEnd: form.isPermanent || form.dateEnd === '' ? null : form.dateEnd,
    dates: form.isPermanent ? [] : [...form.dates].sort(),
    openTime: form.openTime === '' ? null : form.openTime,
    closeTime: form.closeTime === '' ? null : form.closeTime,
    setting: form.setting === '' ? null : form.setting,
    categoryId: form.categoryId,
    venue: {
      name: form.venueName,
      address: form.address,
      city: form.city,
      postalCode: form.postalCode,
      lat: form.lat,
      lng: form.lng,
    },
  };

  loading.value = true;
  try {
    const { event } = editId.value
      ? await api.sendForm<{ event: EventItem }>(`/api/events/${editId.value}`, 'PUT', payload, photo.value)
      : await api.sendForm<{ event: EventItem }>('/api/events', 'POST', payload, photo.value);
    router.push(`/sorties/${event.id}`);
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Erreur lors de l’envoi';
  } finally {
    loading.value = false;
  }
}

onMounted(async () => {
  const { categories: cats } = await api.get<{ categories: Category[] }>('/api/categories');
  categories.value = cats;

  if (!editId.value) return;
  const { event } = await api.get<{ event: EventItem }>(`/api/events/${editId.value}`);
  form.title = event.title;
  form.description = event.description;
  form.sourceUrl = event.sourceUrl ?? '';
  foundOn.value = event.foundOnUrl ?? '';
  form.isFree = event.isFree;
  // Tarif indéterminé (import) : on repart vide pour forcer la saisie.
  form.price = hasPrice(event) ? event.price ?? '' : '';
  form.ageMin = event.ageMin ?? '';
  form.ageMax = event.ageMax ?? '';
  form.isPermanent = event.isPermanent;
  form.dateStart = event.dateStart ?? '';
  form.dateEnd = event.dateEnd ?? '';
  form.dates = [...event.dates];
  form.openTime = event.openTime ?? '';
  form.closeTime = event.closeTime ?? '';
  form.setting = event.setting ?? '';
  form.categoryId = event.category.id;
  form.venueName = event.venue.name;
  form.address = event.venue.address;
  form.city = event.venue.city;
  form.postalCode = event.venue.postalCode;
  // Sortie importée sans géocodage : on repart de zéro sur la position pour
  // forcer la sélection d'une vraie adresse dans les suggestions.
  const located = hasCoordinates(event.venue);
  form.lat = located ? event.venue.lat : null;
  form.lng = located ? event.venue.lng : null;
  existingPhotoUrl.value = event.photoUrl;
});
</script>

<template>
  <div class="container page">
    <h1>{{ editId ? 'Modifier la sortie' : 'Proposer une sortie' }}</h1>
    <p class="muted">
      Votre proposition sera vérifiée par un modérateur avant d'être publiée.
    </p>

    <form class="form" @submit.prevent="submit">
      <p v-if="error" class="error">{{ error }}</p>

      <div class="field">
        <label for="title">Titre *</label>
        <input id="title" v-model="form.title" type="text" required minlength="3" maxlength="150" />
      </div>

      <div class="field">
        <label for="desc">Description *</label>
        <textarea id="desc" v-model="form.description" rows="6" required minlength="10" />
      </div>

      <div class="row">
        <div class="field">
          <label>&nbsp;</label>
          <label class="checkbox">
            <input v-model="form.isFree" type="checkbox" />
            Sortie gratuite
          </label>
        </div>
        <div class="field">
          <label for="price">Prix par enfant (€) {{ form.isFree ? '' : '*' }}</label>
          <input
            id="price"
            v-model="form.price"
            type="number"
            min="0"
            step="0.5"
            :disabled="form.isFree"
            :required="!form.isFree"
          />
        </div>
      </div>

      <div class="row">
        <div class="field">
          <label for="age-min">Âge minimum</label>
          <input id="age-min" v-model="form.ageMin" type="number" min="0" max="17" />
        </div>
        <div class="field">
          <label for="age-max">Âge maximum</label>
          <input id="age-max" v-model="form.ageMax" type="number" min="0" max="18" />
        </div>
        <div class="field">
          <label for="setting">Cadre</label>
          <select id="setting" v-model="form.setting">
            <option value="">Non précisé</option>
            <option value="INDOOR">Intérieur</option>
            <option value="OUTDOOR">Extérieur</option>
            <option value="BOTH">Les deux</option>
          </select>
        </div>
        <div class="field">
          <label for="category">Catégorie *</label>
          <select id="category" v-model.number="form.categoryId" required>
            <option :value="null" disabled>Choisissez…</option>
            <option v-for="c in categories" :key="c.id" :value="c.id">{{ c.name }}</option>
          </select>
        </div>
      </div>

      <div class="field">
        <label class="checkbox">
          <input v-model="form.isPermanent" type="checkbox" />
          Événement permanent (pas de date de fin)
        </label>
      </div>

      <div class="row">
        <div class="field">
          <label for="date-start">Date de début {{ form.isPermanent ? '' : '*' }}</label>
          <input
            id="date-start"
            v-model="form.dateStart"
            type="date"
            :disabled="form.isPermanent"
            :required="!form.isPermanent"
          />
        </div>
        <div class="field">
          <label for="date-end">Date de fin {{ form.isPermanent ? '' : '*' }}</label>
          <input
            id="date-end"
            v-model="form.dateEnd"
            type="date"
            :disabled="form.isPermanent"
            :required="!form.isPermanent"
          />
        </div>
        <div class="field">
          <label for="open-time">Heure d'ouverture</label>
          <input id="open-time" v-model="form.openTime" type="time" />
        </div>
        <div class="field">
          <label for="close-time">Heure de fermeture</label>
          <input id="close-time" v-model="form.closeTime" type="time" />
        </div>
      </div>
      <span class="hint">Cette plage horaire s'applique tous les jours de l'évènement.</span>

      <div v-if="!form.isPermanent" class="field">
        <label>Jours de représentation</label>
        <span class="hint">
          Laissez vide si la sortie a lieu tous les jours de la période — c'est le cas d'une
          exposition ou d'une fête foraine. Pour un spectacle qui ne se joue que certains jours,
          énumérez-les : sans ça il ressortira dans les recherches un jour où il ne se joue pas.
        </span>

        <div class="dates-picker">
          <!-- Un clic ajoute le jour, un second le retire : quinze
               représentations se pointent d'affilée, sans validation à chaque
               date. Le calendrier est borné par la période de la sortie, que
               le serveur fait respecter de toute façon. -->
          <v-date-picker
            v-model="selectedDates"
            multiple
            hide-header
            show-adjacent-months
            color="primary"
            :min="periodStart"
            :max="periodEnd"
          />

          <div class="dates-side">
            <p v-if="!form.dates.length" class="muted">
              Aucune date sélectionnée : la sortie a lieu <strong>tous les jours</strong> de sa
              période.
            </p>
            <template v-else>
              <p class="muted">
                {{ form.dates.length }} date(s) — recliquez un jour pour le retirer.
                <button class="linklike" type="button" @click="form.dates = []">
                  Tout effacer
                </button>
              </p>
              <ul class="dates">
                <li v-for="day in form.dates" :key="day">
                  {{ dayLabel(day) }}
                  <button type="button" title="Retirer cette date" @click="removeDate(day)">
                    ×
                  </button>
                </li>
              </ul>
            </template>
          </div>
        </div>

        <!-- La période a été resserrée après coup : ces dates ne sont plus
             atteignables au calendrier, et le serveur refuserait la sortie. -->
        <p v-if="outOfPeriod.length" class="out-of-period">
          {{ outOfPeriod.length }} date(s) sortent de la période
          ({{ outOfPeriod.map(dayLabel).join(', ') }}) : l'enregistrement sera refusé.
          <button class="linklike" type="button" @click="dropOutOfPeriod">Les retirer</button>
        </p>
      </div>

      <div class="field">
        <label for="source-url">Lien vers l'événement (source)</label>
        <input
          id="source-url"
          v-model="form.sourceUrl"
          type="url"
          placeholder="https://…"
        />
        <p class="hint">
          De préférence la page de l'organisateur — le musée, le théâtre, la
          mairie — plutôt qu'un agenda qui la republie : c'est là que les
          horaires et les annulations sont à jour.
        </p>
        <!-- Provenance d'une proposition automatique. Elle explique au
             modérateur pourquoi le lien ci-dessus n'est pas celui de la page
             lue, et lui donne de quoi vérifier en un clic. -->
        <p v-if="foundOn && foundOn !== form.sourceUrl" class="hint">
          Repérée sur
          <a :href="foundOn" target="_blank" rel="noopener">{{ foundOn }}</a> par la
          recherche automatique.
        </p>
      </div>

      <h2>Le lieu</h2>

      <div class="field">
        <label for="venue-name">Nom du lieu *</label>
        <input
          id="venue-name"
          v-model="form.venueName"
          type="text"
          required
          placeholder="ex. Parc de Sceaux"
        />
      </div>

      <div class="field">
        <label>Adresse *</label>
        <AddressPicker v-model="form.address" placeholder="Cherchez l'adresse…" @select="onAddressSelect" />
        <span class="hint">
          Choisissez une suggestion pour géolocaliser le lieu (recherche par distance).
        </span>
      </div>

      <div class="row">
        <div class="field">
          <label for="postal">Code postal *</label>
          <input id="postal" v-model="form.postalCode" type="text" required />
        </div>
        <div class="field">
          <label for="city">Ville *</label>
          <input id="city" v-model="form.city" type="text" required />
        </div>
      </div>

      <div class="field">
        <label for="photo">Photo</label>
        <input id="photo" type="file" accept="image/*" @change="onPhotoChange" />
        <img
          v-if="photoPreview || existingPhotoUrl"
          :src="photoPreview || existingPhotoUrl!"
          alt="Aperçu"
          style="max-width: 320px; border-radius: 10px; margin-top: 0.5rem"
        />
      </div>

      <div>
        <button class="btn" type="submit" :disabled="loading">
          {{ loading ? 'Envoi…' : editId ? 'Enregistrer' : 'Proposer la sortie' }}
        </button>
      </div>
    </form>
  </div>
</template>

<style scoped>
.dates-picker {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  gap: 1.2rem;
  margin-top: 0.4rem;
}

.dates-side {
  flex: 1 1 260px;
  min-width: 240px;
}

.dates-side p {
  margin: 0 0 0.5rem;
}

.out-of-period {
  margin: 0.6rem 0 0;
  padding: 0.6rem 0.8rem;
  border-radius: 12px;
  background: var(--warn-soft);
  color: var(--warn);
  font-size: 0.9rem;
}

.linklike {
  background: none;
  border: none;
  padding: 0;
  font: inherit;
  color: var(--accent-dark);
  cursor: pointer;
  text-decoration: underline;
}

.dates {
  list-style: none;
  padding: 0;
  margin: 0.5rem 0;
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
}

.dates li {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  background: var(--accent-soft);
  border-radius: 999px;
  padding: 0.2rem 0.5rem 0.2rem 0.7rem;
  font-size: 0.85rem;
}

.dates button {
  background: none;
  border: none;
  cursor: pointer;
  font-size: 1rem;
  line-height: 1;
  padding: 0 0.15rem;
  color: var(--ink-soft);
}

</style>
