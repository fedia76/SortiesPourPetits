/**
 * Données de démonstration : un compte de chaque rôle et quelques sorties
 * en Île-de-France. Lancez avec : npm run db:seed
 *
 * Comptes créés (mot de passe : "motdepasse") :
 *   admin@example.com / modo@example.com / parent@example.com
 */
import 'dotenv/config';
import { PrismaClient, Setting } from '@prisma/client';
import bcrypt from 'bcryptjs';

const prisma = new PrismaClient();

async function main() {
  const passwordHash = await bcrypt.hash('motdepasse', 12);

  const [admin, modo, parent] = await Promise.all([
    prisma.user.upsert({
      where: { email: 'admin@example.com' },
      update: {},
      create: { email: 'admin@example.com', displayName: 'Admin', role: 'ADMIN', passwordHash },
    }),
    prisma.user.upsert({
      where: { email: 'modo@example.com' },
      update: {},
      create: { email: 'modo@example.com', displayName: 'Modérateur', role: 'MODERATOR', passwordHash },
    }),
    prisma.user.upsert({
      where: { email: 'parent@example.com' },
      update: {},
      create: { email: 'parent@example.com', displayName: 'Parent Curieux', passwordHash },
    }),
  ]);

  const categoryNames = ['Parc', 'Musée', 'Spectacle', 'Sport', 'Atelier'];
  const categories = Object.fromEntries(
    await Promise.all(
      categoryNames.map(async (name) => {
        const category = await prisma.category.upsert({
          where: { name },
          update: {},
          create: { name },
        });
        return [name, category] as const;
      }),
    ),
  );

  const year = new Date().getFullYear();
  const demoEvents: Array<{
    title: string;
    description: string;
    isFree: boolean;
    price: number | null;
    ageMin: number;
    ageMax: number;
    dateStart: string;
    dateEnd: string;
    setting: Setting;
    category: string;
    venue: { name: string; address: string; city: string; postalCode: string; lat: number; lng: number };
  }> = [
    {
      title: 'Jardin d’Acclimatation',
      description:
        'Parc d’attractions et jardin au cœur du bois de Boulogne : manèges, animaux de la ferme, aires de jeux et grande volière. Idéal pour une journée complète en famille.',
      isFree: false,
      price: 7,
      ageMin: 2,
      ageMax: 12,
      dateStart: `${year}-01-01`,
      dateEnd: `${year}-12-31`,
      setting: 'BOTH',
      category: 'Parc',
      venue: {
        name: 'Jardin d’Acclimatation',
        address: 'Bois de Boulogne, Route de la Porte Dauphine',
        city: 'Paris',
        postalCode: '75116',
        lat: 48.877778,
        lng: 2.263056,
      },
    },
    {
      title: 'Cité des enfants (2-7 ans)',
      description:
        'Espace de découverte scientifique conçu pour les tout-petits à la Cité des sciences : jeux d’eau, chantier de construction, parcours de motricité. Réservation d’un créneau de 1h30 conseillée.',
      isFree: false,
      price: 15,
      ageMin: 2,
      ageMax: 7,
      dateStart: `${year}-01-01`,
      dateEnd: `${year}-12-31`,
      setting: 'INDOOR',
      category: 'Musée',
      venue: {
        name: 'Cité des sciences et de l’industrie',
        address: '30 Avenue Corentin Cariou',
        city: 'Paris',
        postalCode: '75019',
        lat: 48.895651,
        lng: 2.38795,
      },
    },
    {
      title: 'Parc de Sceaux — chasse au trésor nature',
      description:
        'Grande balade libre dans le domaine de Sceaux avec parcours d’énigmes à imprimer : cascades, grand canal, perspectives de Le Nôtre. Aires de pique-nique et location de barques en été.',
      isFree: true,
      price: null,
      ageMin: 3,
      ageMax: 14,
      dateStart: `${year}-04-01`,
      dateEnd: `${year}-10-31`,
      setting: 'OUTDOOR',
      category: 'Parc',
      venue: {
        name: 'Parc de Sceaux',
        address: '8 Avenue Claude Perrault',
        city: 'Sceaux',
        postalCode: '92330',
        lat: 48.771389,
        lng: 2.297222,
      },
    },
    {
      title: 'France Miniature',
      description:
        'Tour de France en une journée : 117 monuments reproduits en miniature dans un parc paysager, avec espaces de jeux entre les zones. Compter 3 à 4 heures de visite.',
      isFree: false,
      price: 22,
      ageMin: 4,
      ageMax: 15,
      dateStart: `${year}-04-05`,
      dateEnd: `${year}-11-02`,
      setting: 'OUTDOOR',
      category: 'Sport',
      venue: {
        name: 'France Miniature',
        address: 'Boulevard André Malraux',
        city: 'Élancourt',
        postalCode: '78990',
        lat: 48.774722,
        lng: 1.949444,
      },
    },
  ];

  for (const e of demoEvents) {
    const existing = await prisma.event.findFirst({ where: { title: e.title } });
    if (existing) continue;

    const venue =
      (await prisma.venue.findFirst({ where: { name: e.venue.name, city: e.venue.city } })) ??
      (await prisma.venue.create({ data: e.venue }));

    await prisma.event.create({
      data: {
        title: e.title,
        description: e.description,
        isFree: e.isFree,
        price: e.price,
        ageMin: e.ageMin,
        ageMax: e.ageMax,
        dateStart: new Date(e.dateStart),
        dateEnd: new Date(e.dateEnd),
        openTime: '10:00',
        closeTime: '18:00',
        setting: e.setting,
        status: 'APPROVED',
        venueId: venue.id,
        categoryId: categories[e.category].id,
        createdById: parent.id,
        moderatedById: modo.id,
      },
    });
  }

  console.log(`Seed terminé. Comptes : ${admin.email}, ${modo.email}, ${parent.email} (mdp : motdepasse)`);
}

main()
  .catch((e) => {
    console.error(e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
