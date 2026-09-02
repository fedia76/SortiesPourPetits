<script setup lang="ts">
import { onMounted } from 'vue';
import { setPageSeo } from '../lib/seo';

onMounted(() => {
  setPageSeo({
    title: 'Page introuvable',
    description: "Cette page n'existe pas ou n'est plus disponible.",
    noindex: true,
  });
});
</script>

<template>
  <!--
    Une adresse inconnue affichait l'accueil, par redirection. C'était mentir
    deux fois : au visiteur, qui ne comprenait pas où était passée sa page, et
    au serveur, qui répond 404 sur cette même adresse — les deux doivent dire
    la même chose.
  -->
  <div class="container page">
    <h1>Page introuvable</h1>
    <p>Cette page n'existe pas, ou elle n'est plus publiée.</p>
    <p><RouterLink to="/">Retour aux sorties</RouterLink></p>
  </div>
</template>
