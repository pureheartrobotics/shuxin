-- All active devices use Volcengine voice clone TTS (matches default_device_tts_config in config.py).
UPDATE devices
SET tts_config = '{"type":"volcengine-clone","profile_id":"shuxin","encoding":"mp3","output_dir":"outputs"}'::jsonb,
    updated_at = now()
WHERE deleted_at IS NULL;
