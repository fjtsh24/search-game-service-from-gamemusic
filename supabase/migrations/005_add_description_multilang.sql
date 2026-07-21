-- 005_add_description_multilang.sql
-- ゲーム概要の多言語対応 (ja / zh-Hans)
-- 言語優先: ブラウザの Accept-Language に従って description_ja / description_zh / description を選択
ALTER TABLE games
  ADD COLUMN IF NOT EXISTS description_ja TEXT,
  ADD COLUMN IF NOT EXISTS description_zh TEXT;
