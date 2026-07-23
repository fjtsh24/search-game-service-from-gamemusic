-- is_discoverable を game_tags / tracks の変更時に自動再計算するトリガー
--
-- 判定ロジック: タグが1件以上 OR youtube_video_id があるトラックが1件以上 → TRUE
-- バッチスクリプト側の手動セット（is_discoverable=TRUE）は引き続き動作するが、
-- このトリガーが常に上書き再計算するため整合性が保たれる。

CREATE OR REPLACE FUNCTION recalculate_is_discoverable()
RETURNS TRIGGER AS $$
DECLARE
  gid UUID;
  has_tags BOOLEAN;
  has_video BOOLEAN;
BEGIN
  gid := COALESCE(NEW.game_id, OLD.game_id);

  SELECT EXISTS(
    SELECT 1 FROM game_tags WHERE game_id = gid
  ) INTO has_tags;

  SELECT EXISTS(
    SELECT 1 FROM tracks WHERE game_id = gid AND youtube_video_id IS NOT NULL
  ) INTO has_video;

  UPDATE games SET is_discoverable = (has_tags OR has_video) WHERE id = gid;
  RETURN NULL;
END;
$$ LANGUAGE plpgsql;

-- game_tags の INSERT / DELETE 時
CREATE TRIGGER trg_discoverable_on_game_tags
AFTER INSERT OR DELETE ON game_tags
FOR EACH ROW EXECUTE FUNCTION recalculate_is_discoverable();

-- tracks の youtube_video_id 変更時（UPDATE / INSERT / DELETE）
CREATE TRIGGER trg_discoverable_on_tracks
AFTER INSERT OR UPDATE OF youtube_video_id OR DELETE ON tracks
FOR EACH ROW EXECUTE FUNCTION recalculate_is_discoverable();
