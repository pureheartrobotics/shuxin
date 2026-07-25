-- Soft companion per-row metadata (milestones, care ack, stage cursor).
ALTER TABLE user_companions
  ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb;
