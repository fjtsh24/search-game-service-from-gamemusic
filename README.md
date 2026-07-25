# ゲーム音楽発見サービス

好きなゲーム音楽を起点にゲームを発見できるWebサービス。

YouTube でサントラを試聴しながらゲームを探し、Steam でそのまま購入できます。Steam ログインでライブラリと星評価を連携すると、好みに合わせたレコメンドフィードが生成されます。

## 機能

- **検索**: アーティスト名・ゲーム名でゲームを検索
- **試聴**: YouTube プレーヤーで OST を試聴（トラックリスト付き）
- **購入**: Steam ストアページへ直リンク
- **評価**: Steam ログイン後に星1〜5で評価
- **レコメンド**: 評価履歴をもとにタグベースのフィードを生成（推薦理由タグ表示付き）
- **タグ申告**: 不正確なタグをフラグで報告

## 技術スタック

| 層 | 技術 |
|---|---|
| フロントエンド | Next.js 16 + TypeScript（Vercel） |
| バックエンド | Python + FastAPI（Fly.io） |
| データベース | Supabase（PostgreSQL + RLS） |
| 外部API | Steam API / YouTube Data API v3 / Last.fm API |
| CI/CD | GitHub Actions（日次データ補完バッチ・CI） |

## ディレクトリ構成

```
├── web/         Next.js 16 + TypeScript（フロントエンド）
├── api/         Python + FastAPI（バックエンド）
├── supabase/    DBスキーマ（schema.sql で一元管理）
├── scripts/     データインポート・日次バッチスクリプト
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

## 開発状況

| フェーズ | 内容 | 状態 |
|---|------|------|
| M1 | データ基盤 | ✅ 完了 |
| M2 | 検索・閲覧 | ✅ 完了 |
| M3 | 認証・連携 | ✅ 完了 |
| M4 | レコメンド | ✅ 完了 |
| β | ベータリリース | ✅ 完了 |
| Post-β | データ品質向上・UX改善 | 進行中 |

ベータリリース後のロードマップは [`docs/planning/07_post_beta_roadmap.md`](docs/planning/07_post_beta_roadmap.md) を参照してください。

## ライセンス

検討中（OSS公開はサービス安定後に予定）
