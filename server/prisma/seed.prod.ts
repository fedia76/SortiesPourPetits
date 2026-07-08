/**
 * Seed de production : catégories de base + compte ADMIN initial.
 * Ne crée aucune donnée de démonstration (voir seed.ts pour ça).
 *
 * Le mot de passe admin n'est jamais fourni en clair : ADMIN_PASSWORD_HASH
 * doit déjà être un hash bcrypt, généré localement avec :
 *   npm run hash-password -- 'mon-mot-de-passe'
 *
 * Lancez avec : npm run db:seed:prod
 */
import 'dotenv/config';
import { PrismaClient } from '@prisma/client';

const prisma = new PrismaClient();

async function main() {
  const email = process.env.ADMIN_EMAIL;
  const passwordHash = process.env.ADMIN_PASSWORD_HASH;
  const displayName = process.env.ADMIN_DISPLAY_NAME ?? 'Admin';

  if (!email || !passwordHash) {
    throw new Error(
      'ADMIN_EMAIL et ADMIN_PASSWORD_HASH doivent être définis dans le .env ' +
        "(générez le hash avec : npm run hash-password -- 'mon-mot-de-passe')",
    );
  }

  const categoryNames = ['Parc', 'Musée', 'Spectacle', 'Sport', 'Atelier'];
  await Promise.all(
    categoryNames.map((name) =>
      prisma.category.upsert({ where: { name }, update: {}, create: { name } }),
    ),
  );

  const admin = await prisma.user.upsert({
    where: { email },
    update: {},
    create: { email, displayName, role: 'ADMIN', passwordHash },
  });

  console.log(`Seed de production terminé. Compte admin : ${admin.email}`);
}

main()
  .catch((e) => {
    console.error(e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
