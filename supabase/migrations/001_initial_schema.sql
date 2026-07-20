-- ============================================================
-- 001_initial_schema.sql
-- ゲーム音楽発見サービス 初期スキーマ
-- ============================================================

-- ── ゲーム ──────────────────────────────────────────────────
CREATE TABLE games (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  title           TEXT NOT NULL,
  title_ja        TEXT,
  steam_app_id    BIGINT UNIQUE,
  igdb_id         BIGINT UNIQUE,
  vgmdb_album_id  INTEGER,
  description     TEXT,
  release_year    INTEGER,
  cover_image_url TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_games_steam_app_id ON games (steam_app_id);
CREATE INDEX idx_games_release_year ON games (release_year);

-- ── 作曲家 / アーティスト ────────────────────────────────────
CREATE TABLE composers (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name             TEXT NOT NULL,
  musicbrainz_id   UUID UNIQUE,
  lastfm_name      TEXT,            -- Last.fm の表記（類似度検索に使う）
  bio              TEXT,
  image_url        TEXT,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_composers_name ON composers USING gin (to_tsvector('simple', name));

-- ── トラック（曲）────────────────────────────────────────────
-- ゲーム : トラック = 1 : 多
CREATE TABLE tracks (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  game_id          UUID NOT NULL REFERENCES games (id) ON DELETE CASCADE,
  title            TEXT NOT NULL,
  track_number     INTEGER,
  duration_seconds INTEGER,
  youtube_video_id TEXT,   -- 事前バッチ取得して保存（埋め込み再生用）
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_tracks_game_id ON tracks (game_id);

-- ── トラック × 作曲家（多対多）──────────────────────────────
-- MVP では1曲1作曲家の想定だが、is_primary で主担当を表現して精度を保つ
CREATE TABLE track_composers (
  track_id    UUID NOT NULL REFERENCES tracks (id) ON DELETE CASCADE,
  composer_id UUID NOT NULL REFERENCES composers (id) ON DELETE CASCADE,
  is_primary  BOOLEAN NOT NULL DEFAULT TRUE,
  PRIMARY KEY (track_id, composer_id)
);

CREATE INDEX idx_track_composers_composer_id ON track_composers (composer_id);

-- ── 雰囲気タグ ───────────────────────────────────────────────
CREATE TABLE mood_tags (
  id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name    TEXT UNIQUE NOT NULL,    -- 'orchestral', 'dark', 'ambient' ...
  name_ja TEXT                     -- 「壮大なオーケストラ」など
);

-- ── ゲーム × タグ（多対多）──────────────────────────────────
CREATE TABLE game_tags (
  game_id    UUID NOT NULL REFERENCES games (id) ON DELETE CASCADE,
  tag_id     UUID NOT NULL REFERENCES mood_tags (id) ON DELETE CASCADE,
  confidence FLOAT NOT NULL DEFAULT 1.0,  -- 将来 ML スコアに使う
  added_by   TEXT NOT NULL DEFAULT 'system',  -- 'system' | 'community'
  PRIMARY KEY (game_id, tag_id)
);

CREATE INDEX idx_game_tags_tag_id ON game_tags (tag_id);

-- ── 作曲家間類似度（Last.fm / Spotify キャッシュ）─────────────
-- 定期バッチで更新。API に毎回問い合わせない。
CREATE TABLE composer_similarities (
  composer_id_a UUID NOT NULL REFERENCES composers (id) ON DELETE CASCADE,
  composer_id_b UUID NOT NULL REFERENCES composers (id) ON DELETE CASCADE,
  score         FLOAT NOT NULL CHECK (score BETWEEN 0 AND 1),
  source        TEXT NOT NULL DEFAULT 'lastfm',
  fetched_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (composer_id_a, composer_id_b)
);

CREATE INDEX idx_composer_sim_a_score
  ON composer_similarities (composer_id_a, score DESC);

-- ── ユーザー ─────────────────────────────────────────────────
-- Supabase Auth の auth.users と 1:1 対応
CREATE TABLE users (
  id           UUID PRIMARY KEY,   -- auth.users.id と一致させる
  steam_id     TEXT UNIQUE NOT NULL,
  display_name TEXT,
  avatar_url   TEXT,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── ユーザー × ゲーム（ライブラリ・星評価）──────────────────
CREATE TABLE user_games (
  id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id                UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  game_id                UUID NOT NULL REFERENCES games (id),
  rating                 INTEGER CHECK (rating BETWEEN 1 AND 5),
  is_played              BOOLEAN NOT NULL DEFAULT TRUE,
  steam_playtime_minutes INTEGER,
  added_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  rated_at               TIMESTAMPTZ,
  UNIQUE (user_id, game_id)
);

CREATE INDEX idx_user_games_user_id      ON user_games (user_id);
CREATE INDEX idx_user_games_user_rating  ON user_games (user_id, rating DESC NULLS LAST);

-- ── タイムスタンプ自動更新 ───────────────────────────────────
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN NEW.updated_at = NOW(); RETURN NEW; END;
$$;

CREATE TRIGGER trg_games_updated_at
  BEFORE UPDATE ON games
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ============================================================
-- RLS（Row Level Security）
-- ============================================================

-- マスタデータ：全員が読み取り可、書き込みはサービスロールのみ
ALTER TABLE games               ENABLE ROW LEVEL SECURITY;
ALTER TABLE composers           ENABLE ROW LEVEL SECURITY;
ALTER TABLE tracks              ENABLE ROW LEVEL SECURITY;
ALTER TABLE track_composers     ENABLE ROW LEVEL SECURITY;
ALTER TABLE mood_tags           ENABLE ROW LEVEL SECURITY;
ALTER TABLE game_tags           ENABLE ROW LEVEL SECURITY;
ALTER TABLE composer_similarities ENABLE ROW LEVEL SECURITY;

CREATE POLICY "public_read" ON games               FOR SELECT USING (true);
CREATE POLICY "public_read" ON composers           FOR SELECT USING (true);
CREATE POLICY "public_read" ON tracks              FOR SELECT USING (true);
CREATE POLICY "public_read" ON track_composers     FOR SELECT USING (true);
CREATE POLICY "public_read" ON mood_tags           FOR SELECT USING (true);
CREATE POLICY "public_read" ON game_tags           FOR SELECT USING (true);
CREATE POLICY "public_read" ON composer_similarities FOR SELECT USING (true);

-- ユーザーデータ：本人のみ読み書き可
ALTER TABLE users      ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_games ENABLE ROW LEVEL SECURITY;

CREATE POLICY "owner_only" ON users
  USING (id = auth.uid());

CREATE POLICY "owner_only" ON user_games
  USING (user_id = auth.uid());

CREATE POLICY "owner_insert" ON user_games
  FOR INSERT WITH CHECK (user_id = auth.uid());

CREATE POLICY "owner_update" ON user_games
  FOR UPDATE USING (user_id = auth.uid());

CREATE POLICY "owner_delete" ON user_games
  FOR DELETE USING (user_id = auth.uid());

-- ============================================================
-- 初期タグデータ（雰囲気タグのシード）
-- ============================================================
INSERT INTO mood_tags (name, name_ja) VALUES
  ('orchestral',       '壮大なオーケストラ'),
  ('dark',             'ダーク・重厚'),
  ('ambient',          'アンビエント・環境音楽'),
  ('upbeat',           '明るく軽快'),
  ('chiptune',         'チップチューン・レトロ'),
  ('jazz',             'ジャズ・ブルース'),
  ('electronic',       'エレクトロニック'),
  ('acoustic',         'アコースティック'),
  ('epic',             'エピック・壮大'),
  ('melancholic',      'メランコリック・哀愁'),
  ('relaxing',         'リラックス・癒し'),
  ('intense',          '激しい・テンション高'),
  ('folk',             'フォーク・民族音楽'),
  ('metal',            'メタル・ロック'),
  ('vocal',            'ボーカル曲');
