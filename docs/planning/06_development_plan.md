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
> - **主ソース: Steam Soundtracks カテゴリ（高評価フィルタ）** — `scripts/import_steam_soundtracks.py`
>   - `appreviews` API でサントラ自身のレビュースコアを確認し、Very Positive（80%以上）のみ採用
>   - レビュー数順での検索を維持しつつ、スコアが低いものをスキップ
> - **MusicBrainz**: ゲームの主ソースとしては不適切（映画・TV・アニメが混入）。`import_steam_soundtracks.py` 内で作曲家名の補完にのみ使用。単独スクリプト廃止済み。
> - **Last.fm `album.getTopTags`**: ゲームへのタグ付けに使用（新規スクリプトで実装予定）。
> - **VGMdb**: 非公式APIのため採用見送り。
> - **IGDB**: カバー画像取得用。MVP後に検討（現在は Steam CDN URL で代替）。

**実行順序が重要。各ステップは依存関係に従って進める。**

#### データ特性とバッチ補完の保証

| データ | 初回投入 | 補完方法 | VideoIDなし時のUI |
|---|---|---|---|
| `games` | Step 1 手動 | Step 1 を再実行（upsert） | — |
| `composers` / `track_composers` | Step 1 手動（MusicBrainz一致時のみ） | Step 1 再実行 | 作曲家セクション非表示 |
| `tracks` | Step 1（作曲家あり）or Step 2（なし） | Step 2 バッチが自動補完 | — |
| `tracks.youtube_video_id` | **Step 2 バッチが後から補完** | GitHub Actions 毎日自動 | "動画を準備中です" |
| `game_tags` | Step 3 手動（初回後は任意） | Step 3 再実行 or `--overwrite` | タグセクション非表示 |
| `composer_similarities` | Step 4 手動 | Step 4 再実行 | 類似ゲームなし |

> `tracks.youtube_video_id` は登録直後は null でよい。
> UIが「準備中」プレースホルダーを表示するため、ユーザー体験は壊れない。
> GitHub Actions の daily-import（毎日 JST 10:00）が順次補完する。

#### Step 1: ゲーム + 作曲家 + トラック取込み
- [x] `import_steam_soundtracks.py` 修正済み
  - Steam `appreviews` API でスコアフィルタ（デフォルト `--min-score 8` = Very Positive 80%以上）
  - MusicBrainz で作曲家が見つかった場合に `tracks` + `track_composers` も作成
  - Steam CDN から `cover_image_url` を設定
  - Steam `appdetails` の `type` フィールドで DLC・デモをスキップ（`game` または空文字のみ取込み）
- [x] 初回 200件インポート済み・日次バッチで継続追加中

#### Step 2: YouTube VideoID 付与（毎日 GitHub Actions バッチ）

> **データ特性**: YouTube VideoID は「後から補完」前提のバッチデータ。
> ゲーム登録時点では `tracks.youtube_video_id = null` でも問題なく、
> 毎日の GitHub Actions ジョブ（`daily-import.yml` → youtube ジョブ）が順次補完する。
> UIは VideoID なし状態を「動画を準備中です」と表示し、空欄にはしない。

- [x] `import_youtube_video_ids.py` 修正済み（2フェーズ対応）
  - **Phase 1（既存補完）**: `youtube_video_id = null` の既存トラックに VideoID を UPDATE
    - `import_steam_soundtracks.py` が作った作曲家リンク付きトラックも対象
  - **Phase 2（新規作成）**: tracks レコードがないゲームに新規トラックを INSERT
  - `--phase 1|2|all` で個別実行も可能
- [x] `YouTubePlayer.tsx`: VideoID なし時に「動画を準備中です」プレースホルダーを表示
- [x] GitHub Actions `daily-enrichment` ジョブで毎日 JST 04:00 に自動実行
- [x] 初回手動実行済み

#### Step 3: ゲームへのタグ付け（Step 1 と独立して実施可）
- [x] **`import_game_tags.py` 実装済み**
  - MusicBrainz mbid がある場合は mbid で Last.fm 検索（精度高）
  - ない場合は `{title} Soundtrack` + 最初の作曲家名でアルバム検索
  - Last.fm タグ名 → `mood_tags` ボキャブラリーへのキーワードマッピング
  - confidence は Last.fm の count を正規化（0.1〜1.0）
  - `--overwrite` で既タグゲームも再付与可能
- [x] 初回実行済み・日次バッチで継続中

#### Step 4: 作曲家間類似度（Step 1 完了後）
- [x] `import_lastfm_similarities.py` 実装済み（DB に composers データが必要）
- [x] 初回実行済み・手動トリガーで再実行可能

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
- [x] 星評価の更新時にフィードキャッシュを無効化（Redis）— `rate_game` 内で `cache.delete("feed:{user_id}")`
- [x] `GET /users/me/feed` に Redis キャッシュ（TTL 600s）+ limit キャップ（le=100）
- [x] `GET /tags` エンドポイント（mood_tags 一覧、TTL 3600s キャッシュ）

### 4-2. フロントエンド
- [x] ホームページ: 常にランダムゲーム一覧を表示（全件からランダム offset で取得）
- [x] ログイン＋ライブラリあり時: 「あなたへのおすすめ」をランダム一覧の上に追加表示（`FeedSection.tsx`）
- [x] 未ログイン時: タグクラウド + ランダムゲーム一覧
- [ ] フィードカードのデザイン改善（類似理由の表示など）— 現状は `GameCard` を流用

---

## β: ベータリリース（2026-07-21 完了）

### デプロイ
- [x] Vercel に `web/` デプロイ（https://search-game-service-from-gamemusic.vercel.app）
- [x] Fly.io に `api/` デプロイ（https://search-game-service-api.fly.dev）
- [x] 環境変数をそれぞれの本番環境に設定

### 品質チェック
- [x] Path A が本番環境で完走できる
- [x] Path B が本番環境で完走できる（※Cookie 修正後に完全動作）
- [x] Steam 認証が本番ドメインで動く（※URL・Cookie 修正後に完全動作）
- [x] アカウント削除が動く
- [x] Supabase RLS が正しく機能している

### リリース時の追加対応
- [x] pytest テストスイート（カバレッジ 54%）
- [x] GitHub Actions CI/CD（lint → test → Fly.io 自動デプロイ）
- [x] ゲーム説明文の多言語対応（EN/JA/ZH、Accept-Language で自動切替）
- [x] 全APIエンドポイントへの game_tags 追加
- [x] CORS を FRONTEND_URL 環境変数から動的生成

---

## ベータ後の修正・改善（2026-07-21）

### Steam 認証・セッション修正
- [x] `STEAM_OPENID_RETURN_URL` の設定ミス修正（`.fly.dev` が欠落していた）
- [x] Cookie の `samesite` 修正
  - フロント（vercel.app）と API（fly.dev）が別ドメインのため、`samesite=lax` では cross-site fetch で Cookie が送られず `/users/me` が常に 401 になっていた
  - 本番環境のみ `samesite=none + secure=True` に変更（開発環境は `lax` 維持）

### ホームページ・ランダム表示修正
- [x] ランダム取得ロジック修正
  - 旧: 先頭 `limit×5` 件を DB 取得順に固定してシャッフル → 後半のゲームが出現しない
  - 新: 全件カウント → ランダム offset → `limit` 件だけ取得（全ゲームが均等に候補）
- [x] ホームページ表示改善: ログイン＋ライブラリあり時に「あなたへのおすすめ」と「データベース収録タイトル」を両方表示（従来はおすすめのみで置換していた）

### 動画報告ボタン修正
- [x] `YouTubePlayer`（Client Component）内で `useEffect` + `getMe()` を呼ぶよう修正
  - 旧: Server Component で `getMe()` を呼んでいたため Node.js 側に Cookie が届かず常に `isLoggedIn=false`
  - 新: クライアント側で認証状態を取得し、ログイン時のみボタンを表示

### データ品質・インポート改善
- [x] Steam インポート時の DLC フィルタ追加（`type` フィールドで `game` 以外をスキップ）
- [x] 誤動画の削除・ロック処理（Hidden in Plain Sight、Chicken Hill、Slash/Jump、of the Devil）
- [x] 非ゲームアプリ（DFHack - Dwarf Fortress Modding Engine）を DB から削除

### 動画報告システム（`youtube_flagged`）
- [x] `tracks.youtube_flagged` カラム追加（migration 007）
- [x] ログインユーザーがゲーム詳細ページから動画を報告できる（`POST /games/{id}/flag-video`）
  - 即時削除ではなくフラグのみセット（悪用防止）
  - 日次バッチログで管理者が確認・判断する設計
- [x] 日次バッチで `youtube_flagged=true` のトラックをログ出力（GitHub Actions で確認可能）

---

## リリース後: データ拡充パイプライン（2026-07-21 設計）

### 方針
- 毎日 JST 04:00 に GitHub Actions `daily-enrichment` ジョブが自動実行
- 1日 ~100件、参照先サービスへの負荷を最小化（sleep による間隔制御）
- **更新優先 → 新規追加** の優先度で処理

### 処理内訳（合計 ~100件/日）

| 優先度 | 処理 | 件数 | API | sleep |
|---|---|---|---|---|
| 1 | タグ未付与ゲームへのタグ付与 | 40件 | Last.fm | 0.3s |
| 2 | 既存ゲームの欠損説明文補完（ja/zh） | 30件 | Steam appdetails | 1.2s |
| 3 | YouTube VideoID 欠損トラックの補完 | 20件 | YouTube Search | 0.1s |
| 4 | Steam 新規ゲーム追加 | 10件 | Steam Search | 1.2s |

### ロックフラグ（migration 006）
取得不可なゲームを日次バッチから除外するために DB フラグを導入。

| カラム | 説明 |
|---|---|
| `games.tags_locked` | Last.fm でタグが取得できないゲーム |
| `games.youtube_locked` | YouTube で動画が見つからないゲーム |

- ロック時はバッチ実行ログにタイトル一覧を出力（GitHub Actions のログで確認）
- 手動リセット: Supabase で `UPDATE games SET tags_locked=FALSE WHERE title='...'`
- ロック済み一覧確認: `SELECT title FROM games WHERE tags_locked OR youtube_locked`
- `--overwrite` フラグ付きで手動実行するとロックを無視して再試行可能

### 手動トリガー（workflow_dispatch）
GitHub Actions → Daily Data Import → Run workflow から個別実行可能：
- `youtube` / `steam_backfill` / `steam` / `game_tags` / `lastfm_similarities`

---

## V2 以降の要件（ベータ後に着手）

### トラックリスト取込み

ゲームごとにサントラの個別曲を取込み、曲単位での視聴・発見を可能にする。  
`tracks` テーブルはすでに複数件対応の設計になっているため、スキーマ変更は不要。  
betaは「フルOST動画1本」で運用し、V2でトラックレベルに詳細化する。

**データソース候補（優先度順）:**

| ソース | 取得できるもの | 備考 |
|---|---|---|
| **YouTube 公式OSTプレイリスト** | 曲名 + VideoID | 公式チャンネルのプレイリストを検索→各動画がトラック。100件/日クォータ内に収まる見込み |
| **Last.fm `album.getInfo`** | 曲名一覧（VideoIDなし） | アルバム検索で取得した曲リストをDB登録→VideoIDはYouTube側で補完 |
| **Bandcamp** | 曲名 + 30秒プレビューURL | 多くのインディーOSTが公開。公式APIなし（スクレイピング必要、利用規約要確認） |
| **IGDB（Twitch API）** | 部分的なサントラ情報 | カバレッジ限定的、補助ソースとして活用 |

**Last.fm を使う実装イメージ:**
1. `album.search` で既存の `search_album()` ロジックを流用してアルバムを特定
2. `album.getInfo` でトラックリスト（`tracks.track[]`）を取得
3. 各トラックを `tracks` テーブルに INSERT（`youtube_video_id = null` で登録）
4. YouTube バッチ（既存の `import_youtube_video_ids.py`）が VideoID を順次補完

**V2 実装タスク（未着手）:**
- [ ] `import_track_listings.py` 新規作成（Last.fm `album.getInfo` → tracks 登録）
- [ ] YouTube VideoID バッチを「トラック名 + ゲーム名」で検索するよう拡張
- [ ] ゲーム詳細ページのプレーヤーをトラック選択 UI に対応（複数 VideoID）
- [ ] 曲名での検索（`GET /search/tracks?q=`）エンドポイント追加（将来）

---

### ラジオモード（グローバルプレーヤー）

ページをまたいで音楽を再生し続けるグローバルプレーヤー。  
App Router の Server Components と共存するには Zustand または React Context でクライアント側のグローバル状態を管理する必要があるため V2 に延期。  
V1 の YouTube 埋め込みは個別ゲームページのみで再生が完結する設計とする。

**V2 実装タスク（未着手）:**
- [ ] Zustand ストアでプレーヤー状態管理（現在再生中トラック・プレイリスト・再生位置）
- [ ] レイアウト内にグローバルプレーヤーバー（`web/app/layout.tsx` に追加）
- [ ] ページ遷移後も再生継続するための hydration 設計

---

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
