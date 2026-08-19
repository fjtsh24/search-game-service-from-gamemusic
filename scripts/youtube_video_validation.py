"""
YouTube 動画がゲームの OST として妥当そうかを判定する共有ロジック。

issue #105（games.youtube_video_id の31%がOSTと無関係な動画）の調査で
実測・検証したルールを切り出したもの。全310件を videos.list で検証した結果、
正常な OST 動画の最小尺は92秒（90秒未満は0件）だったため、90秒を下限にしても
正常な動画を誤除外しない。

このモジュールは判定のみを行い、DB の更新（youtube_locked を立てる等）は
呼び出し側の責務とする。
"""

import re

OST_WORD_RE = re.compile(
    r"(ost\b|soundtrack|original score|original sound|full album|bgm|サントラ|音楽|原声)",
    re.IGNORECASE,
)
_BAD_WORD_RE = re.compile(
    r"(walkthrough|gameplay|playthrough|let'?s play|review|speedrun|guide|"
    r"reaction|tutorial|攻略)",
    re.IGNORECASE,
)
_TRAILER_RE = re.compile(r"(trailer|announcement|teaser)", re.IGNORECASE)

MIN_DURATION_SECONDS = 90
# 「作業用BGMミックス」等、無関係な動画を弾くための尺の上限。
# タイトルに OST 語が無い動画にのみ適用する。
#
# 全310件の実測で、OST語を含まない長時間動画（AQUARIUM 12h、拖拖拉拉小菲镇 11.3h、
# Alpaca Stacka 10.4h）は全て無関係な動画だった一方、OST語を含む長時間動画
# （The Witcher 3 "FULL Soundtrack + DLC" 3.6h、Portal 2 "OST Full 3 parts" 3.4h、
# Denshattack! 3.8h 等）は大作 RPG や DLC 込みの正規フル OST だった。
# 尺だけで判定すると後者を誤って弾いてしまうため、OST語の有無で上限を分ける。
MAX_DURATION_SECONDS_NO_OST_WORD = 3 * 60 * 60
# OST語がある場合の上限。実測した OST語ありの最長は 3.8h（Denshattack!）だったため
# 十分な安全マージンを取る。24時間耐久配信のような極端なケースだけを弾く想定。
MAX_DURATION_SECONDS_WITH_OST_WORD = 8 * 60 * 60


def parse_iso8601_duration(iso: str | None) -> int:
    """YouTube API の ISO8601 duration（例: "PT1H2M3S"）を秒数に変換する。"""
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return 0
    h, mi, s = (int(x) if x else 0 for x in m.groups())
    return h * 3600 + mi * 60 + s


def _tokens(text: str) -> tuple[list[str], list[str]]:
    """ASCII 語（3文字以上）と CJK 2-gram を抽出する。"""
    text = text.lower()
    ascii_words = re.findall(r"[a-z0-9]{3,}", text)
    cjk = "".join(re.findall(r"[぀-ヿ㐀-鿿가-힯]", text))
    grams = [cjk[i:i + 2] for i in range(len(cjk) - 1)]
    return ascii_words, grams


def title_matches_game(game_title: str, video_text: str, threshold: float = 0.6) -> bool:
    """動画タイトル（+チャンネル名等）にゲーム名のキーワードが十分含まれるか判定する。

    ASCII 語・CJK 2-gram のいずれかで threshold 以上の一致率があれば True。
    ゲーム名が短すぎて語が抽出できない場合は False（過去の import_youtube_video_ids.py の
    「非ASCIIは無条件 True」という抜け穴を再現しないため、意図的に厳しくしている）。
    """
    ascii_words, grams = _tokens(game_title)
    video_lower = video_text.lower()

    if ascii_words:
        hit = sum(1 for w in ascii_words if w in video_lower)
        if hit >= max(1, round(len(ascii_words) * threshold)):
            return True
    if grams:
        hit = sum(1 for g in grams if g in video_lower)
        if hit >= max(1, round(len(grams) * threshold)):
            return True
    return False


def is_valid_ost_video(
    game_title: str,
    video_title: str,
    channel_title: str,
    category_id: str | None,
    topic_categories: list[str],
    duration_seconds: int,
) -> tuple[bool, str]:
    """動画がそのゲームの OST として妥当そうかを判定する。

    Returns: (妥当そうなら True, 判定理由)
    """
    has_ost_word = bool(OST_WORD_RE.search(video_title)) or channel_title.endswith("- Topic")

    if _BAD_WORD_RE.search(video_title) and not has_ost_word:
        return False, "実況・攻略・レビュー系のタイトル"
    if _TRAILER_RE.search(video_title) and not has_ost_word:
        return False, "トレーラー系のタイトル"
    if duration_seconds < MIN_DURATION_SECONDS:
        return False, f"尺が短すぎる（{duration_seconds}秒）"
    max_duration = (
        MAX_DURATION_SECONDS_WITH_OST_WORD if has_ost_word else MAX_DURATION_SECONDS_NO_OST_WORD
    )
    if duration_seconds > max_duration:
        return False, f"尺が長すぎる（{duration_seconds}秒） — 作業用BGMミックス等の可能性"

    is_music = (
        category_id == "10"
        or any("music" in t.lower() for t in topic_categories)
        or has_ost_word
    )
    if not is_music:
        return False, "音楽である根拠がない"

    if not title_matches_game(game_title, video_title + " " + channel_title):
        return False, "ゲーム名がタイトル・チャンネル名のいずれとも一致しない"

    return True, "OK"
