import 'vuetify/styles';
import '@mdi/font/css/materialdesignicons.css';
import { createVuetify } from 'vuetify';

export default createVuetify({
  theme: {
    defaultTheme: 'sortiesPourPetits',
    themes: {
      sortiesPourPetits: {
        dark: false,
        colors: {
          primary: '#ff5ca8',
          secondary: '#33c1ff',
          background: '#f5faff',
          surface: '#ffffff',
          error: '#d63447',
          success: '#1fae7a',
          warning: '#dd8f1e',
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
