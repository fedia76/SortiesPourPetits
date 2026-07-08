/**
 * Génère un hash bcrypt à partir d'un mot de passe, sans jamais l'écrire sur le serveur.
 * Usage : npm run hash-password -- 'mon-mot-de-passe'
 * Copiez la sortie dans ADMIN_PASSWORD_HASH du .env de production.
 */
import bcrypt from 'bcryptjs';

const password = process.argv[2];
if (!password) {
  console.error("Usage : npm run hash-password -- 'mon-mot-de-passe'");
  process.exit(1);
}

bcrypt.hash(password, 12).then((hash) => {
  console.log(hash);
});
