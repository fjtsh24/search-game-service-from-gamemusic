-- Migration 004: user_games FK cascade 追加 + steam_app_id の意味を明確化
--
-- 変更内容:
--   1. user_games.game_id FK に ON DELETE CASCADE を追加
--      → ゲームレコードを削除しても user_games が孤立しなくなる
--   2. games.steam_app_id の意味をコメントで明示
--      → サントラDLCのappidではなく、ゲーム本体のappidを格納する列

-- 1. user_games.game_id FK の再定義
ALTER TABLE user_games
  DROP CONSTRAINT user_games_game_id_fkey,
  ADD CONSTRAINT user_games_game_id_fkey
    FOREIGN KEY (game_id) REFERENCES games (id) ON DELETE CASCADE;

-- 2. games.steam_app_id の意味をコメントで記録
COMMENT ON COLUMN games.steam_app_id IS
  'Steam ゲーム本体のappid（サントラDLC/Soundtrackのappidではない）。'
  'GetOwnedGames API と突合して user_games にマッチさせるために使用。';
