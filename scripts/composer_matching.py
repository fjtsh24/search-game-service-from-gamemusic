"""Last.fm の類似アーティスト名を自前の composers に突合する純粋関数。

DB にも環境変数にも依存しないので、CI の軽量テストジョブ（標準ライブラリのみ）から
そのまま呼べる。import_lastfm_similarities.py は取得と保存だけを担当する。
"""


def match_key(composer: dict) -> str:
    """突合に使う正規化キー。lastfm_name があればそれを優先する。"""
    return (composer.get("lastfm_name") or composer["name"]).strip().lower()


def build_similarity_pairs(cached: list[dict], composers: list[dict]) -> list[dict]:
    """キャッシュ済みの類似アーティスト名を composers と突合してペアを組み立てる。

    Args:
        cached:    [{"composer_id", "similar_name", "score"}, ...]（Last.fm 応答のキャッシュ）
        composers: [{"id", "name", "lastfm_name"}, ...]（自前の作曲家）

    Returns:
        composer_similarities に upsert する行のリスト。
        PK が (composer_id_a, composer_id_b) なので ID をソートして順序を固定し、
        A→B と B→A の両方が取れている場合は高い方の score を採用する。
    """
    by_key = {match_key(c): c["id"] for c in composers}

    pairs: dict[tuple[str, str], dict] = {}
    for row in cached:
        match_id = by_key.get((row.get("similar_name") or "").strip().lower())
        if not match_id or match_id == row["composer_id"]:
            continue
        id_a, id_b = sorted([row["composer_id"], match_id])
        key = (id_a, id_b)
        if key not in pairs or row["score"] > pairs[key]["score"]:
            pairs[key] = {
                "composer_id_a": id_a,
                "composer_id_b": id_b,
                "score": row["score"],
                "source": "lastfm",
            }
    return list(pairs.values())
