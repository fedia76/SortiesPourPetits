-- CreateTable
CREATE TABLE `ScraperConfig` (
    `id` INTEGER NOT NULL AUTO_INCREMENT,
    `name` VARCHAR(191) NOT NULL,
    `enabled` BOOLEAN NOT NULL DEFAULT true,
    `theme` TEXT NOT NULL,
    `area` VARCHAR(191) NOT NULL DEFAULT 'Île-de-France',
    `period` VARCHAR(191) NOT NULL DEFAULT 'les prochaines semaines',
    `horizonDays` INTEGER NOT NULL DEFAULT 30,
    `maxEvents` INTEGER NOT NULL DEFAULT 20,
    `maxSearches` INTEGER NOT NULL DEFAULT 6,
    `maxAgendas` INTEGER NOT NULL DEFAULT 6,
    `maxLinksPerAgenda` INTEGER NOT NULL DEFAULT 8,
    `maxPageChars` INTEGER NOT NULL DEFAULT 8000,
    `maxCostUsd` DECIMAL(6, 2) NOT NULL DEFAULT 1.00,
    `keepOutOfScope` BOOLEAN NOT NULL DEFAULT true,
    `defaultCategory` VARCHAR(191) NOT NULL DEFAULT 'Non classé',
    `postalPrefixes` VARCHAR(191) NOT NULL DEFAULT '75,77,78,91,92,93,94,95',
    `blockedDomains` TEXT NOT NULL,
    `searchModel` VARCHAR(191) NOT NULL DEFAULT 'claude-haiku-4-5',
    `selectModel` VARCHAR(191) NOT NULL DEFAULT 'claude-haiku-4-5',
    `extractionModel` VARCHAR(191) NOT NULL DEFAULT 'claude-haiku-4-5',
    `searchPrompt` TEXT NULL,
    `selectPrompt` TEXT NULL,
    `extractionPrompt` TEXT NULL,
    `createdAt` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    `updatedAt` DATETIME(3) NOT NULL,

    UNIQUE INDEX `ScraperConfig_name_key`(`name`),
    PRIMARY KEY (`id`)
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- CreateTable
CREATE TABLE `ScraperRun` (
    `id` INTEGER NOT NULL AUTO_INCREMENT,
    `status` ENUM('QUEUED', 'RUNNING', 'DONE', 'FAILED') NOT NULL DEFAULT 'QUEUED',
    `submit` BOOLEAN NOT NULL DEFAULT false,
    `queuedAt` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    `startedAt` DATETIME(3) NULL,
    `finishedAt` DATETIME(3) NULL,
    `error` TEXT NULL,
    `candidates` INTEGER NOT NULL DEFAULT 0,
    `pages` INTEGER NOT NULL DEFAULT 0,
    `retained` INTEGER NOT NULL DEFAULT 0,
    `submitted` INTEGER NOT NULL DEFAULT 0,
    `duplicates` INTEGER NOT NULL DEFAULT 0,
    `skipped` INTEGER NOT NULL DEFAULT 0,
    `errors` INTEGER NOT NULL DEFAULT 0,
    `inputTokens` INTEGER NOT NULL DEFAULT 0,
    `outputTokens` INTEGER NOT NULL DEFAULT 0,
    `webSearches` INTEGER NOT NULL DEFAULT 0,
    `costUsd` DECIMAL(8, 4) NOT NULL DEFAULT 0,
    `configId` INTEGER NOT NULL,
    `requestedById` INTEGER NULL,

    INDEX `ScraperRun_status_queuedAt_idx`(`status`, `queuedAt`),
    INDEX `ScraperRun_configId_idx`(`configId`),
    PRIMARY KEY (`id`)
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- CreateTable
CREATE TABLE `ScraperRunItem` (
    `id` INTEGER NOT NULL AUTO_INCREMENT,
    `url` VARCHAR(500) NOT NULL,
    `title` VARCHAR(191) NULL,
    `decision` VARCHAR(191) NOT NULL,
    `reason` TEXT NULL,
    `at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    `runId` INTEGER NOT NULL,
    `eventId` INTEGER NULL,

    INDEX `ScraperRunItem_runId_idx`(`runId`),
    PRIMARY KEY (`id`)
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- CreateTable
CREATE TABLE `ScrapedUrl` (
    `id` INTEGER NOT NULL AUTO_INCREMENT,
    `url` VARCHAR(500) NOT NULL,
    `title` VARCHAR(191) NULL,
    `decision` VARCHAR(191) NOT NULL,
    `firstSeen` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    `lastSeen` DATETIME(3) NOT NULL,
    `eventId` INTEGER NULL,

    UNIQUE INDEX `ScrapedUrl_url_key`(`url`),
    INDEX `ScrapedUrl_decision_idx`(`decision`),
    PRIMARY KEY (`id`)
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- AddForeignKey
ALTER TABLE `ScraperRun` ADD CONSTRAINT `ScraperRun_configId_fkey` FOREIGN KEY (`configId`) REFERENCES `ScraperConfig`(`id`) ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE `ScraperRun` ADD CONSTRAINT `ScraperRun_requestedById_fkey` FOREIGN KEY (`requestedById`) REFERENCES `User`(`id`) ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE `ScraperRunItem` ADD CONSTRAINT `ScraperRunItem_runId_fkey` FOREIGN KEY (`runId`) REFERENCES `ScraperRun`(`id`) ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE `ScraperRunItem` ADD CONSTRAINT `ScraperRunItem_eventId_fkey` FOREIGN KEY (`eventId`) REFERENCES `Event`(`id`) ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE `ScrapedUrl` ADD CONSTRAINT `ScrapedUrl_eventId_fkey` FOREIGN KEY (`eventId`) REFERENCES `Event`(`id`) ON DELETE SET NULL ON UPDATE CASCADE;
