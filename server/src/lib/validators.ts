import { z } from 'zod';

export const registerSchema = z.object({
  email: z.string().email('Email invalide'),
  password: z.string().min(8, 'Le mot de passe doit faire au moins 8 caractères'),
  displayName: z.string().trim().min(2, 'Le nom doit faire au moins 2 caractères').max(50),
});

export const loginSchema = z.object({
  email: z.string().email(),
  password: z.string().min(1),
});

const timeRegex = /^([01]\d|2[0-3]):[0-5]\d$/;

export const openingHourSchema = z
  .object({
    dayOfWeek: z.number().int().min(0).max(6),
    openTime: z.string().regex(timeRegex, 'Heure invalide (HH:MM)'),
    closeTime: z.string().regex(timeRegex, 'Heure invalide (HH:MM)'),
  })
  .refine((h) => h.openTime < h.closeTime, {
    message: "L'heure d'ouverture doit précéder l'heure de fermeture",
  });

export const venueSchema = z.object({
  name: z.string().trim().min(1, 'Nom du lieu requis').max(120),
  address: z.string().trim().min(1, 'Adresse requise').max(255),
  city: z.string().trim().min(1, 'Ville requise').max(120),
  postalCode: z.string().trim().min(4).max(10),
  lat: z.number().min(-90).max(90),
  lng: z.number().min(-180).max(180),
});

export const categorySchema = z.object({
  name: z.string().trim().min(2, 'Nom trop court').max(50, 'Nom trop long'),
});

export const eventInputSchema = z
  .object({
    title: z.string().trim().min(3, 'Titre trop court').max(150),
    description: z.string().trim().min(10, 'Description trop courte').max(10_000),
    isFree: z.boolean(),
    price: z.number().min(0).max(100_000).nullable().optional(),
    ageMin: z.number().int().min(0).max(17),
    ageMax: z.number().int().min(0).max(18),
    dateStart: z.string().regex(/^\d{4}-\d{2}-\d{2}$/, 'Date invalide (AAAA-MM-JJ)'),
    dateEnd: z.string().regex(/^\d{4}-\d{2}-\d{2}$/, 'Date invalide (AAAA-MM-JJ)'),
    setting: z.enum(['INDOOR', 'OUTDOOR', 'BOTH']),
    categoryId: z.number().int().positive('Catégorie requise'),
    venue: venueSchema,
    openingHours: z.array(openingHourSchema).max(21),
  })
  .refine((e) => e.ageMin <= e.ageMax, {
    message: "La tranche d'âge est inversée",
  })
  .refine((e) => e.dateStart <= e.dateEnd, {
    message: 'La date de fin précède la date de début',
  })
  .refine((e) => e.isFree || (e.price !== null && e.price !== undefined), {
    message: 'Indiquez un prix ou cochez « gratuit »',
  });

export const searchSchema = z.object({
  q: z.string().trim().max(200).optional(),
  free: z.enum(['true', 'false']).optional(),
  priceMax: z.coerce.number().min(0).optional(),
  age: z.coerce.number().int().min(0).max(18).optional(),
  from: z.string().regex(/^\d{4}-\d{2}-\d{2}$/).optional(),
  to: z.string().regex(/^\d{4}-\d{2}-\d{2}$/).optional(),
  setting: z.enum(['INDOOR', 'OUTDOOR', 'BOTH']).optional(),
  categoryId: z.coerce.number().int().positive().optional(),
  lat: z.coerce.number().min(-90).max(90).optional(),
  lng: z.coerce.number().min(-180).max(180).optional(),
  radiusKm: z.coerce.number().min(0.1).max(300).optional(),
  page: z.coerce.number().int().min(1).default(1),
  pageSize: z.coerce.number().int().min(1).max(50).default(12),
});

export const moderateSchema = z.object({
  action: z.enum(['approve', 'reject']),
  reason: z.string().trim().max(1000).optional(),
});

export const updateRoleSchema = z.object({
  role: z.enum(['USER', 'MODERATOR', 'ADMIN']),
});
