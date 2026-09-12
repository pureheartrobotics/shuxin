-- Rebrand default agent display name: 舒心 -> 初心 (agent_id unchanged)
UPDATE agents
SET display_name = '初心', updated_at = now()
WHERE agent_id = 'shuxin' AND display_name = '舒心';
