import express, { NextFunction, Request, Response } from 'express';
import cookieParser from 'cookie-parser';
import rateLimit from 'express-rate-limit';
import { config } from './config';
import { attachUser } from './middleware/auth';
import { authRouter } from './routes/auth';
import { eventsRouter } from './routes/events';
import { moderationRouter } from './routes/moderation';
import { adminRouter } from './routes/admin';
import { categoriesRouter } from './routes/categories';
import { areasRouter } from './routes/areas';
import { scraperRouter } from './routes/scraper';
import { apiKeysRouter } from './routes/apiKeys';
import { siteRouter } from './routes/site';

const app = express();

// Nécessaire derrière un reverse proxy (nginx/Caddy) : IP client et détection HTTPS correctes.
if (process.env.NODE_ENV === 'production') {
  app.set('trust proxy', 1);
}

app.use(express.json());
app.use(cookieParser());

// Limite les appels des programmes tiers, par clé d'API présentée.
// Les sessions web (cookie) ne sont pas concernées.
app.use(
  '/api',
  rateLimit({
    windowMs: 15 * 60 * 1000,
    limit: 300,
    standardHeaders: true,
    legacyHeaders: false,
    skip: (req) => !req.headers.authorization?.startsWith('Bearer '),
    keyGenerator: (req) => req.headers.authorization!,
    message: { error: 'Trop de requêtes, réessayez plus tard' },
  }),
);

app.use(attachUser);

app.use('/uploads', express.static(config.uploadsDir, { maxAge: '7d', immutable: true }));

app.use('/api/auth', authRouter);
app.use('/api/events', eventsRouter);
app.use('/api/moderation', moderationRouter);
app.use('/api/admin', adminRouter);
app.use('/api/categories', categoriesRouter);
app.use('/api/areas', areasRouter);
app.use('/api/keys', apiKeysRouter);
app.use('/api/scraper', scraperRouter);

app.get('/api/health', (_req, res) => {
  res.json({ ok: true });
});

// Le site, en dernier : tout ce qui n'est pas une route d'API est une page à
// servir — pré-rendue pour les moteurs, puis reprise par Vue dans le
// navigateur. Ce routeur porte aussi robots.txt et sitemap.xml.
app.use(siteRouter);

// Gestion d'erreur centralisée (multer, JSON malformé, erreurs inattendues…)
app.use((err: Error, _req: Request, res: Response, _next: NextFunction) => {
  if (res.headersSent) return;
  const known =
    err.name === 'MulterError' || err.message.startsWith('Format de photo');
  if (known) {
    res.status(400).json({ error: err.message });
    return;
  }
  console.error(err);
  res.status(500).json({ error: 'Erreur interne du serveur' });
});

app.listen(config.port, () => {
  console.log(`API démarrée sur http://localhost:${config.port}`);
});
