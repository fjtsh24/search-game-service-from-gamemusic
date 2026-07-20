# 06 開発計画（M1〜M4 → ベータリリース）

## 全体目標

M4完了時点でベータリリース。Path A・Path B の両方が外部から使える状態を目指す。

## マイルストーン一覧

| # | マイルストーン | 完了条件 |
|---|---|---|
| M1 | データ基盤 | 音楽グラフが動く。ゲーム・作曲家・タグのデータが入っている |
| M2 | 検索・閲覧 | Path A が完走する（アーティスト検索 → ゲーム詳細 → YouTube試聴 → Steam） |
| M3 | 認証・連携 | Steam ログイン・ライブラリインポート・星評価が動く |
| M4 | レコメンド | Path B が完走する（フィードが生成される） |
| β | ベータリリース | Vercel + Fly.io にデプロイ済み。外部から使える |

---

## M1: データ基盤

### 1-1. プロジェクト初期設定
- [x] ディレクトリ構成作成（`web/` `api/` `supabase/` `scripts/`）
- [x] Next.js 15 + TypeScript 初期化（`web/`）
- [x] FastAPI プロジェクト初期化（`api/`）
- [x] Supabase プロジェクト作成
- [x] `.gitignore` / `.env.example` 設定（APIキー類は一切コミットしない）
- [ ] GitHub Secret Scanning 有効化

### 1-2. データベーススキーマ実装
- [x] `games` テーブル
- [x] `composers` テーブル
- [x] `tracks` テーブル（game:track = 1:多）
- [x] `track_composers` テーブル（track:composer = 多:多、MVPでは is_primary で1:1相当を表現）
- [x] `mood_tags` / `game_tags` テーブル
- [x] `composer_similarities` テーブル（類似度キャッシュ）
- [x] `users` / `user_games` テーブル
- [x] Supabase RLS ポリシー（games/tracks/composers は全員読み取り可、user_games は本人のみ）

### 1-3. データパイプライン

> **データソース方針（2026-07-20 確定）**
> - **主ソース: Steam Soundtracks カテゴリ（レビュー数降順）** — `scripts/import_steam_soundtracks.py`
> - **MusicBrainz**: ゲームの主ソースとしては不適切（映画・TV・アニメが混入）。`import_steam_soundtracks.py` 内で作曲家名の補完にのみ使用。単独スクリプト廃止済み。
> - **Last.fm `album.getTopTags`**: ゲームへのタグ付けに使用（新規スクリプトで実装予定）。
> - **VGMdb**: 非公式APIのため採用見送り。
> - **IGDB**: カバー画像取得用。MVP後に検討。

**実行順序が重要。各ステップは依存関係に従って進める。**

#### Step 1: ゲーム + 作曲家 + トラック取込み
- [x] `import_steam_soundtracks.py` 実装済み・200件投入済み
- [ ] **`import_steam_soundtracks.py` 修正**: 現状はゲームのみ登録（`composers` は upsert するが `tracks` / `track_composers` を作らない）。MusicBrainz でアーティストが見つかった場合に `tracks` + `track_composers` も作成するよう修正が必要。
- [ ] 修正後に再実行して作曲家とゲームを紐付け

#### Step 2: YouTube VideoID 付与（Step 1 完了後）
- [x] `import_youtube_video_ids.py` 実装済み（tracks が存在するゲームをスキップ）
- [ ] `python3 scripts/import_youtube_video_ids.py --limit 200` を実行

#### Step 3: ゲームへのタグ付け（Step 1 と独立して実施可）
- [ ] **`import_game_tags.py` 新規実装**: Last.fm `album.getTopTags` でゲームタイトルをキーに上位タグを取得し、`mood_tags` のボキャブラリーにマッピングして `game_tags` に保存する（例: `"ambient music"` → `"ambient"`、`"orchestral"` → `"orchestral"`）
- [ ] `python3 scripts/import_game_tags.py --limit 200` を実行

#### Step 4: 作曲家間類似度（Step 1 完了後）
- [x] `import_lastfm_similarities.py` 実装済み（DB に composers データが必要）
- [ ] `python3 scripts/import_lastfm_similarities.py` を実行

### 1-4. 音楽類似度ロジック
- [x] Upstash Redis セットアップ（API キャッシュ）
- [x] VibeTag Jaccard係数 計算ロジック実装（`api/app/services/similarity.py`）

---

## M2: 検索・閲覧（Path A 完走）

### 2-1. バックエンド API
- [x] `GET /search/composers?q=` — 作曲家・アーティスト名検索
- [x] `GET /search/games?q=` — ゲーム名検索
- [x] `GET /composers/{id}` — 作曲家詳細（担当ゲーム一覧つき）
- [x] `GET /games/{id}` — ゲーム詳細（タグ・類似ゲーム・YouTube VideoID）
- [x] `GET /games?tag_id=` — タグ別ゲーム一覧
- [x] `GET /games/{id}/similar` — 音楽的に似たゲーム一覧（Jaccard使用）

### 2-2. フロントエンド
- [x] 検索バー（アーティスト・ゲーム名）
- [x] 作曲家ページ（`/composers/[id]`）
- [x] ゲーム詳細ページ（`/games/[id]`）
  - タグ表示
  - 担当作曲家リンク
  - YouTube埋め込みプレーヤー
  - 類似ゲーム一覧
  - Steam へのリンク
- [x] タグ絞り込みページ（`/tags/[id]`）
- [x] 基本的なナビゲーション

---

## M3: 認証・連携（Path B 前半）

### 3-1. Steam OpenID 2.0 認証
- [x] Steam OpenID 2.0 実装（`check_authentication` 省略しない）
- [x] セッション管理（サーバーサイドセッション、JWT不使用）
- [x] ログイン / ログアウト エンドポイント
- [x] ユーザー作成フロー（初回ログイン時）
- [x] **アカウント削除フロー**（user_games 含む全データ削除）

### 3-2. Steam ライブラリ連携
- [x] Steam Web API でライブラリ取得（`GetOwnedGames`、最小権限）
- [x] インポートしたゲームを `user_games` に保存
- [x] インポートページ UI

### 3-3. 星評価
- [x] `POST /user/games/{game_id}/rating` — 星評価の登録・更新
- [x] ゲーム詳細ページに星評価 UI（1〜5）

---

## M4: レコメンド（Path B 完走）

### 4-1. レコメンドエンジン
- [x] ユーザーの評価済みゲームから music fingerprint を集計
- [x] Jaccard係数ベースの未体験ゲームスコアリング
- [x] `GET /users/me/feed` エンドポイント
- [ ] 星評価の更新時にフィードキャッシュを無効化（Redis）

### 4-2. フロントエンド
- [ ] ログイン後ホームページ（パーソナライズドフィード）
- [ ] フィードカードのデザイン（タイトル・タグ・類似理由）
- [ ] 未ログイン時のホームページ（タグ・人気ゲームの表示）

---

## β: ベータリリース

### デプロイ
- [ ] Vercel に `web/` デプロイ
- [ ] Fly.io に `api/` デプロイ
- [ ] 環境変数をそれぞれの本番環境に設定

### 品質チェック
- [ ] Path A が本番環境で完走できる
- [ ] Path B が本番環境で完走できる
- [ ] Steam 認証が本番ドメインで動く
- [ ] アカウント削除が動く
- [ ] Supabase RLS が正しく機能している（他ユーザーのデータにアクセスできない）

### ベータリリース後の既知制限（許容事項）
- データ量は限定的（サンプルデータ中心）
- タグはシステム付与のみ（コミュニティタグはV2）
- レコメンド精度は粗削り（データが増えるにつれ改善）

---

## V2 以降の要件（ベータ後に着手）

### 多言語対応（i18n）

ベータは日本語UIで運用し、V2で英語を追加することを前提に設計する。

**設計方針（ベータ時点で守るべき規約）:**
- フロントエンドの文字列は将来 `next-intl` 等に移行できるよう、ハードコードを局所化する
- DBの `title_ja` / `name_ja` カラムは既に多言語を想定した設計になっている
- API レスポンスは `title` (原題) と `title_ja` (日本語タイトル) を常に両方返す
- `<html lang="ja">` は将来ルートパラメータ `[locale]` に差し替える前提で記述する

**V2 実装タスク（未着手）:**
- [ ] `next-intl` 導入・`/ja` `/en` ルート構成
- [ ] UIテキストの翻訳ファイル作成（`messages/ja.json` `messages/en.json`）
- [ ] 言語スイッチャー UI
- [ ] API の `Accept-Language` ヘッダー対応（タグの `name` / `name_ja` 切り替え）

---

## ディレクトリ構成

```
/
├── web/              # Next.js 15 + TypeScript
├── api/              # Python + FastAPI
├── supabase/
│   └── migrations/   # SQL マイグレーション
├── scripts/          # データインポートスクリプト
├── docs/             # 企画ドキュメント（本ドキュメント含む）
├── .gitignore
├── .env.example
└── README.md
```

## 技術スタック（確定）

| 層 | 技術 |
|---|---|
| フロントエンド | Next.js 15 + TypeScript |
| バックエンド | Python 3.12 + FastAPI |
| データベース | PostgreSQL（Supabase） |
| キャッシュ | Upstash Redis |
| フロントホスティング | Vercel |
| バックホスティング | Fly.io |
| 音楽再生 | YouTube Data API v3（VideoID事前取得、埋め込み再生） |
| Steam認証 | Steam OpenID 2.0 |
