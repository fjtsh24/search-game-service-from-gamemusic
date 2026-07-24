# ゲーム音楽発見サービス

ゲーム音楽を起点にゲームを発見できるWEBサービス。

## ディレクトリ構成

```
├── web/         Next.js 16 + TypeScript（フロントエンド）
├── api/         Python + FastAPI（バックエンド）
├── supabase/    DBスキーマ（schema.sql で一元管理）
├── scripts/     データインポートスクリプト
└── docs/        企画ドキュメント
```

## セットアップ

```bash
cp .env.example .env
# .env に各サービスのキーを記入

# フロントエンド
cd web && npm install && npm run dev

# バックエンド
cd api
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload

# データインポート（Supabase のスキーマ適用後）
cd scripts
pip install -r requirements.txt
python import_steam_soundtracks.py --limit 50
```

## マイルストーン

| # | 内容 | 状態 |
|---|------|------|
| M1 | データ基盤 | ✅ 完了 |
| M2 | 検索・閲覧 | ✅ 完了 |
| M3 | 認証・連携 | ✅ 完了 |
| M4 | レコメンド | ✅ 完了 |
| β | ベータリリース | ✅ 完了 |

詳細: `docs/planning/06_development_plan.md`
