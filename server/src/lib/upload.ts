import crypto from 'crypto';
import fs from 'fs';
import path from 'path';
import multer from 'multer';
import sharp from 'sharp';
import { config } from '../config';

const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;

export const photoUpload = multer({
  storage: multer.memoryStorage(),
  limits: { fileSize: MAX_UPLOAD_BYTES },
  fileFilter: (_req, file, cb) => {
    if (/^image\/(jpeg|png|webp|gif|avif)$/.test(file.mimetype)) {
      cb(null, true);
    } else {
      cb(new Error('Format de photo non supporté (JPEG, PNG, WebP, GIF ou AVIF)'));
    }
  },
});

/**
 * Redimensionne la photo (max 1600px de large), la convertit en WebP et
 * l'écrit sur le disque. Retourne le chemin public à stocker en BDD.
 */
export async function savePhoto(buffer: Buffer): Promise<string> {
  await fs.promises.mkdir(config.uploadsDir, { recursive: true });
  const name = `${crypto.randomBytes(16).toString('hex')}.webp`;
  await sharp(buffer)
    .rotate() // applique l'orientation EXIF
    .resize({ width: 1600, withoutEnlargement: true })
    .webp({ quality: 82 })
    .toFile(path.join(config.uploadsDir, name));
  return `/uploads/${name}`;
}

export async function deletePhoto(photoUrl: string): Promise<void> {
  const name = path.basename(photoUrl);
  await fs.promises.unlink(path.join(config.uploadsDir, name)).catch(() => {});
}
