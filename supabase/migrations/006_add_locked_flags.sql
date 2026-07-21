ALTER TABLE games
  ADD COLUMN IF NOT EXISTS tags_locked    BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS youtube_locked BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN games.tags_locked    IS 'TRUE: Last.fm でタグが取得できないゲーム。日次バッチがスキップする。';
COMMENT ON COLUMN games.youtube_locked IS 'TRUE: YouTube で動画が見つからないゲーム。日次バッチがスキップする。';
