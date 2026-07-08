-- AlterTable
ALTER TABLE `Event` ADD COLUMN `openTime` VARCHAR(191) NULL;
ALTER TABLE `Event` ADD COLUMN `closeTime` VARCHAR(191) NULL;

-- Backfill : une seule plage horaire par évènement (bornes des anciens créneaux).
UPDATE `Event` e
SET
  `openTime` = COALESCE((SELECT MIN(`openTime`) FROM `OpeningHour` WHERE `eventId` = e.`id`), '09:00'),
  `closeTime` = COALESCE((SELECT MAX(`closeTime`) FROM `OpeningHour` WHERE `eventId` = e.`id`), '18:00');

ALTER TABLE `Event` MODIFY COLUMN `openTime` VARCHAR(191) NOT NULL;
ALTER TABLE `Event` MODIFY COLUMN `closeTime` VARCHAR(191) NOT NULL;

-- DropTable
DROP TABLE `OpeningHour`;
