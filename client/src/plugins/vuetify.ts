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
