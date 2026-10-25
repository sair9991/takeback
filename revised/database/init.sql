-- enable pgvector extension for natural language semantic search
CREATE EXTENSION IF NOT EXISTS vector;

-- users table (3nf / bcnf)
CREATE TABLE IF NOT EXISTS users (
    user_id VARCHAR(64) PRIMARY KEY,
    email VARCHAR(255) UNIQUE,
    password_hash VARCHAR(255),
    google_id VARCHAR(255) UNIQUE,
    chess_com_username VARCHAR(64),
    lichess_username VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_google_id ON users(google_id);

-- seed default guest account for anonymous sessions
INSERT INTO users (user_id, email)
VALUES ('guest', 'guest@chessclone.local')
ON CONFLICT (user_id) DO NOTHING;

-- games table (3nf)
-- opponent_color is derived dynamically from player_color
CREATE TABLE IF NOT EXISTS games (
    id BIGSERIAL PRIMARY KEY,
    player_id VARCHAR(64) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    game_id VARCHAR(128) UNIQUE NOT NULL,
    src VARCHAR(32) NOT NULL,
    player_color VARCHAR(10) NOT NULL CHECK (player_color IN ('white', 'black')),
    player_elo INT CHECK (player_elo IS NULL OR player_elo >= 0),
    opponent_elo INT CHECK (opponent_elo IS NULL OR opponent_elo >= 0),
    opponent_username VARCHAR(64),
    result VARCHAR(32),
    time_control VARCHAR(32),
    date VARCHAR(32),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_games_player_date ON games(player_id, date DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_games_game_id ON games(game_id);

-- moves table (3nf)
-- clock_str is derived dynamically from time_remaining
CREATE TABLE IF NOT EXISTS moves (
    id BIGSERIAL PRIMARY KEY,
    game_id VARCHAR(128) NOT NULL REFERENCES games(game_id) ON DELETE CASCADE,
    ply INT NOT NULL CHECK (ply >= 0),
    side VARCHAR(10) NOT NULL CHECK (side IN ('white', 'black')),
    move VARCHAR(16) NOT NULL,
    time_remaining REAL CHECK (time_remaining IS NULL OR time_remaining >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_moves_game_ply UNIQUE (game_id, ply)
);

CREATE INDEX IF NOT EXISTS idx_moves_game_ply ON moves(game_id, ply ASC);

-- models table (3nf)
-- access_count and last_accessed_at are derived dynamically from model_access_logs
CREATE TABLE IF NOT EXISTS models (
    player_id VARCHAR(64) PRIMARY KEY,
    trained_by_user_id VARCHAR(64) REFERENCES users(user_id) ON DELETE SET NULL,
    weights_path TEXT NOT NULL,
    weights_blob BYTEA,
    model_name VARCHAR(64) NOT NULL DEFAULT 'clone',
    style_description TEXT,
    embedding vector(2048),
    val_accuracy REAL CHECK (val_accuracy IS NULL OR (val_accuracy >= 0.0 AND val_accuracy <= 1.0)),
    val_loss REAL CHECK (val_loss IS NULL OR val_loss >= 0.0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_models_trained_by ON models(trained_by_user_id);
-- Note: standard pgvector HNSW indexes have a 2000-dimension limit.
-- For 2048-dim Gemma vectors, PostgreSQL executes exact cosine distance scans (<=>) directly with full precision.

-- model_access_logs table (3nf event ledger)
CREATE TABLE IF NOT EXISTS model_access_logs (
    id BIGSERIAL PRIMARY KEY,
    player_id VARCHAR(64) NOT NULL REFERENCES models(player_id) ON DELETE CASCADE,
    accessed_by_user_id VARCHAR(64) REFERENCES users(user_id) ON DELETE SET NULL,
    think_time REAL CHECK (think_time IS NULL OR think_time >= 0),
    accessed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- covering index for index-only scans on model stats aggregation
CREATE INDEX IF NOT EXISTS idx_model_logs_perf ON model_access_logs(player_id, accessed_at DESC) INCLUDE (accessed_by_user_id);
CREATE INDEX IF NOT EXISTS idx_model_logs_user ON model_access_logs(accessed_by_user_id, accessed_at DESC);

-- analyzed_games master table (3nf)
CREATE TABLE IF NOT EXISTS analyzed_games (
    id BIGSERIAL PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    game_id VARCHAR(128) NOT NULL REFERENCES games(game_id) ON DELETE CASCADE,
    narrative TEXT,
    embedding vector(2048),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_analyzed_user_game UNIQUE (user_id, game_id)
);

CREATE INDEX IF NOT EXISTS idx_analyzed_user_id ON analyzed_games(user_id);
CREATE INDEX IF NOT EXISTS idx_analyzed_game_user ON analyzed_games(game_id, user_id);

-- analysis_evaluations table (3nf normalized per-ply evaluations)
CREATE TABLE IF NOT EXISTS analysis_evaluations (
    id BIGSERIAL PRIMARY KEY,
    analysis_id BIGINT NOT NULL REFERENCES analyzed_games(id) ON DELETE CASCADE,
    ply INT NOT NULL CHECK (ply >= 0),
    win_probability REAL NOT NULL CHECK (win_probability >= 0.0 AND win_probability <= 100.0),
    phase VARCHAR(32),
    headline TEXT,
    commentary TEXT,
    is_pivotal BOOLEAN NOT NULL DEFAULT FALSE,
    pivotal_label VARCHAR(64),
    CONSTRAINT uq_analysis_eval_ply UNIQUE (analysis_id, ply)
);

CREATE INDEX IF NOT EXISTS idx_eval_analysis_ply ON analysis_evaluations(analysis_id, ply ASC);
CREATE INDEX IF NOT EXISTS idx_eval_pivotal ON analysis_evaluations(analysis_id) WHERE is_pivotal = TRUE;

-- analysis_tags table (3nf normalized match trait tags)
CREATE TABLE IF NOT EXISTS analysis_tags (
    id BIGSERIAL PRIMARY KEY,
    analysis_id BIGINT NOT NULL REFERENCES analyzed_games(id) ON DELETE CASCADE,
    tag VARCHAR(64) NOT NULL,
    CONSTRAINT uq_analysis_tag UNIQUE (analysis_id, tag)
);

CREATE INDEX IF NOT EXISTS idx_analysis_tags_lookup ON analysis_tags(analysis_id, tag);
CREATE INDEX IF NOT EXISTS idx_analysis_tags_tag ON analysis_tags(tag);

-- view for instantaneous 3nf model stats aggregation
CREATE OR REPLACE VIEW v_model_stats AS
SELECT
    m.player_id,
    m.trained_by_user_id,
    m.weights_path,
    m.model_name,
    m.style_description,
    m.val_accuracy,
    m.val_loss,
    COALESCE(stats.access_count, 0) AS access_count,
    stats.last_accessed_at,
    m.created_at,
    m.updated_at
FROM models m
LEFT JOIN (
    SELECT
        player_id,
        COUNT(*) AS access_count,
        MAX(accessed_at) AS last_accessed_at
    FROM model_access_logs
    GROUP BY player_id
) stats ON m.player_id = stats.player_id;

-- auto-update timestamp trigger
CREATE OR REPLACE FUNCTION set_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_users_updated_at ON users;
CREATE TRIGGER trg_users_updated_at
BEFORE UPDATE ON users
FOR EACH ROW
EXECUTE FUNCTION set_updated_at_column();

DROP TRIGGER IF EXISTS trg_models_updated_at ON models;
CREATE TRIGGER trg_models_updated_at
BEFORE UPDATE ON models
FOR EACH ROW
EXECUTE FUNCTION set_updated_at_column();
