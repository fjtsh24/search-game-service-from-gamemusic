"""
ゲームの Steam 説明文（description フィールド）からキーワードを抽出し、
mood_tags として game_tags テーブルに登録する。

対象: tags_locked = TRUE のゲーム（Last.fm タグ取得に失敗済み）。
追加したタグの added_by = 'description'、confidence = 0.5（Last.fm タグより低め）。

保守的な判定:
  - 音楽的な意味に絞るため、style キーワード単体では原則マッチさせない。
  - 「orchestral score」「jazz soundtrack」等の複合フレーズ、
    または style キーワードが音楽アンカー語（music/score/soundtrack 等）の
    前後 80 文字以内にあるときのみマッチする。
  - "dark"/"epic"/"intense" 等のゲーム設定語は複合フレーズのみ許可。

使い方:
  python3 scripts/import_description_tags.py [--limit 100] [--dry-run]

  --dry-run: DB 書き込みを行わず、マッチ結果だけ表示する。
"""

import argparse
import os
import re

from dotenv import load_dotenv

load_dotenv(dotenv_path=".env")

try:
    from supabase import create_client
except ImportError:
    print("pip install python-dotenv supabase")
    raise SystemExit(1)

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_ROLE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
UPSTASH_REDIS_URL = os.environ.get("UPSTASH_REDIS_URL", "")
UPSTASH_REDIS_TOKEN = os.environ.get("UPSTASH_REDIS_TOKEN", "")

db = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

CONFIDENCE = 0.5
ADDED_BY = "description"

# 音楽を示すアンカー語（これの前後 80 文字以内なら contextual パターンも許可）
_ANCHOR = re.compile(
    r"\b(music(?:al)?|soundtrack|score|ost|audio|songs?|tracks?|"
    r"compositions?|composed(?:\s+by)?|composer|bgm|"
    r"melody|melodies|themes?|tunes?|beats?|arrangement)\b",
    re.IGNORECASE,
)

# per-tag パターン定義
# explicit  : アンカー語を内包するため単体で安全なフレーズ
# contextual: アンカー語が近傍にある場合のみ許可するキーワード
_PATTERNS: dict[str, dict[str, list[str]]] = {
    "orchestral": {
        "explicit": [
            r"orchestral\s+(?:score|music|soundtrack|arrangement|composition)",
            r"symphonic\s+(?:score|music|soundtrack|composition)",
            r"(?:full|live)\s+orchestra",
            r"philharmonic\s+(?:orchestra|score)",
        ],
        "contextual": [
            r"\borchestral\b",
            r"\bsymphony\b",
            r"\bsymphonic\b",
        ],
    },
    "chiptune": {
        "explicit": [
            r"chiptune",
            r"chip[\s-]tune",
            r"8[\s-]bit\s+(?:music|sound|audio|style)",
            r"retro[\s-](?:game[\s-])?(?:music|sound|chip|style)",
        ],
        "contextual": [],
    },
    "jazz": {
        "explicit": [
            r"jazz[\s-](?:score|music|soundtrack|fusion|inspired|influenced)",
            r"bossa\s+nova",
            r"(?:blues|swing|bebop)\s+(?:score|music|soundtrack|inspired)",
        ],
        "contextual": [
            r"\bjazz\b",
            r"\bblues\b",
        ],
    },
    "ambient": {
        "explicit": [
            r"ambient\s+(?:music|soundtrack|soundscape|score|electronic)",
            r"atmospheric\s+(?:music|soundtrack|soundscape|score)",
        ],
        "contextual": [
            r"\bambient\b",
        ],
    },
    "electronic": {
        "explicit": [
            r"electronic\s+(?:music|soundtrack|score|beats?)",
            r"synth(?:wave|pop|esizer)?\s+(?:music|soundtrack|score|beats?)",
            r"electroni[ck]a",
        ],
        "contextual": [
            r"\bsynthwave\b",
            r"\belectronica\b",
        ],
    },
    "epic": {
        "explicit": [
            r"epic\s+(?:score|music|soundtrack|orchestral|composition|theme)",
            r"cinematic\s+(?:score|music|soundtrack|orchestral)",
            r"heroic\s+(?:score|music|soundtrack|theme)",
        ],
        "contextual": [],
    },
    "dark": {
        "explicit": [
            r"dark\s+ambient",
            r"dark\s+(?:music|score|soundtrack|orchestral|theme)",
            r"(?:haunting|eerie|ominous|sinister)\s+(?:music|score|soundtrack|melody|melodies|theme)",
        ],
        "contextual": [],
    },
    "relaxing": {
        "explicit": [
            r"(?:relaxing|peaceful|calming|soothing|tranquil)\s+(?:music|score|soundtrack|melody|melodies|theme)",
            r"lo[\s-]fi\s+(?:music|soundtrack|vibes|beats?)",
            r"chill(?:out|ing)?\s+(?:music|soundtrack|vibes|beats?)",
        ],
        "contextual": [],
    },
    "folk": {
        "explicit": [
            r"folk\s+(?:music|score|soundtrack|songs?|inspired|influences|elements?)",
            r"celtic\s+(?:music|score|soundtrack|inspired|influences|folk)",
            r"(?:tribal|ethnic|traditional)\s+(?:music|score|soundtrack)",
            r"world[\s-]music",
        ],
        "contextual": [
            r"\bceltic\b",
            r"\bfolk\b",
        ],
    },
    "metal": {
        "explicit": [
            r"(?:heavy\s+)?metal\s+(?:music|soundtrack|score|inspired|riffs?)",
            r"(?:hard|prog(?:ressive)?)\s+rock\s+(?:music|soundtrack|score|inspired)",
            r"rock\s+(?:music|soundtrack|score|inspired|influenced)",
        ],
        "contextual": [
            r"\bheavy\s+metal\b",
        ],
    },
    "upbeat": {
        "explicit": [
            r"(?:upbeat|cheerful|lively|catchy|fun|playful)\s+(?:music|score|soundtrack|tunes?|melody|melodies|beats?)",
            r"(?:energetic|uplifting)\s+(?:music|score|soundtrack|tunes?|beats?)",
        ],
        "contextual": [],
    },
    "melancholic": {
        "explicit": [
            r"(?:melanchol(?:ic|y)|nostalgic|bittersweet|somber|wistful)\s+(?:music|score|soundtrack|melody|melodies|theme)",
            r"post[\s-]rock\s+(?:music|soundtrack|score|inspired|influences|sound|elements?)",
            r"shoegaze\s+(?:music|soundtrack|sound|inspired)",
        ],
        "contextual": [
            r"\bmelanchol(?:ic|y)\b",
        ],
    },
    "acoustic": {
        "explicit": [
            r"acoustic\s+(?:music|score|soundtrack|guitar|piano|instruments?|arrangements?)",
            r"piano[\s-]driven\s+(?:music|score|soundtrack)?",
            r"piano\s+(?:music|score|soundtrack|solos?|pieces?|composition)",
        ],
        "contextual": [
            r"\bacoustic\b",
        ],
    },
    "vocal": {
        "explicit": [
            r"vocal\s+(?:music|score|soundtrack|performances?|arrangements?)",
            r"(?:choir|choral)\s+(?:music|arrangements?|pieces?|singing|vocals?)",
            r"features?\s+(?:singing|vocals?|singers?)",
            r"(?:original|anime|j[\s-]?pop)\s+(?:songs?|vocals?)",
        ],
        "contextual": [
            r"\bchoir\b",
            r"\bvocals?\b",
        ],
    },
    "instrumental": {
        "explicit": [
            r"\binstrumental\b",
        ],
        "contextual": [],
    },
    "intense": {
        "explicit": [
            r"(?:intense|adrenaline[\s-]pumping|high[\s-]energy)\s+(?:music|score|soundtrack|battle|beats?)",
            r"battle\s+(?:music|themes?|score)",
            r"action[\s-]packed\s+(?:music|score|soundtrack)",
        ],
        "contextual": [],
    },
}

# コンパイル済みパターンをキャッシュ
_COMPILED: dict[str, dict[str, list[re.Pattern]]] = {
    tag: {
        kind: [re.compile(p, re.IGNORECASE) for p in pats]
        for kind, pats in tag_pats.items()
    }
    for tag, tag_pats in _PATTERNS.items()
}


def _has_anchor_nearby(text: str, match: re.Match, window: int = 80) -> bool:
    start = max(0, match.start() - window)
    end = min(len(text), match.end() + window)
    return bool(_ANCHOR.search(text[start:end]))


def extract_tags(description: str) -> list[str]:
    """English description テキストから mood_tag 名リストを返す（保守的マッチング）。"""
    if not description:
        return []
    text = description.lower()
    matched = []
    for tag, compiled in _COMPILED.items():
        found = False
        for pat in compiled.get("explicit", []):
            if pat.search(text):
                found = True
                break
        if not found:
            for pat in compiled.get("contextual", []):
                m = pat.search(text)
                if m and _has_anchor_nearby(text, m):
                    found = True
                    break
        if found:
            matched.append(tag)
    return matched


def _clear_cache(game_ids: list[str], tag_ids: list[str]) -> None:
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return
    import requests
    headers = {"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"}
    keys = []
    for gid in game_ids:
        keys.append(f"games:detail:{gid}")
        keys.append(f"games:similar:{gid}:8")
    for tid in tag_ids:
        for limit in (20, 50, 100):
            keys.append(f"games:list:{tid}:{limit}")
    for limit in (20, 50, 100):
        keys.append(f"games:list:all:{limit}")
    if not keys:
        return
    try:
        s = requests.Session()
        s.headers.update({"User-Agent": "GameMusicDiscovery/0.1.0"})
        resp = s.post(f"{UPSTASH_REDIS_URL}/", headers=headers, json=["del"] + keys, timeout=5)
        print(f"キャッシュクリア: {resp.json().get('result', '?')} 件削除")
    except Exception as e:
        print(f"キャッシュクリア失敗（無視）: {e}")


def run(limit: int, dry_run: bool) -> None:
    # mood_tags 名 → id マップ
    tag_rows = db.table("mood_tags").select("id, name").execute().data or []
    tag_id_map: dict[str, str] = {r["name"]: r["id"] for r in tag_rows}

    # tags_locked = TRUE かつ description がある未タグゲームを取得
    # すでに description タグがあるゲームは skip（added_by = 'description' で判定）
    existing_desc_tags = (
        db.table("game_tags")
        .select("game_id")
        .eq("added_by", ADDED_BY)
        .execute()
        .data or []
    )
    already_done: set[str] = {r["game_id"] for r in existing_desc_tags}

    games = (
        db.table("games")
        .select("id, title, description")
        .eq("tags_locked", True)
        .not_.is_("description", "null")
        .order("created_at", desc=False)
        .limit(limit * 3)  # already_done を除外した後 limit 件になるよう多めに取得
        .execute()
        .data or []
    )

    # already_done を除外
    candidates = [g for g in games if g["id"] not in already_done][:limit]

    if not candidates:
        print("処理対象ゲームなし（tags_locked=TRUE で description あり）")
        return

    print(f"処理対象: {len(candidates)} 件")

    tagged_game_ids: list[str] = []
    tagged_tag_ids: set[str] = set()
    total_tags = 0

    for game in candidates:
        title = game.get("title", "?")
        desc = game.get("description") or ""
        matched_names = extract_tags(desc)

        if not matched_names:
            print(f"  [{title}] マッチなし")
            continue

        rows_to_insert = []
        for tag_name in matched_names:
            tid = tag_id_map.get(tag_name)
            if not tid:
                print(f"  [{title}] タグ ID 不明: {tag_name}")
                continue
            rows_to_insert.append({
                "game_id": game["id"],
                "tag_id": tid,
                "confidence": CONFIDENCE,
                "added_by": ADDED_BY,
            })
            tagged_tag_ids.add(tid)

        if rows_to_insert:
            tag_names_str = ", ".join(matched_names)
            print(f"  [{title}] → {tag_names_str}")
            if not dry_run:
                db.table("game_tags").upsert(rows_to_insert, on_conflict="game_id,tag_id").execute()
            tagged_game_ids.append(game["id"])
            total_tags += len(rows_to_insert)

    print(f"\n完了: {len(tagged_game_ids)} ゲームに計 {total_tags} タグ追加")

    if dry_run:
        print("[dry-run] DB 書き込みはスキップしました")
    elif tagged_game_ids:
        _clear_cache(tagged_game_ids, list(tagged_tag_ids))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=100, help="処理するゲーム数上限")
    parser.add_argument("--dry-run", action="store_true", help="DB 書き込みを行わない")
    args = parser.parse_args()
    run(args.limit, args.dry_run)


if __name__ == "__main__":
    main()
