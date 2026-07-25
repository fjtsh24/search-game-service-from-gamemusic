#!/usr/bin/env node
/**
 * check-i18n.mjs — JSX 属性・confirm() などにハードコードされた CJK 文字列を検出する
 *
 * 検出対象:
 *   - aria-label / placeholder / title / alt 属性の文字列・テンプレートリテラル値
 *   - confirm() / alert() の文字列引数
 *   - setError() / throw new Error() の文字列引数（ユーザーに見えるエラー文）
 *
 * 使い方:
 *   node scripts/check-i18n.mjs              # CI チェック（違反増加で exit 1）
 *   node scripts/check-i18n.mjs --update     # スナップショット更新（既知違反を記録）
 *
 * ラチェット方式: 既知の違反は web/i18n-violations.json に記録し、
 * 新規追加を防ぐ。i18n 対応を進めるたびにスナップショットから減らしていく。
 */

import { readFileSync, writeFileSync, readdirSync } from 'fs'
import { join, relative, dirname } from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)
const ROOT = join(__dirname, '..')
const WEB_APP = join(ROOT, 'web', 'app')
const SNAPSHOT = join(ROOT, 'web', 'i18n-violations.json')

// Hiragana / Katakana / CJK統合漢字 / 全角記号
const CJK = /[぀-鿿＀-￯]/

// 検出するパターン: { name, re } — re のキャプチャ group 1 がチェック対象の文字列値
const CHECKS = [
  { name: 'aria-label (string)',   re: /\baria-label="([^"]+)"/g },
  { name: 'aria-label (template)', re: /\baria-label=\{`([^`]+)`\}/g },
  { name: 'placeholder',          re: /\bplaceholder="([^"]+)"/g },
  { name: 'title attr (string)',   re: /(?<![a-zA-Z\d-])title="([^"]+)"/g },
  { name: 'title attr (template)', re: /(?<![a-zA-Z\d-])title=\{`([^`]+)`\}/g },
  { name: 'alt attr',             re: /\balt="([^"]+)"/g },
  { name: 'confirm()',            re: /\bconfirm\(["'`]([^"'`]+)["'`]\)/g },
  { name: 'alert()',              re: /\balert\(["'`]([^"'`]+)["'`]\)/g },
  { name: 'setError()',           re: /\bsetError\(["'`]([^"'`]+)["'`]\)/g },
  { name: 'throw Error()',        re: /\bnew Error\(["'`]([^"'`]+)["'`]\)/g },
]

function* walkTsx(dir) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name)
    if (entry.isDirectory() && !entry.name.startsWith('.')) {
      yield* walkTsx(full)
    } else if (entry.isFile() && entry.name.endsWith('.tsx')) {
      yield full
    }
  }
}

function stripComments(src) {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, m => ' '.repeat(m.length))
    .replace(/\/\/[^\n]*/g, m => ' '.repeat(m.length))
}

function lineOf(src, index) {
  return src.slice(0, index).split('\n').length
}

function scanFile(filePath) {
  const src = stripComments(readFileSync(filePath, 'utf8'))
  const rel = relative(ROOT, filePath).replace(/\\/g, '/')
  const findings = []

  for (const { name, re } of CHECKS) {
    re.lastIndex = 0
    let m
    while ((m = re.exec(src)) !== null) {
      const value = m[1]
      if (!CJK.test(value)) continue
      findings.push({
        file: rel,
        line: lineOf(src, m.index),
        check: name,
        value: value.trim(),
      })
    }
  }
  return findings
}

const findings = [...walkTsx(WEB_APP)]
  .flatMap(scanFile)
  .sort((a, b) => `${a.file}:${a.line}`.localeCompare(`${b.file}:${b.line}`))

const isUpdate = process.argv.includes('--update')

if (isUpdate) {
  writeFileSync(SNAPSHOT, JSON.stringify(findings, null, 2) + '\n')
  console.log(`✅ スナップショット更新: ${findings.length} 件の既知違反を記録しました`)
  for (const v of findings) {
    console.log(`  ${v.file}:${v.line}  [${v.check}]  "${v.value}"`)
  }
  process.exit(0)
}

// --- CI チェックモード ---
let snapshot = []
try {
  snapshot = JSON.parse(readFileSync(SNAPSHOT, 'utf8'))
} catch {
  console.error('❌ web/i18n-violations.json が見つかりません。')
  console.error('   先に: node scripts/check-i18n.mjs --update')
  process.exit(1)
}

const knownKeys = new Set(snapshot.map(v => `${v.file}::${v.check}::${v.value}`))
const newViolations = findings.filter(v => !knownKeys.has(`${v.file}::${v.check}::${v.value}`))

if (newViolations.length === 0) {
  const removed = snapshot.length - findings.length
  if (removed > 0) {
    console.log(`✅ i18n 対応進捗: ${removed} 件削減（残 ${findings.length} 件）`)
    console.log('   スナップショットを更新してください: node scripts/check-i18n.mjs --update')
  } else {
    console.log(`✅ 新規ハードコード CJK 文字列なし（既知違反 ${findings.length} 件）`)
  }
  process.exit(0)
} else {
  console.error(`\n❌ 新規ハードコード CJK 文字列が ${newViolations.length} 件見つかりました:\n`)
  for (const v of newViolations) {
    console.error(`  ${v.file}:${v.line}  [${v.check}]`)
    console.error(`    "${v.value}"`)
  }
  console.error('\n翻訳キー（t("key")）を使うか、既知の場合はスナップショットを更新してください:')
  console.error('  node scripts/check-i18n.mjs --update')
  process.exit(1)
}
