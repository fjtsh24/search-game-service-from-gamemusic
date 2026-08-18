"""
音楽に関するテキスト（Steam OST ストアページの説明文など）から
mood_tags 名を抽出する共有ロジック。

もとは import_description_tags.py に実装されていたが、同スクリプトが読んでいた
games.description は Steam の short_description（ゲームプレイの宣伝文）であり、
音楽への言及をほとんど含まないため 212 件試行して 1 件しかタグが付かなかった。
（詳細: docs/planning/08_tagging_redesign.md §3-B）

そのためスクリプト本体は廃止し、パターン定義のみをここへ移して
「実際に音楽について書かれたテキスト」に対して再利用する。

2 つのマッチングモードを持つ:

  music_context=False（汎用テキスト向け・従来の挙動）
    ゲーム紹介文のように音楽以外の話題が混ざるテキストが対象。
    explicit パターン（アンカー語を内包する複合フレーズ）を優先し、
    contextual パターンは音楽アンカー語が前後 80 文字以内にある場合のみ許可する。

  music_context=True（OST 説明文向け）
    テキスト全体が音楽についての記述であることが前提のため、
    contextual パターンにアンカー語の近接を要求しない。
    例: Chicory OST の "intimate piano, chamber grooves and electronic bombast" は
    「piano」「electronic」が音楽の記述であることが文脈上自明。
"""

import re

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


# music_context=True のときだけ有効なパターン。
# 「テキスト全体が音楽についての記述」という前提があるため、
# アンカー語を要求せず素の語（piano / electronic / dark 等）でマッチさせてよい。
# 汎用テキスト（ゲーム紹介文）では誤爆するので music_context=False では使わない。
_MUSIC_ONLY: dict[str, list[str]] = {
    'orchestral'   : [
        r'\borchestral\b',
        r'\borchestra\b',
        r'\bsymphonic\b',
        r'\bsymphony\b',
        r'\bstrings?\b',
        r'\bviolin\b',
        r'\bcello\b',
        r'\bbrass\b',
        r'\bclassical\b',
        r'\bchamber\b',
        r'\bwoodwinds?\b',
        r'\bflute\b',
        r'\bharp\b',
    ],
    'dark'         : [
        r'\bterror\w*',
        r'\bterrifying\b',
        r'\bcreepy\b',
        r'\bnightmar\w*',
        r'\bdread\w*',
        r'\bgrim\b',
        r'\bdark\b',
        r'\bhaunting\b',
        r'\beerie\b',
        r'\bominous\b',
        r'\bsinister\b',
        r'\bhorror\b',
        r'\bdissonan\w*',
        r'\bunsettling\b',
        r'\bmenacing\b',
        r'\bgothic\b',
    ],
    'ambient'      : [
        r'\bambient\b',
        r'\batmospheric\b',
        r'\bsoundscapes?\b',
        r'\bdrones?\b',
        r'\bethereal\b',
        r'\bminimalist?\b',
    ],
    'upbeat'       : [
        r'\bupliftin\w*',
        r'\benergetic\s+tunes?\b',
        r'\bhappy\b',
        r'\bupbeat\b',
        r'\bcheerful\b',
        r'\bplayful\b',
        r'\bbouncy\b',
        r'\blively\b',
        r'\bcatchy\b',
        r'\bwhimsical\b',
        r'\bjoyful\b',
        r'\bfunky\b',
        r'\bgroovy\b',
        r'\bgrooves?\b',
    ],
    'chiptune'     : [
        r'\bchiptunes?\b',
        r'\b8[\s-]?bit\b',
        r'\bchip\s?music\b',
        r'\bretro\b',
        r'\bfamicom\b',
        r'\btracker\b',
        r'\bbitpop\b',
    ],
    'jazz'         : [
        r'\bjazz\w*',
        r'\bblues\w*',
        r'\bswing\s+(?:band|jazz|music|era)\b',
        r'\bbebop\b',
        r'\bbossa\s+nova\b',
        r'\bsaxophone\b',
        r'\bbig\s+band\b',
    ],
    'electronic'   : [
        r'\bdance\s+music\b',
        r'\belectro\b',
        r'\bchiptronic\b',
        r'\belectronic\w*',
        r'\bsynths?\b',
        r'\bsynthesizers?\b',
        r'\bsynthwave\b',
        r'\btechno\b',
        r'\bedm\b',
        r'\btrance\b',
        r'\bdubstep\b',
        r'\bdrum\s+(?:and|&|n)\s+bass\b',
        r'\bhouse\s+music\b',
        r'\bidm\b',
        r'\bglitch\b',
        r'\bbeats?\b',
    ],
    'acoustic'     : [
        r'\bacoustic\b',
        r'\bpianos?\b',
        r'\bukulele\b',
        r'\bunplugged\b',
        r'\bfingerpick\w*',
    ],
    'epic'         : [
        r'\bepic\b',
        r'\bcinematic\b',
        r'\bheroic\b',
        r'\bmajestic\b',
        r'\btriumphant\b',
        r'\bsweeping\b',
        r'\bbombast\w*',
    ],
    'melancholic'  : [
        r'\bsad\b',
        r'\bmelanchol\w*',
        r'\bheartfelt\b',
        r'\btender\b',
        r'\bmelanchol\w*',
        r'\bnostalgic\b',
        r'\bbittersweet\b',
        r'\bsomber\b',
        r'\bwistful\b',
        r'\bmournful\b',
        r'\bpoignant\b',
        r'\bemotional\b',
        r'\bpost[\s-]rock\b',
        r'\bshoegaze\b',
    ],
    'relaxing'     : [
        r'\brelaxing\b',
        r'\bcalm\w*',
        r'\bsoothing\b',
        r'\bpeaceful\b',
        r'\bmellow\b',
        r'\bchill\w*',
        r'\blo[\s-]?fi\b',
        r'\bgentle\b',
        r'\btranquil\b',
        r'\bcozy\b',
        r'\bcosy\b',
    ],
    'intense'      : [
        r'\bpulse[\s-]poundin\w*',
        r'\bhard[\s-]hittin\w*',
        r'\bintense\b',
        r'\baggressive\b',
        r'\benergetic\b',
        r'\bfrantic\b',
        r'\bdriving\s+(?:beats?|rhythms?|bass|guitars?|synths?)\b',
        r'\brelentless\b',
        r'\badrenaline\b',
        r'\bhigh[\s-]energy\b',
        r'\bpounding\b',
    ],
    'folk'         : [
        r'\bfolk\w*',
        r'\bceltic\b',
        r'\btraditional\s+(?:music|instruments?|songs?|folk|melodies)\b',
        r'\bethnic\b',
        r'\btribal\b',
        r'\bworld\s+music\b',
        r'\bmedieval\b',
        r'\bbanjo\b',
        r'\baccordion\b',
    ],
    'metal'        : [
        r'\bmetal\b',
        r'\bhard\s+rock\b',
        r'\bprog(?:ressive)?\s+rock\b',
        r'\bpunk\b',
        r'\bshred\w*',
        r'\briffs?\b',
        r'\bdistort\w*',
        r'\bheavy\s+guitars?\b',
        r'\brock\b',
    ],
    'vocal'        : [
        r'\bvocals?\b',
        r'\bvocalist\b',
        r'\bsinger\w*',
        r'\bsinging\b',
        r'\bchoir\b',
        r'\bchoral\b',
        r'\ba\s+cappella\b',
        r'\blyrics\b',
        r'\bsung\b',
        r'\btheme\s+song\b',
    ],
    'instrumental' : [
        r'\binstrumentals?\b',
    ],
}

_MUSIC_ONLY_COMPILED: dict[str, list[re.Pattern]] = {
    tag: [re.compile(p, re.IGNORECASE) for p in pats]
    for tag, pats in _MUSIC_ONLY.items()
}


def _has_anchor_nearby(text: str, match: re.Match, window: int = 80) -> bool:
    start = max(0, match.start() - window)
    end = min(len(text), match.end() + window)
    return bool(_ANCHOR.search(text[start:end]))


def extract_tags(text: str, music_context: bool = False) -> list[str]:
    """テキストから mood_tag 名のリストを返す。

    music_context=True のときはテキスト全体が音楽の記述だとみなし、
    contextual パターンにアンカー語の近接を要求しない。
    """
    if not text:
        return []
    lowered = text.lower()
    matched = []
    for tag, compiled in _COMPILED.items():
        found = any(pat.search(lowered) for pat in compiled.get("explicit", []))
        if not found and music_context:
            found = any(pat.search(lowered) for pat in _MUSIC_ONLY_COMPILED.get(tag, []))
        if not found:
            for pat in compiled.get("contextual", []):
                m = pat.search(lowered)
                if not m:
                    continue
                if music_context or _has_anchor_nearby(lowered, m):
                    found = True
                    break
        if found:
            matched.append(tag)
    return matched
