# ゲーム音楽発見サービス

ゲーム音楽を起点にゲームを発見できるWEBサービス。

## ディレクトリ構成

```
├── web/         Next.js 15 + TypeScript（フロントエンド）
├── api/         Python + FastAPI（バックエンド）
├── supabase/    DBスキーマ・マイグレーション
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
pip install musicbrainzngs python-dotenv supabase
python import_musicbrainz.py --limit 200
```

## マイルストーン

| # | 内容 | 状態 |
|---|------|------|
| M1 | データ基盤 | 🚧 進行中 |
| M2 | 検索・閲覧 | 待機 |
| M3 | 認証・連携 | 待機 |
| M4 | レコメンド | 待機 |
| β | ベータリリース | 待機 |

詳細: `docs/planning/06_development_plan.md`

---

## ▶ 次回の作業手順（中断ポイント: 2026-07-18）

### 現在地

M1「データ基盤」の途中。プロジェクト骨格は完成済み。
**Supabase プロジェクトの作成とAPIキーの取得がまだ。**

### 手順①：Supabase セットアップ

1. [supabase.com](https://supabase.com) で新規プロジェクトを作成
2. プロジェクトの Settings → API から以下をコピーして `.env` に記入:
   - `SUPABASE_URL`
   - `SUPABASE_ANON_KEY`
   - `SUPABASE_SERVICE_ROLE_KEY`
3. SQL Editor で `supabase/migrations/001_initial_schema.sql` を実行
   - 全テーブル・RLS・初期タグ15件が作成される

### 手順②：外部APIキーの取得

| サービス | 取得先 | 記入する変数 |
|---------|--------|------------|
| Steam Web API | [steamcommunity.com/dev/apikey](https://steamcommunity.com/dev/apikey) | `STEAM_API_KEY` |
| Last.fm API | [last.fm/api/account/create](https://www.last.fm/api/account/create) | `LASTFM_API_KEY` |
| YouTube Data API v3 | Google Cloud Console → APIとサービス | `YOUTUBE_API_KEY` |
| IGDB (Twitch) | [dev.twitch.tv](https://dev.twitch.tv) でアプリ作成 | `IGDB_CLIENT_ID` / `IGDB_CLIENT_SECRET` |
| Upstash Redis | [upstash.com](https://upstash.com) で無料DBを作成 | `UPSTASH_REDIS_URL` / `UPSTASH_REDIS_TOKEN` |

`SESSION_SECRET` は任意の長いランダム文字列でOK（例: `openssl rand -hex 32`）

### 手順③：初期データ投入

```bash
cd scripts
pip install musicbrainzngs python-dotenv supabase
python import_musicbrainz.py --limit 200
```

ゲーム・作曲家データが DB に入ったら M1 完了。

### 手順④：M2（検索・閲覧）へ進む

`api/` と `web/` を起動して動作確認後、
フロントエンドのページ実装（ゲーム詳細・作曲家ページ・YouTube埋め込み）に入る。
