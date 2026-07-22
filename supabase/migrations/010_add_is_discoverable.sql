-- ============================================================
-- 010_add_is_discoverable.sql
-- タグ・YouTube動画の両方が未登録のゲームをリスト取得から除外するためのフラグ
-- ============================================================

ALTER TABLE games ADD COLUMN is_discoverable BOOLEAN NOT NULL DEFAULT FALSE;

-- 既存データのバックフィル:
--   game_tags にタグが1件以上ある、または
--   tracks に youtube_video_id が設定されているゲームを TRUE にセット
UPDATE games
SET is_discoverable = TRUE
WHERE id IN (
    SELECT DISTINCT game_id FROM game_tags
)
OR id IN (
    SELECT DISTINCT game_id FROM tracks WHERE youtube_video_id IS NOT NULL
);
