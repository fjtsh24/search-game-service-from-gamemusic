-- games テーブルに MusicBrainz リリース ID を追加
-- インポートスクリプトの upsert 競合キーとして使用

ALTER TABLE games ADD COLUMN musicbrainz_release_id UUID UNIQUE;
