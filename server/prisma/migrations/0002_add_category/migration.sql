-- CreateTable
CREATE TABLE `Category` (
    `id` INTEGER NOT NULL AUTO_INCREMENT,
    `name` VARCHAR(191) NOT NULL,
    `createdAt` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),

    UNIQUE INDEX `Category_name_key`(`name`),
    PRIMARY KEY (`id`)
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- Backfill : catégorie par défaut pour les événements existants.
INSERT INTO `Category` (`name`) VALUES ('Non classé');

-- AlterTable
ALTER TABLE `Event` ADD COLUMN `categoryId` INTEGER NULL;

UPDATE `Event` SET `categoryId` = (SELECT `id` FROM `Category` WHERE `name` = 'Non classé');

ALTER TABLE `Event` MODIFY COLUMN `categoryId` INTEGER NOT NULL;

-- CreateIndex
CREATE INDEX `Event_categoryId_idx` ON `Event`(`categoryId`);

-- AddForeignKey
ALTER TABLE `Event` ADD CONSTRAINT `Event_categoryId_fkey` FOREIGN KEY (`categoryId`) REFERENCES `Category`(`id`) ON DELETE RESTRICT ON UPDATE CASCADE;
