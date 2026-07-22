-- ============================================================
-- 009_add_system_settings.sql
-- バッチスクリプトの実行状態を永続化するためのキーバリューテーブル
-- ============================================================

CREATE TABLE system_settings (
  key        TEXT PRIMARY KEY,
  value      TEXT NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- steam_scan_offset: 新規ゲーム追加バッチのスキャン開始位置（次回の再スキャン用）
INSERT INTO system_settings (key, value) VALUES ('steam_scan_offset', '0');

-- サービスロールのみ読み書き可（フロントエンドから参照しない）
ALTER TABLE system_settings ENABLE ROW LEVEL SECURITY;
