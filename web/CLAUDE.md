@AGENTS.md

# web — Next.js フロントエンド

ゲーム音楽発見サービスのフロントエンド（Next.js 16 + React 19 + TypeScript、Vercel / `hnd1`）。
バックエンドは `../api`（FastAPI）、DB は Supabase。全体像は `../README.md`。

## コマンド（このディレクトリで実行）

```bash
npm run dev            # http://localhost:3000
npm run lint           # ESLint
npx tsc --noEmit       # 型チェック（CI で実行される）
npm run build
node ../scripts/check-i18n.mjs            # ハードコード日本語文字列の検出（CI）
node ../scripts/check-i18n.mjs --update   # i18n-violations.json を更新（既知違反の記録）
```

CI（`../.github/workflows/ci.yml`）は eslint → tsc → build の順。

## 環境変数

- `NEXT_PUBLIC_API_URL`: FastAPI のベース URL（`.env.local` に設定。`app/lib/api.ts` が参照）
- `NEXT_PUBLIC_SENTRY_DSN` / `SENTRY_DSN`: Sentry

## ルール・注意点

- **i18n ラチェット方式**: `aria-label` / `placeholder` / `title` / `alt` / `confirm()` / `setError()` などに日本語を直書きしない。新規違反が増えると CI が落ちる。既存の違反は `i18n-violations.json` に記録済みで、直したらスナップショットから減らしていく。
- ブランチ: `feature/*` → `develop` → `main`。`main` への PR は `develop` からのみ（`enforce-branch-flow.yml` が強制）。
- 構成: `app/`（App Router。`games` / `composers` / `tags` / `library` ほか）、`app/components/`、`app/lib/`（`api.ts` 等）。
- 設計判断の経緯は `../docs/planning/`（`02_design_decisions.md` ほか）。
