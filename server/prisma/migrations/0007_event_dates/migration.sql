-- CreateTable
CREATE TABLE `EventDate` (
    `id` INTEGER NOT NULL AUTO_INCREMENT,
    `day` DATE NOT NULL,
    `eventId` INTEGER NOT NULL,

    INDEX `EventDate_day_idx`(`day`),
    UNIQUE INDEX `EventDate_eventId_day_key`(`eventId`, `day`),
    PRIMARY KEY (`id`)
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- AddForeignKey
ALTER TABLE `EventDate` ADD CONSTRAINT `EventDate_eventId_fkey` FOREIGN KEY (`eventId`) REFERENCES `Event`(`id`) ON DELETE CASCADE ON UPDATE CASCADE;
