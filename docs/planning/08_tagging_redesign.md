# 08 タグ付与の仕組み 再設計案

> 調査日: 2026-08-19
> 対象: issue #84（タグ付与率）・#14（タグソース拡張）
> 本ドキュメントは**検討用**。「評価」「コメント」列はユーザーが記入する。

---

## 0. 結論（先に3行）

1. **タグ付与率は 6.2%（21/337件）** — issue #84 記載の 7.3% よりさらに悪化している。母数が増えた分だけ未タグが増え続けている。
2. **原因はチューニング不足ではなく、参照ソースの選択ミス**。Last.fm はこのカタログ（インディー中心）を収録しておらず、`import_description_tags.py` が読んでいる `games.description` は**音楽の説明ではなくゲームプレイの宣伝文**だった。
3. **未活用の有効ソースが手元にある**。Steam OST ストアページの説明文（音楽そのものの記述）と Steam ユーザータグ（雰囲気、全ゲームで取得可能）。実測でカバレッジ 6% → **98%** が見込める。

---

## 1. コンセプトとの照合

企画ドキュメント（01/04）で定義されたコアバリュー:

> ジャンルや評価では伝わらない**ゲームの雰囲気**を、**音楽の好み**という軸で探せる

これを支える機構は `VibeTag Jaccard 係数`（`api/app/services/similarity.py`）ただ一つ。
つまり **game_tags が空 = サービスのコア機能が存在しない** に等しい。

| コンセプト要素 | 実現状況 | 根拠 |
|---|---|---|
| 音楽の雰囲気でゲームを探す | ❌ ほぼ未実現 | タグ付き 21/337 件（6.2%） |
| なぜ似ているかを説明できる | ⚠️ 仕組みはあるが対象がない | `reason_tags` 実装済みだが発火対象が少ない |
| 作曲家つながりでの発見 | ❌ 未実現 | `composer_similarities` **0 件** |
| 試聴して確かめる | ⚠️ 動画IDはあるが精度に問題 | 後述 §5 の別バグ |

---

## 2. 実測した現状（2026-08-19 本番DB）

| 指標 | 実測値 | issue #84 時点 |
|---|---|---|
| ゲーム総数 | 337 | 233 |
| **タグ付きゲーム** | **21（6.2%）** | 17（7.3%） |
| `tags_locked = TRUE` | 313（92.9%） | 213 |
| game_tags 行数 | 46（`system` 45 / `description` 1） | — |
| 1ゲームあたり平均タグ数 | 2.2 | — |
| `description` あり | **337（100%）** | — |
| `steam_app_id` あり | **337（100%）** | — |
| `youtube_video_id` あり | 305（90.5%） | — |
| `steam_ost_appid` あり | 117（34.7%） | — |
| トラックを持つゲーム | 49（14.5%） | — |
| `composer_similarities` | **0 件** | 0 |

日次バッチは毎日 40件 + 100件を処理しているが、**付与実績は description 経由で通算 1 件**。バッチは動いているが成果が出ていない状態。

---

## 3. 原因分析（3つ、すべて構造的な問題）

### 3-A. Last.fm はこのカタログに対して不適切なソース

新規ゲーム取り込みは Steam の OST DLC / タグ検索が起点（`import_steam_soundtracks.py` / `import_steam_tag_search.py`）。結果としてカタログはインディー中心になる。一方 Last.fm はインディーゲームの OST をほぼ収録していない。

**93% の失敗は照合ロジックのバグではなく、ソースとカタログのミスマッチ。** クエリ拡張や KEYWORD_MAP 拡充を続けても頭打ちになる（PR #64/#66 で実施済み、改善せず）。

### 3-B. `import_description_tags.py` は音楽を含まないテキストを読んでいる ← 最重要

`games.description` に入っているのは Steam の `short_description`、つまりゲームプレイの宣伝文。実データ:

```
Dead Cells   → "Dead Cells is a roguelite, metroidvania inspired, action-platformer..."
Spider-Man   → "the worlds of Peter Parker and Spider-Man collide in an original action-packed story..."
NEKOPARA     → "Business is booming for La Soleil, the patisserie run by Kashou Minaduki..."
```

**音楽への言及が一切ない。** 212件試行して1件しか付かなかったのは正常な結果であって、パターンが厳しすぎたからではない。

> ⚠️ issue #84 の修正方針「contextual パターンを緩和、anchor 語の window を広げる」は**逆効果**。
> 音楽の記述がないテキストで閾値を下げれば、ノイズだけが増える。この方針は撤回を推奨する。

### 3-C. `tags_locked` が「Last.fm 失敗」と「タグ付与不能」を混同している

`tags_locked` は本来 Last.fm 専用の失敗フラグだが、実質「タグ付けをあきらめたゲーム」の意味で使われている。313件がこのフラグでゲートされており、**新しいソースを追加してもこの設計のままでは同じ壁にぶつかる**。

既存の `steam_ost_locked` / `youtube_locked` はソース別に分かれている。タグも同じ粒度に揃えるべき。

---

## 4. 検証した候補ソース（すべて実 API を叩いて確認済み）

| ソース | カバレッジ | 信号の質 | 判定 |
|---|---|---|---|
| **Steam OST ストアページ説明文**（`type=music`） | 117件（拡大可） | ★★★ 音楽そのものの記述 | ◎ 採用 |
| **Steam ユーザータグ**（ストアページ） | **337件（100%）** | ★★ 雰囲気。音楽の直接証拠ではない | ◎ 採用（低 confidence） |
| YouTube OST 動画メタデータ | 305件だが約半数が誤動画 | ★★ 検証ゲート必須 | ○ 条件付き採用 |
| Last.fm album.getTopTags | 現状 21件 | ★★★ | ○ 現状維持 |
| トラック名（3,983行 / 49ゲーム） | 14.5% | ★ 汎用名詞が多い | △ 優先度低 |
| Steam `appdetails` の genres/categories | 100% | ✗ 音楽と無関係 | ✗ 不採用 |

### 4-A. Steam OST ストアページ説明文 — 最も質が高い

`import_steam_ost_data.py` は **すでにこのページを取得している**（scrape フェーズでトラックリストと作曲家を抽出）が、**説明文を捨てている**。実データ:

```
Chicory OST  → "an eclectic range of music from intimate piano, to chamber grooves
                and electronic bombast"          → acoustic, electronic
Our Life OST → "The relaxing tunes ... 20 tracks ... instrumental background songs"
                                                 → relaxing, instrumental
Dead Cells   → "songs with guitar, and songs without ... subtle epic music"
                                                 → epic, metal
```

既存の `import_description_tags.py` の正規表現パターンは**そのまま流用できる**（あれが想定していた種類のテキストが、こちらには実際に存在する）。追加の外部依存もゼロ。

### 4-B. Steam ユーザータグ — 唯一 100% をカバーできる手段

全 337 ゲームが `steam_app_id` を持つため、必ず取得できる。ただし**ゲームの雰囲気であって音楽の証拠ではない**ため、マッピングの設計が精度を左右する。

45件の locked ゲームで2種類のマッピングを実測比較した:

| マッピング方針 | カバレッジ | 平均タグ数 | 懸念 |
|---|---|---|---|
| 広い版（`RPG→orchestral`、`Pixel Graphics→chiptune` 等を含む） | 100% | 3.4 | ゲームジャンルからの**決めつけ**。RPGが全部 orchestral になり Jaccard が無意味化する |
| **保守版**（雰囲気語のみ。ジャンル推測を排除） | **98%（44/45）** | **2.2** | 実用的。現状の Last.fm タグと同じタグ密度 |

保守版の実例（`Relaxing/Cozy→relaxing`、`Atmospheric→ambient`、`Psychological Horror→dark`、`Emotional→melancholic` 等、上位15タグのみ使用）:

```
Chicory: A Colorful Tale       → relaxing, melancholic, upbeat
Virtual Cottage                → ambient, relaxing, electronic, upbeat
Dead Cells                     → ambient, dark
Slay the Princess              → dark
Path of Achra                  → dark, folk
Marvel's Spider-Man Remastered → （なし）※スーパーヒーロー系は雰囲気語が付かない
```

**採用するなら「ジャンル→音楽」の推測ルールは入れないこと。** 短期のカバレッジは上がるが、「なぜ似ているか説明できる」というコンセプトの根幹を壊す。

---

## 5. 調査中に見つかった別の問題 → issue #105 として起票済み

**`games.youtube_video_id` の 31% が OST と無関係な動画。** 全310件を `videos.list` で検証した実測:

| 分類 | 件数 | 割合 |
|---|---|---|
| A: 実況・攻略・レビュー | 9 | 2.9% |
| B: トレーラー | 15 | 4.8% |
| C: 音楽の根拠なし（無関係の可能性） | 58 | 18.7% |
| D: 音楽だが尺が短すぎる（単曲・クリップ） | 14 | 4.5% |
| E: OK（OST語 or `- Topic` チャンネル） | 169 | 54.5% |
| F: 弱OK（音楽カテゴリだがOST語なし） | 45 | 14.5% |

→ **要対応 96 / 310 件（31.0%）**

例: AQUARIUM →「12 Hours of Aquarium Relax Music」/ CATO: Buttered Cat → Nintendo の Launch Trailer /
Travellin Cats in Bali → 個人の旅行 vlog（16秒）/ 100 Ninja Cats → 別ゲーム「The Battle Cats」

原因は `import_youtube_video_ids.py` の `run_games` にあり、`maxResults: 1` で検索1位を無条件採用、
`_title_matches()` が非ASCIIタイトルを `return True` で素通しし、動画が音楽かどうかを一切見ていない。

**正常判定(E)の最小尺は 92秒（90秒未満は0件）** のため、90秒の下限は正常な OST を誤除外しない。
対策案とプロトタイプ検証結果は issue #105 に記載。

## 6. 提案する設計

### 6-A. 単一ソース → 証拠の強さで階層化する

`confidence` を「証拠の強さ」として意味付けし直し、フォールバックではなく**積み上げ**にする。

| Tier | ソース | confidence | added_by | 想定カバレッジ |
|---|---|---|---|---|
| 1 | Steam OST ページ説明文 | 0.9 | `steam_ost_desc` | 35%（OST発見数に比例して伸びる） |
| 1 | Last.fm album tags | 0.9 | `system`（現状維持） | 6% |
| 1 | YouTube OST メタデータ（検証ゲート付き） | 0.8 | `youtube` | 検証を通ったもののみ |
| 2 | Steam ユーザータグ（保守マッピング） | 0.4 | `steam_tags` | **98%** |

Tier 2 は「Tier 1 が取れなかったときの下地」。Tier 1 が後から取れたら上書きではなく**共存**させ、confidence で差を付ける。

### 6-B. `confidence` を実際に使う（必須の付随変更）

現在 `compute_similarity_score()` は `confidence` を**完全に無視**して生のタグ集合で Jaccard を計算している。
このまま Tier 2 タグを流し込むと、確信度 0.4 の推測タグが 0.9 の実測タグと同じ重みになり、**類似度の質が下がる**。

重み付き Jaccard（例: `Σ min(conf_a, conf_b) / Σ max(conf_a, conf_b)`）への変更をセットで行う必要がある。

同様に `reason_tags`（フィードの推薦理由表示）も、Tier 2 タグを根拠として出すと説明の説得力が落ちる。**表示は Tier 1 優先**にする。

### 6-C. `tags_locked` をソース別に分解する

既存の `steam_ost_locked` / `youtube_locked` と同じ粒度に揃える。最小の変更:

- `tags_locked` は **Last.fm 専用フラグ**として意味を確定（コメント修正のみ、データ移行不要）
- 新スクリプトは `tags_locked` を参照せず、`game_tags.added_by` に自分のソース名の行があるかで処理済み判定する（→ **§12 で撤回**。タグが付かなかったゲームを判定できず日次バッチが空回りしたため、`game_tag_attempts` に置き換えた）
- `games.steam_tags_scraped_at TIMESTAMPTZ` を追加（Steam タグの再取得管理用）

---

## 7. 実施順序の提案

「1機能を完成させてから次へ」（開発方針）に沿って1つずつ。

| # | 作業 | 効果 | 規模 | 状態 | 評価 | コメント |
|---|---|---|---|---|---|---|
| 1 | `import_description_tags.py` を**日次バッチから外す** | 無駄な100件/日の処理を停止 | 5分 | ✅ 完了（スクリプトごと削除） | | |
| 2 | `import_steam_tags.py` 新規作成（Tier 2・保守マッピング） | **6% → 98%** | 半日 | ⛔ **保留**（§8 Q3=B により。詳細は §10） | | |
| 3 | 重み付き Jaccard へ変更（6-B） | Tier 2 投入による品質劣化を防ぐ | 2時間 | ✅ 完了 | | |
| 4 | `import_steam_ost_data.py` に説明文タグ抽出を追加（Tier 1） | 高品質タグ 35%（既存正規表現を流用） | 2時間 | ✅ 完了（`--phase tags`） | | |
| 5 | YouTube 誤動画の検証ゲート（§5、別 issue） | ユーザーに見えている品質問題の解消 | 半日 | 未着手 | | |
| 6 | YouTube メタデータからのタグ抽出（Tier 1） | 5 の副産物として実装可能 | 2時間 | 未着手 | | |
| 7 | `composer_similarities` 0件問題（#85） | 作曲家軸の発見が機能する | 別途調査 | 未着手 | | |

> #2 と #3 はセットで実施すること（#2 単独だと類似度の質が落ちる）。
> #3 は #2 に先立って実装済みで、Tier 2 が入っていない現状でも従来と同じ結果になる（§6-B）。

---

## 8. 未解決の議論ポイント

| # | 論点 | 選択肢 | 回答欄 |
|---|---|---|---|
| 1 | Steam ユーザータグ（推測ベース・conf 0.4）をコアの類似度計算に混ぜてよいか。「音楽で探す」サービスとして許容できるか | A: 混ぜる（カバレッジ優先） / B: 類似度には使わず一覧の絞り込みだけに使う / C: 使わない | A |
| 2 | Tier 2 タグを UI 上で区別表示するか（例: 薄色・「推定」バッジ） | A: 区別する / B: 区別しない | A | 
| 3 | Steam ストアページのスクレイピング頻度・規約上の許容範囲。既存 `import_steam_tag_search.py` と同等の扱いでよいか | A: 同等でよい / B: 公式API移行（#33）とセットで検討 | B |
| 4 | `import_description_tags.py` は削除するか、OST 説明文用に転用するか | A: OST 用に転用（パターンを流用） / B: 残して停止 / C: 削除 | C |
| 5 | 将来 LLM が使えるようになった場合、入力に使うテキストは OST 説明文でよいか（#14/#16 の Claude API 案は課金の都合で断念済み。ただし §4-A のテキストが得られた今、LLM なしでも当初の狙いの大半は達成できる） | | 検討見送り(レビューが良い可能性もあるため) |
| 6 | Bandcamp（#14 のメイン候補）は Steam OST 説明文で代替できたとみなして優先度を下げてよいか | A: 下げる / B: 維持 | A |

---

## 9. 補足: 検証に使ったコマンド

すべて本番DB・実 API に対して実行。再現用に記録する。

- タグ付与率: `GET /rest/v1/game_tags?select=game_id,added_by` → distinct game_id
- Steam ユーザータグ: `GET store.steampowered.com/app/{appid}/?l=english` → `class="app_tag"` を正規表現抽出
- Steam OST 説明文: `GET store.steampowered.com/api/appdetails?appids={ost_appid}` → `data.detailed_description`
- YouTube メタデータ: `GET youtube/v3/videos?part=snippet,topicDetails&id=...`（50件バッチ・1ユニット/回、クォータ影響は無視できる）

---

## 10. 実装結果と、保留になった項目（2026-08-19）

### 10-A. 実装したもの

| 変更 | 内容 |
|---|---|
| `scripts/music_text_tags.py`（新規） | 音楽テキストから mood タグを抽出する共有ロジック。`import_description_tags.py` のパターンを移植し、`music_context=True` モードを追加 |
| `scripts/import_steam_ost_data.py` | `--phase tags` を追加。appdetails API から OST 説明文を取得してタグ抽出（`added_by='steam_ost_desc'`, `confidence=0.9`） |
| `scripts/import_description_tags.py` | **削除**（§8 Q4=C）。読んでいたテキストに音楽情報がなく、212件で1件しか付与できていなかった |
| `.github/workflows/daily-import.yml` | Step 1b（説明文タグ）を廃止し、Step 5b（OST 説明文タグ・50件/日）を discover の直後に追加。手動実行ジョブ `ost_tags` も追加 |
| `api/app/services/similarity.py` | 重み付き Jaccard に変更（§6-B）。`set` / `{tag_id: confidence}` の両方を受け取り、全 confidence が 1.0 なら従来と完全に同じ結果 |
| `api/tests/test_similarity.py` | 重み付き Jaccard のテスト 6 件追加（既存 54 件を含め全件パス） |
| `api/app/routers/games.py` | ゲーム詳細レスポンスに `game_tags.confidence` を追加 |
| `web/`（型・詳細ページ・`TagsWithFlagButton`） | confidence < 0.7 のタグを「推定」バッジ＋破線ボーダーで区別表示（§8 Q2=A） |
| `supabase/schema.sql` | `tags_locked` が Last.fm 専用フラグであることを明記。`game_tags.added_by` / `confidence` のコメント追加（§6-C） |

### 10-B. ⛔ 保留: Steam ユーザータグ（§7 #2）

**§8 Q3 の回答が B（公式API移行 #33 とセットで検討）だったため、実装を見送った。**

見送るにあたり、スクレイピングを避けて同じデータを取る方法を調べたが、**存在しなかった**:

| 手段 | 結果 |
|---|---|
| 公式 `appdetails` API | `genres` / `categories` のみ返る（'Adventure' / 'Single-player' 等）。音楽の手がかりにならないことを実測で確認済み（§4 表） |
| SteamSpy API（タグを votecount 付きで返す） | Cloudflare により 403。回避はスクレイピングより筋が悪い |
| ストアページ HTML | ユーザータグを取得できる唯一の手段。ただし #33 が問題視している非公式エンドポイント依存が increases |

なお #33 が具体的に問題視しているのは **`store.steampowered.com/search/results/`（内部 JSON 検索）** であり、
`appdetails` は #33 自身が**移行先候補**として挙げているため、今回実装した `--phase tags` は #33 の懸念には抵触しない。

### 10-C. 保留による影響 — カバレッジ目標に届かない

当初の「6% → 98%」という数字は**全て Tier 2（Steam ユーザータグ）由来**だった。Tier 1 だけでは届かない。

実測に基づく Tier 1 の上限:

| 要素 | 実測値 |
|---|---|
| `steam_ost_appid` を持つゲーム | 117 / 337（34.7%） |
| うち OST 説明文からタグを抽出できた割合 | **49%**（35件サンプル、平均 1.0 タグ） |
| `steam_ost_locked` からの追加発見余地 | 30件サンプル中 3件（10%）のみ。既存の discover はほぼ正しく、伸びしろは小さい |

→ **Tier 1 のみの到達点は 20〜25% 程度**（6% からは大幅改善だが、98% には届かない）。

**実際にバックフィルを実行した結果（2026-08-19）:**

| 指標 | 実行前 | 実行後 |
|---|---|---|
| タグ付きゲーム | 21 / 337（6.2%） | **75 / 337（22.3%）** |
| game_tags 行数 | 46 | 154 |
| うち `steam_ost_desc` | — | 109 行 / 59 ゲーム |

予測（20〜25%）どおりの着地。以後は日次バッチ Step 5b が新規 OST 発見分を自動で拾う。

OST 説明文でタグが取れない理由は、パターン不足ではなく**説明文自体に雰囲気の記述がない**ケースが大半:

```
Pizza Tower : "Featuring more than 3 hours of music, unlooped, no transitions ... It sure is good music."
DELTARUNE   : "Crash! Bang! Boom! It's the music of DELTARUNE!"
100 Ninja Cats: "Soundtrack of 100 Ninja Cats"
```

### 10-D. 判断が必要なこと

| # | 論点 | 選択肢 | 回答欄 |
|---|---|---|---|
| 7 | Tier 2 を諦めて 20〜25% で運用するか、ストアページ取得を許容して 98% を取りに行くか | A: ストアページ取得を許容して #2 を実装（#33 とは別物として扱う） / B: #33 を先に片付けてから #2 / C: 20〜25% で運用し Tier 2 は見送る | |
| 8 | 7 が A/B の場合、取得頻度の上限（既存バッチは 1.2〜1.3 秒間隔） | | |

---

## 11. YouTube 動画メタからのタグ抽出（Tier 1.5、2026-08-19 追加）

### 経緯

ユーザーから「タグなしゲームのうち YouTube 動画が適切に登録されていそうなものの `tags_locked` を外してタグ付与対象に復活させたい」との要望があった。検証の結果、当初の想定とは異なる結論に至った。

### 検証で判明したこと

1. **`tags_locked` は Last.fm 専用ロックであり、Steam OST 説明文パイプライン（Tier 1）には無関係。** 外しても新パイプラインの対象は増えない。
2. **タグなし267件のうち104件は `steam_ost_appid` を既に持っており、アクション不要で次回日次バッチの対象。**
3. **残り214件は全件 `steam_ost_locked=TRUE`（discover 失敗済み）。** 「YouTube動画が妥当そう」で絞った10件で `steam_ost_locked` を外して discover を再実行したが **0/10 で完全に空振り**。既存の discover は既に正確で、これらのゲームの多くはそもそも Steam に OST DLC が存在しない（Bandcamp/YouTube のみで配布）。
4. **代替として YouTube 動画のタイトル＋説明文から直接タグ抽出することが有効と判明。** ただし動画自体が誤登録（issue #105）だと無意味なタグが混入するため、動画の妥当性検証とセットでなければ危険。実際 AQUARIUM（無関係な12時間の作業用BGM動画が誤登録されている実例）は素朴な判定では通ってしまった。

### 実装したもの

- `scripts/youtube_video_validation.py`（新規）: issue #105 で使った動画妥当性判定を共有モジュール化。ゲーム名一致・尺90秒〜3時間（3時間上限は AQUARIUM のような作業用BGMミックスを弾くために今回追加）・実況/トレーラー除外・音楽の根拠（categoryId/topic/`-Topic`チャンネル/OST語）を判定する。
- `import_youtube_video_ids.py --mode tags`（新規）: `games.youtube_video_id` が設定済みのゲームを対象に、`videos.list`（50件/リクエスト=1 unit）でメタ取得し、上記の検証を通った動画のみタイトル＋説明文から `music_text_tags.extract_tags(music_context=True)` でタグ抽出。`added_by='youtube_desc'`, `confidence=0.75`（Steam OST 説明文の 0.9 より低め。動画の誤登録を完全には排除できないため）。
- 日次バッチ Step 3c（50件/日）・手動ジョブ `youtube_tags` を追加。

### 実測結果

「タグなし・OST appidなし・YouTube動画あり」191件のうち:
- 動画妥当性検証を通過: 100件（52%）
- うちタグ抽出成功: 36件（36%）

214件全体に対する見込みは **約40件** のタグ新規付与（追加のカバレッジ改善は 6.2%→22.3% に対してさらに +数%程度）。小サンプル15件で実行し、DB書き込みを確認済み。

---

## 12. 処理済み判定を `game_tag_attempts` に置き換え（2026-08-19）

### 経緯

「日次バッチの説明文タグ付与が毎日同じ対象で走り続けている」との指摘を受けて調査した。

### 判明したこと

**(1) 本番（main）で旧ステップが動き続けていた。**
スケジュール実行が参照するのは `main` の workflow。`main` には §10 で廃止したはずの
`Step 1b — 説明文タグ付与（100件）` → `scripts/import_description_tags.py` が残っており、
`develop` の刷新分が `main` に届いていなかった。Actions のログ 3 日分（16時間前 / 1日前 / 4日前）で
処理対象 100 件が完全に一致し、いずれも「完了: 0 ゲームに計 0 タグ追加」。

**(2) 後継スクリプトも同じ構造欠陥を持っていた。**
§6-C で決めた「`game_tags.added_by` に自分のソース名の行があるか」で処理済みを判定する方式は、
**タグが 1 件も付かなかったゲームを「未処理」と見なし続ける**。ソート順が `created_at` 昇順のため、
そうしたゲームがキュー先頭を恒久的に占有し、日次バッチが毎日同じ説明文を取り直す。

実測（2026-08-19 本番DB）:

| ステップ | 候補 | 付与済 | 毎日再処理される滞留分 | 到達不能になるゲーム |
|---|---|---|---|---|
| Step 5b（`steam_ost_desc`） | 117 | 59 | 58 | `--limit 50` 超過分の 8 件 |
| Step 3c（`youtube_desc`） | 310 | 4 | 306 | 候補取得が `limit*3=150` 件打ち切りのため 151 件目以降すべて |

### 実装したもの

- `supabase/schema.sql`: `game_tag_attempts (game_id, source, result, detail, attempted_at)` を追加。
  `result` は `tagged` / `no_match` / `invalid` / `error`。前 3 つは恒久スキップ、`error`（通信・API 失敗）のみ
  `RETRY_ERROR_AFTER_DAYS`（既定 7 日）後に再試行する。バッチ専用のため RLS は有効・公開ポリシーなし。
- `scripts/tag_attempts.py`（新規）: `load_skip_ids()` / `record()` / `paged()`。
  `load_skip_ids()` は移行用に「既存の `game_tags.added_by` 行があるゲーム」もスキップ扱いにするので、
  過去に成功済みのゲームを叩き直すことはなく、データ移行は不要。
- `import_steam_ost_data.py --phase tags`: 失敗理由を `_FetchFailure(result, detail)` で持ち上げ、
  appdetails の `success=false` は `invalid`（再試行しても変わらない）、通信・HTTP・JSON 失敗は `error` に分類。
- `import_youtube_video_ids.py --mode tags`: `_fetch_videos_meta()` が「リクエスト自体が失敗した videoId」を
  別に返すようにし、**200 応答に含まれなかった動画（削除・非公開）＝ `invalid`** と
  **`videos.list` の失敗＝`error`** を区別。候補取得の `limit*3` 打ち切りは全件取得に変更。
- 併せて、処理済み集合の取得を `paged()` 経由にして PostgREST の 1 リクエスト上限（既定 1000 行）超えに対応。
- `scripts/test_tag_attempts.py`（新規、標準ライブラリのみ）＋ CI の scripts ジョブに追加。

### 日次ステップの全数監査

「タグ2ステップを直して本当に空回りは無くなるのか」を確認するため、Actions ログ（16時間前 / 4日前）で
全ステップの処理対象を突き合わせた。結果、**同じ構造欠陥がさらに2つ**見つかった。

| ステップ | 判定 | 根拠 |
|---|---|---|
| Step 1b 説明文タグ | 解消 | main が PR #108 でリリース済み。ステップもスクリプトも削除された |
| Step 2 説明文バックフィル | 正常 | 対象30件が毎日入れ替わる |
| Step 3 YouTube 動画（ゲーム） | 正常 | 失敗時に `youtube_locked` を立てる |
| **Step 3b トラック別 YouTube** | **空回り** | 10件中9件が4日前と同一 |
| Step 3c / 5b タグ抽出 | 修正済 | 本節の対応 |
| Step 4 / 4b 新規ゲーム追加 | 正常 | 毎日別のゲーム |
| Step 5 OST discover | 正常 | 共通対象0件 |
| Step 6 OST スクレイプ | 正常 | `steam_ost_scraped_at` で前進 |
| **Step 8 Last.fm 類似度** | **空回り** | 出力が完全一致「0 件保存, 17 件スキップ」 |

### Step 3b — トラック別 YouTube（1,000 units/日を空費）

`tracks` には `games.youtube_locked` に相当する列が無く、`youtube_video_id IS NULL` だけで
対象を選んでいた。検索が当たらなかったトラックは NULL のまま `created_at` 昇順の先頭に居座る。

実測: tracks 3,983 件中 video_id ありは 151 件。検索対象 3,796 件に対し日次 10 件（1,000 units）で、
成功実績は 1/10 件・0/10 件。事実上消化されない。

対応: `tracks.youtube_locked BOOLEAN NOT NULL DEFAULT FALSE` を追加し、`games` モードと同じく
見つからなかったトラックをロックする。

### Step 8 — Last.fm 類似度（突合は機能していたが、キューが進んでいなかった）

`composer_similarities` は 0 行、`--limit 30` の対象が毎日同一だった。原因は2つ。

1. **記録が無い。** 保存できたときしか行が増えないので「Last.fm にデータが無い作曲家」は
   永久に未処理のまま先頭に残る。実際その先頭30人がほぼ全員データなしだった。
2. **応答の9割を捨てていた。** `composer_similarities` は両端とも自前 composers のペアしか
   持てないため、突合できなかった類似アーティスト名はその場で破棄され、後から作曲家が
   増えても Last.fm を叩き直さない限り拾えなかった。

140人全員に問い合わせた実測では、96人に類似データがあり、延べ947件のうち **38人分が自前
composers と突合可能**だった。つまり実装は動くのに、キューが先頭で詰まって到達していなかった。

対応:

- `composers.lastfm_similar_fetched_at TIMESTAMPTZ` を追加。結果の有無に関わらず記録し、
  NULL の作曲家だけを対象にする。
- `composer_similar_artists (composer_id, similar_name, score, fetched_at)` を追加し、
  Last.fm の応答を名前のままキャッシュする。
- 毎回キャッシュ全体を現在の composers と突合し直す（API リクエストは発生しない）ので、
  新しい作曲家が追加されたときに過去の応答から自動的にペアが増える。
- 突合ロジックは `scripts/composer_matching.py` に純粋関数として切り出し、CI でテストする。

適用後の実測: 140人すべて取得済み、類似アーティスト 947 件をキャッシュ、
`composer_similarities` に **52 ペア**（従来 0）。2回目以降の実行は Last.fm を一切叩かない。

### 残作業

`develop` → `main` のリリースまで、日次バッチの実際の挙動は変わらない。
