import { Area, Category, Prisma } from '@prisma/client';
import { prisma } from '../db';
import { areaFilter } from './areas';
import { dateFilter, today } from './dateWindow';

/**
 * Les deux listes que toute page publique finit par demander : les zones et
 * les catégories.
 *
 * Elles vivaient dans leurs routes. Le pré-rendu les écrit maintenant aussi
 * dans l'état initial du document, pour que l'application n'ait pas à les
 * redemander avant d'afficher quoi que ce soit — et il faut alors que les deux
 * répondent exactement la même chose, `eventCount` compris : une zone dont le
 * compte disparaîtrait au montage de Vue serait un clignotement de plus.
 */

export type AreaWithCount = Area & { eventCount: number };

/**
 * Les zones, avec le nombre de sorties visibles dans chacune.
 *
 * Ce compte n'est pas décoratif : il sert à ne pas mettre en avant une zone
 * vide. Une page qui annonce des sorties et n'en montre aucune déçoit le
 * visiteur et, répétée, apprend à Google que le site promet plus qu'il ne tient.
 */
export async function areasWithCounts(): Promise<AreaWithCount[]> {
  const areas = await prisma.area.findMany({ orderBy: [{ position: 'asc' }, { name: 'asc' }] });
  const upcoming: Prisma.EventWhereInput = { status: 'APPROVED', AND: [dateFilter(today())] };
  const counts = await Promise.all(
    areas.map((area) =>
      prisma.event.count({ where: { AND: [upcoming, areaFilter(area.postalPrefixes)] } }),
    ),
  );
  return areas.map((area, i) => ({ ...area, eventCount: counts[i] }));
}

/** Les catégories, dans l'ordre où les listes déroulantes les montrent. */
export function allCategories(): Promise<Category[]> {
  return prisma.category.findMany({ orderBy: { name: 'asc' } });
}
