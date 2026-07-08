import express, { NextFunction, Request, Response } from 'express';
import cookieParser from 'cookie-parser';
import { config } from './config';
import { attachUser } from './middleware/auth';
import { authRouter } from './routes/auth';
import { eventsRouter } from './routes/events';
import { moderationRouter } from './routes/moderation';
import { adminRouter } from './routes/admin';
import { categoriesRouter } from './routes/categories';

const app = express();

app.use(express.json());
app.use(cookieParser());
app.use(attachUser);

app.use('/uploads', express.static(config.uploadsDir, { maxAge: '7d', immutable: true }));

app.use('/api/auth', authRouter);
app.use('/api/events', eventsRouter);
app.use('/api/moderation', moderationRouter);
app.use('/api/admin', adminRouter);
app.use('/api/categories', categoriesRouter);

app.get('/api/health', (_req, res) => {
  res.json({ ok: true });
});

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
