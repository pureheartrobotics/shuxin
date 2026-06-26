-- 公告表
CREATE TABLE IF NOT EXISTS announcements (
    id          serial PRIMARY KEY,
    title       text NOT NULL,
    content     text NOT NULL,
    type        text NOT NULL DEFAULT 'banner'
        CHECK (type IN ('banner', 'popup')),
    is_active   boolean NOT NULL DEFAULT true,
    start_time  timestamptz,
    end_time    timestamptz,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

-- 加速获取生效中公告的查询
CREATE INDEX IF NOT EXISTS announcements_active_idx
    ON announcements (is_active, created_at DESC);

-- 用户意见反馈表
CREATE TABLE IF NOT EXISTS feedbacks (
    id          serial PRIMARY KEY,
    user_id     text NOT NULL,
    content     text NOT NULL,
    contact     text NOT NULL DEFAULT '',
    created_at  timestamptz NOT NULL DEFAULT now(),
    status      text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'processed', 'ignored')),
    admin_notes text NOT NULL DEFAULT ''
);

-- 加速用户反馈查询
CREATE INDEX IF NOT EXISTS feedbacks_created_at_idx
    ON feedbacks (created_at DESC);

CREATE INDEX IF NOT EXISTS feedbacks_user_id_idx
    ON feedbacks (user_id);
