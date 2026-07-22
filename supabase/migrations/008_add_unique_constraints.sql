-- ============================================================
-- 008_add_unique_constraints.sql
-- 重複登録防止のための UNIQUE 制約追加
-- ============================================================

-- トラック: 同ゲーム内で track_number が重複しないよう制約
-- track_number が NULL のケースは除外（NULL は一意制約の対象外）
ALTER TABLE tracks
  ADD CONSTRAINT uq_tracks_game_track_number UNIQUE (game_id, track_number);

-- ゲーム: vgmdb_album_id を将来使用したときのために一意性を保証
ALTER TABLE games
  ADD CONSTRAINT uq_games_vgmdb_album_id UNIQUE (vgmdb_album_id);
