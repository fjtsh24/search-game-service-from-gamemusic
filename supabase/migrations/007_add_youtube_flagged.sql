ALTER TABLE tracks
  ADD COLUMN IF NOT EXISTS youtube_flagged BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN tracks.youtube_flagged IS 'TRUE: ユーザーから「動画が違う」報告あり。管理者確認待ち。VideoIDは即座には削除しない。';
