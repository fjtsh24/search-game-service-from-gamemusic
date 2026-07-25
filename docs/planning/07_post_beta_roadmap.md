# 07 ベータ後ロードマップ

> 策定: 2026-07-22  
> ベータリリース（2026-07-21）完了後の開発・拡張計画。

---

## 現状サマリー（2026-07-25）

| 項目 | 状態 |
|---|---|
| M1〜M4 + ベータリリース | ✅ 完了 |
| 日次バッチ（GitHub Actions） | ✅ 稼働中（JST 05:18、Step 1b まで拡充・計9ステップ） |
| 登録ゲーム数 | ~200件以上（毎日~7件追加中） |
| Last.fm タグ付与 | ⚠️ カバレッジ改善中（アルバム検索拡張・KEYWORD_MAP 拡充済み） |
| 説明文タグ付与 | ✅ 実装済み（PR #71）。tags_locked ゲームを対象に日次 100 件処理 |
| タグ申告システム | ✅ 実装済み（PR #71）。game_tag_flags テーブル＋日次ログ＋UI フラグボタン |
| steam_ost_locked フラグ | ✅ 実装済み（PR #65）。discover 失敗ゲームをスキップする仕組み完備 |
| YouTube 動画 | ✅ `games.youtube_video_id` に移管済み |
| is_discoverable 自動更新 | ✅ DB トリガー実装済み（game_tags / youtube_video_id 両対応） |
| フィード推薦理由表示 | ✅ reason_tags フィールド追加・カード下にタグ表示（PR #68） |
| トラックリスト | ⚠️ Steam OST スクレイプ稼働中（~40% のゲームでデータ取得済み） |
| トラックリスト UI | ✅ YouTube プレーヤー横にリスト表示（PR #40） |
| 作曲家類似度更新 | ✅ 日次パイプライン Step 8 に組み込み済み（PR #60） |
| スキーマ管理 | ✅ schema.sql 一元管理（migrations 廃止、実 DB と照合済み） |
| 依存パッケージ | ✅ 主要パッケージ最新版に更新済み（2026-07-24） |
| ユーザー数 | 少数（趣味PJT規模） |

## 2026-07-23 リリース内容

| 変更 | 詳細 | Issue/PR |
|---|---|---|
| ✅ Vercel Analytics 組み込み | `@vercel/analytics` 追加、`layout.tsx` に `<Analytics />` 配置 | #27 / PR#28 |
| ✅ is_discoverable DBトリガー | タグ・動画の削除時も自動でFALSEに戻るよう migration 011 追加 | #26 / PR#31 |
| ✅ バッチスクリプト品質改善 | 全スクリプトに User-Agent 統一（Session化）、`lastfm_similarities.py` HTTP エラー処理追加 | PR#32 |
| ✅ YouTube誤動画修正 | 星空列車与白の旅行 の動画を正しいOP動画（MEJC0FsCido）に差し替え | 手動対応 |
| ❌ Claude AIタグ付与 | 実装済みだが Claude API 課金登録困難のため断念・取り下げ | #29/#16 closed |

---

## 2026-07-24 リリース内容

| 変更 | 詳細 | PR |
|---|---|---|
| ✅ YouTube 動画 games テーブル移管 | `games.youtube_video_id` / `games.youtube_flagged` 追加。OST全体とトラック別を概念分離 | PR#40 |
| ✅ トラックリスト UI | ゲーム詳細ページにプレーヤー横並びリスト表示。「似たゲーム」への視認性を改善 | PR#40 |
| ✅ スキーマ一元管理 | `supabase/schema.sql` へ移行（migrations 廃止）。実 DB と psql 照合済み | PR#40 |
| ✅ daily-import バグ修正 | `--phase` エラー・`youtube_flagged` 誤参照・キャッシュ URL too long を修正 | PR#60 |
| ✅ lastfm_similarities 日次化 | 毎日30件・未登録作曲家優先。`--limit` 引数追加 | PR#60 |
| ✅ 依存パッケージ更新 | next 16.2.11、react 19.2.8、@types/node ^26、pytest 9、Actions v7 等 | PR#58/59 |

---

## 2026-07-25 リリース内容

| 変更 | 詳細 | PR |
|---|---|---|
| ✅ daily-import バグ修正・タグ精度改善 | Steam OST appid 取得漏れ・discover 偏り・import_game_tags 精度改善 | PR#64 |
| ✅ KEYWORD_MAP 拡充 | rock/trance/post-rock 等の不足ジャンルキーワードを追加 | PR#66 |
| ✅ steam_ost_locked フラグ | OST 発見失敗ゲームを discover フェーズからスキップする仕組み | PR#65 |
| ✅ フィード推薦理由タグ表示 | `reason_tags`（寄与タグ上位2件）をフィードカード下に表示。ユニットテスト7件追加 | PR#68 |
| ✅ 説明文タグ付与 | `import_description_tags.py` 新規作成。保守的 2 段階マッチングで music-explicit フレーズのみ抽出 | PR#71 |
| ✅ タグ申告システム | `game_tag_flags` テーブル・`POST /games/{id}/flag-tag` API・ゲーム詳細 UI フラグボタン | PR#71 |

---

## 即時対応（コード変更不要）

設定だけで完了する項目。早めに対応する。

| 内容 | 方法 | Issue |
|---|---|---|
| GitHub Secret Scanning 有効化 | Settings → Security → Secret scanning → Enable | #19 |
| UptimeRobot 設定（死活監視） | https://uptimerobot.com で `/health` を登録 | #20 |

---

## 開発方針

**データを育てる → 探索体験を育てる → UXを育てる** の順番で進める。

- 外部APIへの依存・負荷を最小化（既存APIを最大活用）
- 1人開発のため、1機能を完成させてから次へ進む
- ゲーム数・タグデータが充実するほどレコメンド精度が上がる設計を意識する

---

## Phase 1: データ品質向上（最優先）

タグ・トラックデータが薄いと探索体験全体の質が低い。まずここを解決する。

### 1-A: タグ付与ソース拡張 ✅ 一部完了（PR #71）

**対応済み**:
- [x] Steam `description` フィールドからの音楽キーワード抽出（`import_description_tags.py`）
  - `tags_locked=TRUE` ゲームのみ対象（Last.fm 失敗済み）
  - 2 段階マッチング: ①音楽的複合フレーズ直接マッチ、②スタイルキーワード + 音楽アンカー語前後 80 文字
  - `confidence=0.5`、`added_by='description'`（Last.fm タグと区別可能）
  - 日次バッチ Step 1b（100 件/日）に組み込み済み

**残存タスク（→ issue #14）**:
- [ ] Bandcamp 対応: 利用規約確認後に判断（スクレイピング可否が不明）

---

### 1-B: トラックリスト＋作曲家データ取込み（→ issue #15, #21）

**目的**: 多くのゲームで曲名・尺・作曲家が未入力。`composers` テーブルにもデータがほぼない。トラックリストと作曲家を同一APIアクセスでまとめて取得する。

**仕組み**: Last.fm `album.getInfo` でトラックリストと `artist`（作曲家名）を取得し、`tracks` / `composers` / `track_composers` テーブルに登録。

```
Last.fm album.getInfo
  → 曲名一覧・尺（duration）・artist 名
  → tracks テーブルに INSERT（youtube_video_id=null）
  → composers テーブルに upsert（lastfm_name で同定）
  → track_composers テーブルに INSERT
  → 既存バッチが YouTube VideoID を順次補完
```

**実装タスク**:
- [ ] `import_track_listings.py` 新規作成（Last.fm album.getInfo、composer 登録含む）
- [ ] YouTube VideoID バッチを「トラック名＋ゲーム名」検索に対応
- [ ] ゲーム詳細ページにトラックリストセクション追加
- [ ] composer データ充実後に `import_lastfm_similarities.py` を再実行

---

### 1-C: タグ付与ソース拡張 Bandcamp（→ issue #14）

**目的**: インディーゲームのサントラ販売に多く使われており、詳細なタグが付いている。

**注意**: 公式APIなし。スクレイピングの利用規約確認が必要。1-A の効果を見てから判断する。

---

## Phase 2: レコメンド深化

Phase 1でゲームのタグデータが充実してから着手する。

### 2-A: AIユーザー好みプロファイリング（→ issue #17）

**目的**: 評価済みゲームリストをAIに渡して「音楽的な好み」を言語化し、フィード精度を向上させる。

**仕組み**: 評価を更新したユーザーを対象に1日数件処理。生成したプロファイル（好みのムード・重み）を `users.music_profile` (JSONB) に保存し、フィード生成時の重み付けに活用する。

```
評価4〜5のゲーム一覧（3件以上のユーザー）
  → Claude API: 「このゲームリストから音楽的な好みを分析して」
  → {"preferred_moods": ["orchestral","melancholic"], "weights": {...}}
  → users.music_profile に保存
  → GET /users/me/feed でプロファイル重み付けを使用
```

**前提条件**: Phase 1-A でゲームのタグが十分揃ってから実装する。タグが薄い状態ではAIの分析精度も低い。

**実装タスク**:
- [ ] migration: `users.music_profile JSONB` カラム追加
- [ ] `import_user_profiles.py` 新規作成
- [ ] `GET /users/me/feed` でプロファイル重み付けを組み込む
- [ ] GitHub Actions daily-enrichment の末尾に追加

---

### 2-B: フィードカードUI改善 ✅ 完了（PR #68）

**実装済み**:
- [x] `GET /users/me/feed` レスポンスに `reason_tags`（スコア寄与タグ上位2件）を追加
- [x] `FeedSection.tsx` でカード下に「エレクトロニック・ダークが好きな人に」を表示

---

### 2-C: 音楽フィンガープリント（ゲーム単位特徴量）

ゲーム全体の「音楽的特徴」を集約したデータ（`03_feature_brainstorm.md` の 3-4）。Phase 1-A のタグ付けが充実した後に、タグの分布・重みをゲームの特徴ベクトルとして構造化する。

**実装タスク**:
- [ ] 設計検討（タグベクトル vs. AIによる直接生成 vs. 両方）

---

## Phase 3: UX・プラットフォーム拡張

機能の深みが出てから手をつける領域。

### 3-A: トラック選択プレーヤー

Phase 1-B でトラックリストが揃ってから実装。ゲーム詳細ページで複数トラックを選択・切り替えて再生できるUI。

**実装タスク**:
- [ ] ゲーム詳細ページのプレーヤーをトラック選択UI対応（複数VideoID）
- [ ] `GET /search/tracks?q=` エンドポイント追加（曲名検索）

---

### 3-B: ラジオモード（グローバルプレーヤー）

ページをまたいで音楽を再生し続けるプレーヤー。App Router の Server Components と共存するには Zustand によるグローバル状態管理が必要。

**実装タスク**:
- [ ] Zustand ストアでプレーヤー状態管理
- [ ] `web/app/layout.tsx` にグローバルプレーヤーバーを追加
- [ ] ページ遷移後も再生継続するための hydration 設計

---

### 3-C: 多言語対応（i18n）

現状は日本語UIのみ。APIはすでに `Accept-Language` 対応済みなのでフロント側の実装が主な作業。

**実装タスク**:
- [ ] `next-intl` 導入・`/ja` `/en` ルート構成
- [ ] UIテキストの翻訳ファイル作成（`messages/ja.json` `messages/en.json`）
- [ ] 言語スイッチャーUI

---

## 運用・インフラ

### 監視（→ issue #20）
- [ ] UptimeRobot: `/health` の死活監視（無料）
- [ ] Sentry: FastAPI / Next.js のエラー捕捉（無料枠）

### アクセス解析
- [x] Vercel Analytics 有効化済み（ページビュー・Core Web Vitals）（→ #27）
- [ ] イベントトラッキング追加（PostHog等）— ゲーム閲覧・タグクリック・YouTube再生（→ issue #22、低優先）

## その他残タスク

| 内容 | 備考 |
|---|---|
| テストカバレッジ向上（現54%） | CI通過が優先、余裕があれば |
| OSS公開（AGPL-3.0） | サービス安定後に検討 |

---

## 保留・スコープ外

| 機能 | 判断 | 理由 |
|---|---|---|
| 類似ユーザー推薦（協調フィルタリング） | 保留 | ユーザー数が少なすぎて収束しない |
| ML機械学習（Matrix Factorization等） | 将来 | データ量が揃うまで効果が出ない |
| Spotify連携 | 保留 | 25ユーザー制限がOSS化・公開と相性悪い |
| Bandcamp スクレイピング | 要確認 | 利用規約確認後に判断（Phase 1-C） |
| VGMdb | 採用見送り | 非公式APIのため（02_design_decisions.md 参照） |
| コミュニティタグ付け | 見送り | タグ申告システム（PR #71）で不正タグをユーザーが報告可能。フルコミュニティ編集はモデレーションコスト > 得られる価値 |
| ユーザーによるゲーム登録 | 見送り | 「Steamの高評価サントラ」という自動フィルタが品質担保になっており、ユーザー登録を入れると崩れる |

---

## フェーズ依存関係まとめ

```
Phase 1-A (説明文タグ付与) ✅
  └→ Phase 2-A (AIユーザープロファイリング) ← タグデータが前提
  └→ Phase 2-C (音楽フィンガープリント)     ← タグデータが前提

Phase 1-B (トラックリスト)
  └→ Phase 3-A (トラック選択プレーヤー)    ← トラックデータが前提

Phase 2-A / 2-B ✅
  └→ Phase 2-C                              ← レコメンド改善が前提

Phase 3-A / 3-B / 3-C は独立して進められる
```

---

## GitHub Issues 対応表

| Issue | Phase | 内容 | 状態 |
|---|---|---|---|
| #14 | 1-C | タグ付与ソース拡張（Bandcamp等） | ⚠️ 一部完了（説明文抽出 PR#71 完了、Bandcamp は利用規約確認待ち） |
| #15 | 1-B | トラックリスト取得・保存・表示 | ⚠️ 進行中（Steam OST スクレイプ実装済み・UI追加済み。トラック別VideoID未実装） |
| #16 | 1-A | YouTubeメタデータ＋AIタグ自動付与 | ❌ Closed（Claude API断念） |
| #17 | 2-A | AIユーザー好みプロファイリング | 🔵 Open（タグデータ充実後） |
| #19 | 即時 | GitHub Secret Scanning + Dependabot 有効化 | ⚠️ 進行中（Dependabot 有効化済み、Secret Scanning 未） |
| #20 | 運用 | システム監視（UptimeRobot + Sentry） | 🔵 Open |
| #21 | 1-B | 作曲家データの取得・保存方法の確立 | ⚠️ 進行中（Steam OST スクレイプで track_composers 蓄積中） |
| #22 | 運用 | イベントトラッキング追加（PostHog等） | 🔵 Open（低優先） |
| #33 | 運用 | Steam store search を公式APIに移行 | 🔵 Open（低優先） |
| #34 | 完了 | lastfm_similarities.py に --limit 追加 | ✅ Closed（PR#60） |
| #62 | UX | Steam ログイン価値・安全性説明の改善 | 🔵 Open |
| #63 | 完了 | steam_ost_locked フラグ実装 | ✅ Closed（PR#65） |
