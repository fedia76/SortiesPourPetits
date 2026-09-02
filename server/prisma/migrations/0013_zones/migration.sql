-- CreateTable
CREATE TABLE `Area` (
    `id` INTEGER NOT NULL AUTO_INCREMENT,
    `slug` VARCHAR(191) NOT NULL,
    `name` VARCHAR(191) NOT NULL,
    `postalPrefixes` VARCHAR(191) NOT NULL,
    `intro` TEXT NOT NULL,
    `position` INTEGER NOT NULL DEFAULT 0,
    `createdAt` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),

    UNIQUE INDEX `Area_slug_key`(`slug`),
    UNIQUE INDEX `Area_name_key`(`name`),
    PRIMARY KEY (`id`)
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- Les quatre zones ouvertes à ce jour. Le contenu se modifie ensuite depuis
-- la console d'administration : c'est une amorce, pas une définition figée.
INSERT INTO `Area` (`slug`, `name`, `postalPrefixes`, `intro`, `position`) VALUES
  ('ile-de-france', 'Île-de-France', '75,77,78,91,92,93,94,95',
   'Paris et sa région concentrent une densité de sorties pour enfants qu''on ne trouve nulle part ailleurs : grands musées avec ateliers, spectacles jeune public toute l''année, parcs et bases de loisirs accessibles en RER. Les sorties ci-dessous couvrent les huit départements franciliens.', 1),
  ('le-havre', 'Le Havre', '766,767,762,764',
   'Entre la plage, les bassins et la forêt de Montgeon, Le Havre et son agglomération se prêtent bien aux sorties en famille — y compris les jours de pluie, entre les musées et les équipements couverts de la ville.', 2),
  ('niort', 'Niort', '79',
   'Niort, le Marais poitevin et les Deux-Sèvres offrent des sorties nature à hauteur d''enfant : promenades en barque, fermes pédagogiques, sentiers faciles, sans oublier les rendez-vous culturels de la ville.', 3),
  ('nancy', 'Nancy', '54',
   'Nancy et la Meurthe-et-Moselle réunissent un patrimoine que les enfants regardent volontiers — la place Stanislas, le muséum-aquarium, le jardin botanique — et une saison de spectacles jeune public bien fournie.', 4);

-- Une zone se résout par préfixe de code postal, donc par un LIKE sur cette
-- colonne : sans index, chaque page de zone relit toute la table des lieux.
CREATE INDEX `Venue_postalCode_idx` ON `Venue`(`postalCode`);
