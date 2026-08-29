import 'vuetify/styles';
import '@mdi/font/css/materialdesignicons.css';
import { createVuetify } from 'vuetify';
import { fr } from 'vuetify/locale';

export default createVuetify({
  // Sans ça, le calendrier de sélection des dates s'affiche en anglais et
  // démarre ses semaines le dimanche. `messages` porte les libellés de
  // l'interface, `date` les noms de mois et de jours — et c'est la locale
  // `fr-FR` qui met le lundi en tête, rien d'autre à régler.
  locale: { locale: 'fr', messages: { fr } },
  date: { locale: { fr: 'fr-FR' } },
  theme: {
    defaultTheme: 'sortiesPourPetits',
    themes: {
      sortiesPourPetits: {
        dark: false,
        colors: {
          primary: '#e8779a',
          secondary: '#5aa9e6',
          background: '#f7f6f9',
          surface: '#ffffff',
          error: '#d64550',
          success: '#2f8f63',
          warning: '#b9791f',
        },
      },
    },
  },
  defaults: {
    VBtn: { rounded: 'lg' },
    VCard: { rounded: 'lg' },
    VTextField: { variant: 'outlined', density: 'comfortable' },
    VSelect: { variant: 'outlined', density: 'comfortable' },
  },
});
