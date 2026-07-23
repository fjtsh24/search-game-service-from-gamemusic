"""
Steam説明文をClaude API（Haiku）に渡してムードタグを推定し、
game_tagsテーブルに保存する。

daily-import での位置付け（Step 1-B）:
  Last.fm（Step 1-A）で tags_locked=TRUE になったゲームのうち、
  games.description が存在するものを対象に AI でタグを推定する。

対象の選び方:
  tags_locked = TRUE  ← Last.fm で失敗済み
  かつ game_tags 未登録
  かつ games.description IS NOT NULL

1 日あたり --limit 件処理（デフォルト 40 件）。
コスト目安: Claude Haiku ~$0.00008/件。1,000件処理しても $0.08。

使い方:
  python3 scripts/import_game_tags_ai.py [--limit 40]

依存:
  pip install anthropic requests python-dotenv supabase
"""

import argparse
import json
import os
import time
import requests
from dotenv import load_dotenv

load_dotenv(dotenv_path=".env")

try:
    from supabase import create_client
except ImportError:
    print("pip install requests python-dotenv supabase")
    raise SystemExit(1)

try:
    import anthropic
except ImportError:
    print("pip install anthropic")
    raise SystemExit(1)

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_ROLE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
UPSTASH_REDIS_URL = os.environ.get("UPSTASH_REDIS_URL", "")
UPSTASH_REDIS_TOKEN = os.environ.get("UPSTASH_REDIS_TOKEN", "")

db = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
ai = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

MODEL = "claude-haiku-4-5-20251001"
WAIT = 0.5
MAX_DESC_CHARS = 2000
MIN_CONFIDENCE = 0.5


# ── キャッシュクリア ──────────────────────────────────────────────────────────

def clear_cache(tagged_game_ids: list[str], tagged_tag_ids: list[str]) -> None:
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return
    headers = {"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"}
    keys = []
    for gid in tagged_game_ids:
        keys.append(f"games:detail:{gid}")
        keys.append(f"games:similar:{gid}:8")
    for tid in tagged_tag_ids:
        for limit in (20, 50, 100):
            keys.append(f"games:list:{tid}:{limit}")
    for limit in (20, 50, 100):
        keys.append(f"games:list:all:{limit}")
    if not keys:
        return
    url = f"{UPSTASH_REDIS_URL}/del/{'/'.join(keys)}"
    try:
        resp = requests.get(url, headers=headers, timeout=5)
        print(f"キャッシュクリア: {resp.json().get('result', '?')} 件削除")
    except Exception as e:
        print(f"キャッシュクリア失敗（無視）: {e}")


# ── データ取得 ────────────────────────────────────────────────────────────────

def get_mood_tags() -> dict[str, dict]:
    rows = db.table("mood_tags").select("id, name").execute().data or []
    return {row["name"]: row for row in rows}


def get_target_games(limit: int) -> list[dict]:
    """tags_locked=TRUE かつ game_tags 未登録 かつ description あり のゲームを返す。"""
    tagged_ids = {
        row["game_id"]
        for row in (db.table("game_tags").select("game_id").execute().data or [])
    }

    rows = (
        db.table("games")
        .select("id, title, description")
        .eq("tags_locked", True)
        .not_.is_("description", "null")
        .limit(limit * 3)
        .execute()
        .data or []
    )

    result = [
        r for r in rows
        if r["id"] not in tagged_ids and (r.get("description") or "").strip()
    ]
    return result[:limit]


# ── Claude API 呼び出し ───────────────────────────────────────────────────────

def ask_claude(title: str, description: str, tag_names: list[str]) -> list[tuple[str, float]]:
    """説明文からムードタグを推定する。[(tag_name, confidence)] を返す。"""
    safe_title = title.replace('"', "'")[:200]
    prompt = f"""You are a game music classifier.

Read the following Steam game description for "{safe_title}" and select mood/genre tags that best describe its soundtrack.

Available tags (choose only from this list): {json.dumps(tag_names, ensure_ascii=False)}

Game description:
{description[:MAX_DESC_CHARS]}

Return ONLY a JSON object. Select up to 5 tags with confidence scores (0.0-1.0). Only include tags you're confident about (confidence >= {MIN_CONFIDENCE}).

{{"tags": [{{"name": "tag_name", "confidence": 0.8}}, ...]}}"""

    message = ai.messages.create(
        model=MODEL,
        max_tokens=256,
        messages=[{"role": "user", "content": prompt}],
    )

    text = message.content[0].text.strip()
    start = text.find("{")
    end = text.rfind("}") + 1
    if start == -1 or end == 0:
        return []

    try:
        data = json.loads(text[start:end])
    except json.JSONDecodeError as e:
        raise ValueError(f"Claude returned invalid JSON: {e} | raw: {text[:200]}") from e

    valid_names = set(tag_names)
    return [
        (t["name"], float(t["confidence"]))
        for t in data.get("tags", [])
        if t.get("name") in valid_names and float(t.get("confidence", 0)) >= MIN_CONFIDENCE
    ]


# ── メインループ ───────────────────────────────────────────────────────────────

def run(limit: int) -> None:
    mood_tag_index = get_mood_tags()
    tag_names = list(mood_tag_index.keys())
    print(f"mood_tags: {len(tag_names)} 件ロード済み")

    games = get_target_games(limit)
    if not games:
        print("対象ゲームがありません（tags_locked=TRUE かつ未タグ かつ description あり）。")
        return

    print(f"{len(games)} 件のゲームを AI でタグ推定します...\n")

    total_tagged = 0
    total_skipped = 0
    tagged_game_ids: list[str] = []
    tagged_tag_ids: list[str] = []

    for game in games:
        title = game["title"]
        description = game.get("description") or ""

        print(f"  [{title}]")

        try:
            results = ask_claude(title, description, tag_names)
        except Exception as e:
            print(f"  → Claude API エラー: {e} → スキップ")
            total_skipped += 1
            time.sleep(WAIT)
            continue

        if not results:
            print(f"  → タグなし（確信度不足または該当なし）→ スキップ")
            total_skipped += 1
            time.sleep(WAIT)
            continue

        rows = [
            {
                "game_id": game["id"],
                "tag_id": mood_tag_index[name]["id"],
                "confidence": conf,
                "added_by": "ai_steam_desc",
            }
            for name, conf in results
            if name in mood_tag_index
        ]

        if not rows:
            print(f"  → タグなし → スキップ")
            total_skipped += 1
            time.sleep(WAIT)
            continue

        db.table("game_tags").upsert(rows, on_conflict="game_id,tag_id").execute()
        applied = [name for name, _ in results if name in mood_tag_index]
        print(f"  → タグ付与: {', '.join(applied)}")
        tagged_game_ids.append(game["id"])
        tagged_tag_ids.extend(mood_tag_index[name]["id"] for name, _ in results if name in mood_tag_index)
        total_tagged += 1
        time.sleep(WAIT)

    print(f"\n完了 — タグ付与: {total_tagged} 件 / スキップ: {total_skipped} 件")

    if tagged_game_ids:
        clear_cache(tagged_game_ids, list(set(tagged_tag_ids)))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Steam説明文から Claude API でゲームタグを推定して game_tags に保存"
    )
    parser.add_argument("--limit", type=int, default=40,
                        help="処理するゲーム数 (デフォルト: 40)")
    args = parser.parse_args()
    run(args.limit)
