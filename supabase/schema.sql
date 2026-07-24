-- ============================================================
-- schema.sql
-- ゲーム音楽発見サービス — public スキーマ定義（現在の確定状態）
--
-- このファイルを唯一の真実とする。スキーマ変更時は
--   1. Supabase ダッシュボードまたは psql で ALTER TABLE 等を実行
--   2. このファイルを手動または supabase db dump で更新
--   3. git commit
-- ============================================================

-- ── テーブル ──────────────────────────────────────────────────────────────────

CREATE TABLE games (
  id                   UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  title                TEXT        NOT NULL,
  title_ja             TEXT,
  steam_app_id         BIGINT      UNIQUE,
  igdb_id              BIGINT      UNIQUE,
  description          TEXT,
  description_ja       TEXT,
  description_zh       TEXT,
  release_year         INTEGER,
  cover_image_url      TEXT,
  tags_locked          BOOLEAN     NOT NULL DEFAULT FALSE,
  youtube_locked       BOOLEAN     NOT NULL DEFAULT FALSE,
  is_discoverable      BOOLEAN     NOT NULL DEFAULT FALSE,
  steam_ost_appid      BIGINT      UNIQUE,
  steam_ost_scraped_at TIMESTAMPTZ,
  youtube_video_id     TEXT,
  youtube_flagged      BOOLEAN     NOT NULL DEFAULT FALSE,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON COLUMN games.steam_app_id     IS 'Steam ゲーム本体のappid（サントラDLC/Soundtrackのappidではない）。GetOwnedGames API と突合して user_games にマッチさせるために使用。';
COMMENT ON COLUMN games.tags_locked      IS 'TRUE: Last.fm でタグが取得できないゲーム。日次バッチがスキップする。';
COMMENT ON COLUMN games.youtube_locked   IS 'TRUE: YouTube で動画が見つからないゲーム。日次バッチがスキップする。';
COMMENT ON COLUMN games.youtube_video_id IS 'OST 全体の YouTube 動画 ID。トラック単位の動画は tracks.youtube_video_id を参照。';
COMMENT ON COLUMN games.youtube_flagged  IS 'TRUE: ユーザーから「動画が違う」報告あり。管理者確認待ち。';


CREATE TABLE composers (
  id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  name           TEXT        NOT NULL,
  musicbrainz_id UUID        UNIQUE,
  lastfm_name    TEXT,
  bio            TEXT,
  image_url      TEXT,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


CREATE TABLE tracks (
  id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  game_id          UUID        NOT NULL REFERENCES games (id) ON DELETE CASCADE,
  title            TEXT        NOT NULL,
  track_number     INTEGER,
  duration_seconds INTEGER,
  youtube_video_id TEXT,
  youtube_flagged  BOOLEAN     NOT NULL DEFAULT FALSE,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT uq_tracks_game_track_number UNIQUE (game_id, track_number)
);

COMMENT ON COLUMN tracks.youtube_video_id IS '将来のトラック別動画対応用。OST 全体動画は games.youtube_video_id を使用。';
COMMENT ON COLUMN tracks.youtube_flagged  IS 'TRUE: ユーザーから「動画が違う」報告あり。管理者確認待ち。VideoIDは即座には削除しない。';


CREATE TABLE track_composers (
  track_id    UUID    NOT NULL REFERENCES tracks (id) ON DELETE CASCADE,
  composer_id UUID    NOT NULL REFERENCES composers (id) ON DELETE CASCADE,
  is_primary  BOOLEAN NOT NULL DEFAULT TRUE,
  PRIMARY KEY (track_id, composer_id)
);


CREATE TABLE mood_tags (
  id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name    TEXT UNIQUE NOT NULL,
  name_ja TEXT
);


CREATE TABLE game_tags (
  game_id    UUID  NOT NULL REFERENCES games (id) ON DELETE CASCADE,
  tag_id     UUID  NOT NULL REFERENCES mood_tags (id) ON DELETE CASCADE,
  confidence FLOAT NOT NULL DEFAULT 1.0,
  added_by   TEXT  NOT NULL DEFAULT 'system',
  PRIMARY KEY (game_id, tag_id)
);


CREATE TABLE composer_similarities (
  composer_id_a UUID  NOT NULL REFERENCES composers (id) ON DELETE CASCADE,
  composer_id_b UUID  NOT NULL REFERENCES composers (id) ON DELETE CASCADE,
  score         FLOAT NOT NULL CHECK (score BETWEEN 0 AND 1),
  source        TEXT  NOT NULL DEFAULT 'lastfm',
  fetched_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (composer_id_a, composer_id_b)
);


CREATE TABLE users (
  id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  steam_id     TEXT        UNIQUE NOT NULL,
  display_name TEXT,
  avatar_url   TEXT,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


CREATE TABLE user_games (
  id                     UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id                UUID        NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  game_id                UUID        NOT NULL REFERENCES games (id) ON DELETE CASCADE,
  rating                 INTEGER     CHECK (rating BETWEEN 1 AND 5),
  is_played              BOOLEAN     NOT NULL DEFAULT TRUE,
  steam_playtime_minutes INTEGER,
  added_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  rated_at               TIMESTAMPTZ,
  UNIQUE (user_id, game_id)
);


CREATE TABLE system_settings (
  key        TEXT        PRIMARY KEY,
  value      TEXT        NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- ── インデックス ───────────────────────────────────────────────────────────────

CREATE INDEX idx_games_steam_app_id       ON games (steam_app_id);
CREATE INDEX idx_games_release_year       ON games (release_year);
CREATE INDEX idx_composers_name           ON composers USING gin (to_tsvector('simple', name));
CREATE INDEX idx_tracks_game_id           ON tracks (game_id);
CREATE INDEX idx_track_composers_composer ON track_composers (composer_id);
CREATE INDEX idx_game_tags_tag_id         ON game_tags (tag_id);
CREATE INDEX idx_composer_sim_a_score     ON composer_similarities (composer_id_a, score DESC);
CREATE INDEX idx_user_games_user_id       ON user_games (user_id);
CREATE INDEX idx_user_games_user_rating   ON user_games (user_id, rating DESC NULLS LAST);


-- ── 関数 / トリガー ───────────────────────────────────────────────────────────

-- games.updated_at 自動更新
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN NEW.updated_at = NOW(); RETURN NEW; END;
$$;

CREATE TRIGGER trg_games_updated_at
  BEFORE UPDATE ON games
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();


-- is_discoverable 自動再計算
-- 判定: game_tags が1件以上 OR games.youtube_video_id が非NULL OR tracks.youtube_video_id が非NULL
CREATE OR REPLACE FUNCTION recalculate_is_discoverable()
RETURNS TRIGGER AS $$
DECLARE
  gid       UUID;
  has_tags  BOOLEAN;
  has_video BOOLEAN;
BEGIN
  IF TG_TABLE_NAME = 'games' THEN
    gid := COALESCE(NEW.id, OLD.id);
  ELSE
    gid := COALESCE(NEW.game_id, OLD.game_id);
  END IF;

  SELECT EXISTS(
    SELECT 1 FROM game_tags WHERE game_id = gid
  ) INTO has_tags;

  SELECT (
    EXISTS(SELECT 1 FROM games  WHERE id      = gid AND youtube_video_id IS NOT NULL)
    OR
    EXISTS(SELECT 1 FROM tracks WHERE game_id = gid AND youtube_video_id IS NOT NULL)
  ) INTO has_video;

  UPDATE games SET is_discoverable = (has_tags OR has_video) WHERE id = gid;
  RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_discoverable_on_game_tags ON game_tags;
CREATE TRIGGER trg_discoverable_on_game_tags
  AFTER INSERT OR DELETE ON game_tags
  FOR EACH ROW EXECUTE FUNCTION recalculate_is_discoverable();

DROP TRIGGER IF EXISTS trg_discoverable_on_tracks ON tracks;
CREATE TRIGGER trg_discoverable_on_tracks
  AFTER INSERT OR UPDATE OF youtube_video_id OR DELETE ON tracks
  FOR EACH ROW EXECUTE FUNCTION recalculate_is_discoverable();

DROP TRIGGER IF EXISTS trg_discoverable_on_games_yt ON games;
CREATE TRIGGER trg_discoverable_on_games_yt
  AFTER UPDATE OF youtube_video_id ON games
  FOR EACH ROW EXECUTE FUNCTION recalculate_is_discoverable();


-- ── RLS ───────────────────────────────────────────────────────────────────────

ALTER TABLE games               ENABLE ROW LEVEL SECURITY;
ALTER TABLE composers           ENABLE ROW LEVEL SECURITY;
ALTER TABLE tracks              ENABLE ROW LEVEL SECURITY;
ALTER TABLE track_composers     ENABLE ROW LEVEL SECURITY;
ALTER TABLE mood_tags           ENABLE ROW LEVEL SECURITY;
ALTER TABLE game_tags           ENABLE ROW LEVEL SECURITY;
ALTER TABLE composer_similarities ENABLE ROW LEVEL SECURITY;
ALTER TABLE users               ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_games          ENABLE ROW LEVEL SECURITY;
ALTER TABLE system_settings     ENABLE ROW LEVEL SECURITY;

CREATE POLICY "public_read" ON games               FOR SELECT USING (true);
CREATE POLICY "public_read" ON composers           FOR SELECT USING (true);
CREATE POLICY "public_read" ON tracks              FOR SELECT USING (true);
CREATE POLICY "public_read" ON track_composers     FOR SELECT USING (true);
CREATE POLICY "public_read" ON mood_tags           FOR SELECT USING (true);
CREATE POLICY "public_read" ON game_tags           FOR SELECT USING (true);
CREATE POLICY "public_read" ON composer_similarities FOR SELECT USING (true);

CREATE POLICY "owner_only"   ON users      USING (id = auth.uid());
CREATE POLICY "owner_only"   ON user_games USING (user_id = auth.uid());
CREATE POLICY "owner_insert" ON user_games FOR INSERT WITH CHECK (user_id = auth.uid());
CREATE POLICY "owner_update" ON user_games FOR UPDATE USING (user_id = auth.uid());
CREATE POLICY "owner_delete" ON user_games FOR DELETE USING (user_id = auth.uid());


-- ── 初期データ（スキーマの一部として管理）────────────────────────────────────

INSERT INTO mood_tags (name, name_ja) VALUES
  ('orchestral',  '壮大なオーケストラ'),
  ('dark',        'ダーク・重厚'),
  ('ambient',     'アンビエント・環境音楽'),
  ('upbeat',      '明るく軽快'),
  ('chiptune',    'チップチューン・レトロ'),
  ('jazz',        'ジャズ・ブルース'),
  ('electronic',  'エレクトロニック'),
  ('acoustic',    'アコースティック'),
  ('epic',        'エピック・壮大'),
  ('melancholic', 'メランコリック・哀愁'),
  ('relaxing',    'リラックス・癒し'),
  ('intense',     '激しい・テンション高'),
  ('folk',        'フォーク・民族音楽'),
  ('metal',       'メタル・ロック'),
  ('vocal',       'ボーカル曲');

INSERT INTO system_settings (key, value) VALUES ('steam_scan_offset', '0');
