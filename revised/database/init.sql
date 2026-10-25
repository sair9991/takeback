CREATE TABLE IF NOT EXISTS users (
    user_id VARCHAR(64) PRIMARY KEY,
    email VARCHAR(255) UNIQUE,
    password_hash VARCHAR(255),
    google_id VARCHAR(255) UNIQUE,
    chess_com_username VARCHAR(64),
    lichess_username VARCHAR(64),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_google_id ON users(google_id);

CREATE TABLE IF NOT EXISTS games (
    id BIGSERIAL PRIMARY KEY,
    player_id VARCHAR(64) NOT NULL,
    game_id VARCHAR(128) UNIQUE NOT NULL,
    src VARCHAR(32) NOT NULL,
    player_color VARCHAR(10) NOT NULL,
    opponent_color VARCHAR(10) NOT NULL,
    player_elo INT,
    opponent_elo INT,
    opponent_username VARCHAR(64),
    result VARCHAR(32),
    time_control VARCHAR(32),
    date VARCHAR(32),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS moves (
    id BIGSERIAL PRIMARY KEY,
    game_id VARCHAR(128) NOT NULL,
    ply INT NOT NULL,
    side VARCHAR(10) NOT NULL,
    move VARCHAR(16) NOT NULL,
    time_remaining REAL,
    clock_str VARCHAR(16),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS models (
    player_id VARCHAR(64) PRIMARY KEY,
    trained_by_user_id VARCHAR(64),
    weights_path TEXT NOT NULL,
    weights_blob BYTEA,
    model_name VARCHAR(64) DEFAULT 'clone',
    val_accuracy REAL,
    val_loss REAL,
    eval_stats JSONB,
    access_count BIGINT DEFAULT 0,
    last_accessed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_models_trained_by ON models(trained_by_user_id);

CREATE TABLE IF NOT EXISTS model_access_logs (
    id BIGSERIAL PRIMARY KEY,
    player_id VARCHAR(64) NOT NULL,
    accessed_by_user_id VARCHAR(64),
    think_time REAL,
    accessed_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_model_logs_player ON model_access_logs(player_id, accessed_at DESC);
CREATE INDEX IF NOT EXISTS idx_model_logs_user ON model_access_logs(accessed_by_user_id, accessed_at DESC);

CREATE TABLE IF NOT EXISTS analyzed_games (
    id BIGSERIAL PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL,
    game_id VARCHAR(128) NOT NULL,
    odds JSONB,
    commentary JSONB,
    narrative TEXT,
    narrative_tags JSONB,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, game_id)
);

CREATE INDEX IF NOT EXISTS idx_games_player_date ON games(player_id, date DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_games_game_id ON games(game_id);
CREATE INDEX IF NOT EXISTS idx_moves_game_ply ON moves(game_id, ply ASC);
CREATE INDEX IF NOT EXISTS idx_analyzed_user_id ON analyzed_games(user_id);
CREATE INDEX IF NOT EXISTS idx_analyzed_game_user ON analyzed_games(game_id, user_id);
