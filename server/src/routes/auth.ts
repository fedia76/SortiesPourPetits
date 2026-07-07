import bcrypt from 'bcryptjs';
import { Router } from 'express';
import { prisma } from '../db';
import { config } from '../config';
import { requireAuth, signToken } from '../middleware/auth';
import { loginSchema, registerSchema } from '../lib/validators';

export const authRouter = Router();

const COOKIE_OPTIONS = {
  httpOnly: true,
  sameSite: 'lax' as const,
  secure: process.env.NODE_ENV === 'production',
  maxAge: config.sessionMaxAgeMs,
};

function publicUser(user: { id: number; email: string; displayName: string; role: string }) {
  return { id: user.id, email: user.email, displayName: user.displayName, role: user.role };
}

authRouter.post('/register', async (req, res) => {
  const parsed = registerSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: parsed.error.issues[0].message });
    return;
  }
  const { email, password, displayName } = parsed.data;

  const existing = await prisma.user.findUnique({ where: { email } });
  if (existing) {
    res.status(409).json({ error: 'Un compte existe déjà avec cet email' });
    return;
  }

  const user = await prisma.user.create({
    data: { email, displayName, passwordHash: await bcrypt.hash(password, 12) },
  });

  res.cookie('token', signToken(user), COOKIE_OPTIONS);
  res.status(201).json({ user: publicUser(user) });
});

authRouter.post('/login', async (req, res) => {
  const parsed = loginSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: 'Email ou mot de passe invalide' });
    return;
  }
  const user = await prisma.user.findUnique({ where: { email: parsed.data.email } });
  if (!user || !(await bcrypt.compare(parsed.data.password, user.passwordHash))) {
    res.status(401).json({ error: 'Email ou mot de passe incorrect' });
    return;
  }
  res.cookie('token', signToken(user), COOKIE_OPTIONS);
  res.json({ user: publicUser(user) });
});

authRouter.post('/logout', (_req, res) => {
  res.clearCookie('token');
  res.json({ ok: true });
});

authRouter.get('/me', requireAuth, async (req, res) => {
  const user = await prisma.user.findUnique({ where: { id: req.user!.id } });
  if (!user) {
    res.clearCookie('token');
    res.status(401).json({ error: 'Compte introuvable' });
    return;
  }
  res.json({ user: publicUser(user) });
});
