-- All active devices use Tencent realtime ASR (matches default_tencent_stt_config in config.py).
UPDATE devices
SET stt_config = '{"type":"tencent-realtime","appid":"","model":"16k_zh","output_dir":"outputs"}'::jsonb,
    updated_at = now()
WHERE deleted_at IS NULL;
