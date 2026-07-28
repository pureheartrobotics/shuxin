-- Soft companion chat history: filter conversation_events by metadata.companion_id
CREATE INDEX IF NOT EXISTS conversation_events_user_companion_created_idx
    ON conversation_events (user_id, (metadata->>'companion_id'), created_at DESC)
    WHERE deleted_at IS NULL AND event_type = 'conversation_turn';
