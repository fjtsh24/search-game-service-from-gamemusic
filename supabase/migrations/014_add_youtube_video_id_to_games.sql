-- ============================================================
-- 014_add_youtube_video_id_to_games.sql
-- OST全体の YouTube 動画 ID を games テーブルに移管する
--
-- 背景:
--   旧設計では tracks.youtube_video_id にゲーム全体の OST 動画を格納していた。
--   これはトラック単位の動画と概念が混在するため、games テーブルに正式移管する。
--   tracks.youtube_video_id は将来のトラック別動画対応のために残す（現在は未使用）。
-- ============================================================

-- 1. games テーブルにカラム追加
ALTER TABLE games
  ADD COLUMN IF NOT EXISTS youtube_video_id TEXT,
  ADD COLUMN IF NOT EXISTS youtube_flagged  BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN games.youtube_video_id IS 'OST 全体の YouTube 動画 ID。トラック単位の動画は tracks.youtube_video_id を参照。';
COMMENT ON COLUMN games.youtube_flagged   IS 'TRUE: ユーザーから「動画が違う」報告あり。管理者確認待ち。';

-- 2. is_discoverable トリガー関数を更新
--    has_video: games.youtube_video_id OR tracks.youtube_video_id のいずれかがあれば TRUE
CREATE OR REPLACE FUNCTION recalculate_is_discoverable()
RETURNS TRIGGER AS $$
DECLARE
  gid UUID;
  has_tags  BOOLEAN;
  has_video BOOLEAN;
BEGIN
  -- games テーブルのトリガーは id を使う / それ以外は game_id を使う
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

-- 3. games.youtube_video_id 変更時のトリガーを追加
DROP TRIGGER IF EXISTS trg_discoverable_on_games_yt ON games;
CREATE TRIGGER trg_discoverable_on_games_yt
AFTER UPDATE OF youtube_video_id ON games
FOR EACH ROW EXECUTE FUNCTION recalculate_is_discoverable();

-- 4. データ移行: tracks の youtube_video_id を games へコピー
--    各ゲームで youtube_video_id を持つ最初のトラック（track_number 昇順）を使用
UPDATE games g
SET youtube_video_id = (
  SELECT t.youtube_video_id
  FROM tracks t
  WHERE t.game_id = g.id
    AND t.youtube_video_id IS NOT NULL
  ORDER BY t.track_number ASC NULLS LAST, t.id ASC
  LIMIT 1
)
WHERE EXISTS (
  SELECT 1 FROM tracks t
  WHERE t.game_id = g.id AND t.youtube_video_id IS NOT NULL
);

-- 5. youtube_flagged 移行: tracks でフラグが立っていたゲームを games にも反映
UPDATE games g
SET youtube_flagged = TRUE
WHERE EXISTS (
  SELECT 1 FROM tracks t
  WHERE t.game_id = g.id AND t.youtube_flagged = TRUE
);

-- 6. tracks.youtube_video_id をクリア（OST 全体動画は games に移行済み）
--    トリガーが発火するが games.youtube_video_id は設定済みのため is_discoverable は維持される
UPDATE tracks SET youtube_video_id = NULL WHERE youtube_video_id IS NOT NULL;

-- 7. is_discoverable を全件再計算（移行後の最終確認）
UPDATE games g
SET is_discoverable = (
  EXISTS(SELECT 1 FROM game_tags WHERE game_id = g.id)
  OR g.youtube_video_id IS NOT NULL
  OR EXISTS(SELECT 1 FROM tracks WHERE game_id = g.id AND youtube_video_id IS NOT NULL)
);
