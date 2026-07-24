-- ============================================================
-- 015_fix_is_discoverable_triggers.sql
-- is_discoverable トリガーの明示的再定義
--
-- 背景:
--   migration 014 で recalculate_is_discoverable() 関数を CREATE OR REPLACE した。
--   PostgreSQL はトリガーから関数を名前参照するため、既存トリガーは更新後の
--   関数を自動的に呼び出すが、移行スクリプト内に tracks / game_tags トリガーの
--   記述がなく可読性・安全性に欠けるため、ここで明示的に再定義する。
-- ============================================================

-- game_tags の INSERT / DELETE 時
DROP TRIGGER IF EXISTS trg_discoverable_on_game_tags ON game_tags;
CREATE TRIGGER trg_discoverable_on_game_tags
AFTER INSERT OR DELETE ON game_tags
FOR EACH ROW EXECUTE FUNCTION recalculate_is_discoverable();

-- tracks の youtube_video_id 変更時（将来のトラック別動画対応用）
DROP TRIGGER IF EXISTS trg_discoverable_on_tracks ON tracks;
CREATE TRIGGER trg_discoverable_on_tracks
AFTER INSERT OR UPDATE OF youtube_video_id OR DELETE ON tracks
FOR EACH ROW EXECUTE FUNCTION recalculate_is_discoverable();

-- games.youtube_video_id 変更時（migration 014 で追加済み、念のため再定義）
DROP TRIGGER IF EXISTS trg_discoverable_on_games_yt ON games;
CREATE TRIGGER trg_discoverable_on_games_yt
AFTER UPDATE OF youtube_video_id ON games
FOR EACH ROW EXECUTE FUNCTION recalculate_is_discoverable();
