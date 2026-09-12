ALTER TABLE devices
    ADD COLUMN IF NOT EXISTS device_secret_encrypted text;
