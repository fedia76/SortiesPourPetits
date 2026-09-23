<script setup lang="ts">
import { ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { api } from '../lib/api';
import { messageDe } from '../lib/erreurs';

/**
 * Les deux pages légales, avec une seule vue.
 *
 * Le texte ne vit pas ici : il est écrit une fois côté serveur
 * (`server/src/lib/legal.ts`), qui le rend dans le document **et** le sert par
 * l'API. Au premier affichage, `api.get` le relit dans le document plutôt que
 * de le redemander — l'appel ci-dessous ne touche donc pas le réseau. Deux
 * copies d'un texte juridique finiraient par diverger, et la page mentirait à
 * la moitié de ses lecteurs.
 */
interface SectionLegale {
  titre: string;
  paragraphes: string[];
  action?: 'opposition-audience';
}

interface PageLegale {
  slug: string;
  titre: string;
  description: string;
  sections: SectionLegale[];
}

const route = useRoute();
const page = ref<PageLegale | null>(null);
const erreur = ref('');

async function charger(slug: string) {
  erreur.value = '';
  page.value = null;
  try {
    const { page: recu } = await api.get<{ page: PageLegale }>(`/api/legal/${slug}`);
    page.value = recu;
  } catch (e) {
    erreur.value = messageDe(e);
  }
}

watch(
  () => route.meta.legalSlug as string | undefined,
  (slug) => {
    if (slug) void charger(slug);
  },
  { immediate: true },
);

// ------------------------------------- l'opposition à la mesure d'audience

/**
 * Le drapeau que le script de mesure relit avant de compter quoi que ce soit.
 *
 * Il vit dans le stockage local du navigateur, donc il ne vaut que pour ce
 * navigateur et cet appareil — le texte de la page le dit, et c'est la limite
 * honnête du procédé. Le stockage peut être refusé (navigation privée stricte,
 * cookies bloqués) : on ne prétend alors pas avoir enregistré un refus qui
 * n'existe pas.
 */
const CLE_REFUS = 'umami.disabled';

function lireRefus(): boolean {
  try {
    return localStorage.getItem(CLE_REFUS) === '1';
  } catch {
    return false;
  }
}

const refuse = ref(lireRefus());
const refusImpossible = ref(false);

function basculerRefus() {
  refusImpossible.value = false;
  try {
    if (refuse.value) localStorage.removeItem(CLE_REFUS);
    else localStorage.setItem(CLE_REFUS, '1');
    refuse.value = lireRefus();
  } catch {
    refusImpossible.value = true;
  }
}
</script>

<template>
  <div class="container page legal">
    <p v-if="erreur" class="error">{{ erreur }}</p>

    <template v-if="page">
      <h1>{{ page.titre }}</h1>

      <section v-for="section in page.sections" :key="section.titre">
        <h2>{{ section.titre }}</h2>
        <p v-for="(texte, i) in section.paragraphes" :key="i">{{ texte }}</p>

        <div v-if="section.action === 'opposition-audience'" class="opposition">
          <button class="btn" :class="{ ghost: refuse }" @click="basculerRefus">
            {{ refuse ? 'Autoriser à nouveau la mesure' : 'Refuser la mesure d’audience' }}
          </button>
          <p v-if="refusImpossible" class="note error">
            Votre navigateur refuse d’enregistrer ce choix. Utilisez l’option
            « Do Not Track » de ses réglages : elle est respectée ici.
          </p>
          <p v-else-if="refuse" class="note">
            Vos visites ne sont plus comptées depuis ce navigateur.
          </p>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.legal section {
  margin-bottom: 1.75rem;
}

.legal h2 {
  font-size: 1.15rem;
  margin-bottom: 0.5rem;
}

/* Un texte de loi se lit en lignes courtes ; pleine largeur, il se survole et
   ne se lit pas — ce qui est exactement ce qu'on ne veut pas d'une page dont
   l'objet est d'informer. */
.legal p {
  max-width: 68ch;
  line-height: 1.6;
  margin-bottom: 0.6rem;
}

.opposition {
  margin-top: 0.9rem;
}

.note {
  margin-top: 0.5rem;
  font-size: 0.9rem;
  opacity: 0.85;
}
</style>
