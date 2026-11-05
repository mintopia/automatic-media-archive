"""Languages: the ISO 639 codes a Disc tags its tracks with, and the names people type.

TMDB gives a film's `original_language` as ISO 639-1 ("ja"); Discs tag tracks with
ISO 639-2 ("jpn", or both bibliographic and terminology forms: "fre"/"fra"). The
Encode's preferred languages (ADR 0010) are typed as names or codes ("English, ja").
"""

from __future__ import annotations

# ISO 639-1 -> (English name, the ISO 639-2 codes a Disc may tag it with).
LANGUAGES: dict[str, tuple[str, tuple[str, ...]]] = {
    "en": ("English", ("eng",)), "fr": ("French", ("fre", "fra")),
    "de": ("German", ("ger", "deu")), "es": ("Spanish", ("spa",)),
    "it": ("Italian", ("ita",)), "ja": ("Japanese", ("jpn",)), "ko": ("Korean", ("kor",)),
    "zh": ("Chinese", ("chi", "zho")), "cn": ("Chinese", ("chi", "zho")),
    "ru": ("Russian", ("rus",)), "pt": ("Portuguese", ("por",)),
    "nl": ("Dutch", ("dut", "nld")), "sv": ("Swedish", ("swe",)), "da": ("Danish", ("dan",)),
    "no": ("Norwegian", ("nor", "nob", "nno")), "nb": ("Norwegian Bokmål", ("nob", "nor")),
    "fi": ("Finnish", ("fin",)), "is": ("Icelandic", ("ice", "isl")),
    "pl": ("Polish", ("pol",)), "cs": ("Czech", ("cze", "ces")),
    "sk": ("Slovak", ("slo", "slk")), "hu": ("Hungarian", ("hun",)),
    "ro": ("Romanian", ("rum", "ron")), "el": ("Greek", ("gre", "ell")),
    "tr": ("Turkish", ("tur",)), "he": ("Hebrew", ("heb",)), "ar": ("Arabic", ("ara",)),
    "fa": ("Persian", ("per", "fas")), "hi": ("Hindi", ("hin",)), "ta": ("Tamil", ("tam",)),
    "te": ("Telugu", ("tel",)), "bn": ("Bengali", ("ben",)), "th": ("Thai", ("tha",)),
    "vi": ("Vietnamese", ("vie",)), "id": ("Indonesian", ("ind",)),
    "ms": ("Malay", ("may", "msa")), "tl": ("Tagalog", ("tgl", "fil")),
    "uk": ("Ukrainian", ("ukr",)), "sr": ("Serbian", ("srp",)), "hr": ("Croatian", ("hrv",)),
    "bg": ("Bulgarian", ("bul",)), "ca": ("Catalan", ("cat",)),
    "eu": ("Basque", ("baq", "eus")), "gl": ("Galician", ("glg",)), "ga": ("Irish", ("gle",)),
    "cy": ("Welsh", ("wel", "cym")), "et": ("Estonian", ("est",)), "lv": ("Latvian", ("lav",)),
    "lt": ("Lithuanian", ("lit",)), "sl": ("Slovenian", ("slv",)),
    "ka": ("Georgian", ("geo", "kat")), "hy": ("Armenian", ("arm", "hye")),
    "ur": ("Urdu", ("urd",)), "pa": ("Punjabi", ("pan",)), "ml": ("Malayalam", ("mal",)),
    "kn": ("Kannada", ("kan",)), "mr": ("Marathi", ("mar",)),
    "yue": ("Cantonese", ("chi", "zho", "yue")),
}

# Every way to type a language -> its ISO 639-1 code ("japanese", "ja", "jpn" -> "ja").
_TYPED: dict[str, str] = {}
for _code, (_name, _iso2) in reversed(list(LANGUAGES.items())):  # first entry wins
    for _alias in (_name.lower(), _code, *_iso2):
        _TYPED[_alias] = _code


def language_codes(iso_639_1: str) -> frozenset[str]:
    """Every tag a stream in this (TMDB) language may carry."""
    code = iso_639_1.lower()
    return frozenset({code, *LANGUAGES.get(code, ("", ()))[1]}) if code else frozenset()


def name_of(iso_639_1: str) -> str:
    return LANGUAGES.get(iso_639_1, (iso_639_1, ()))[0]


def parse_languages(text: str) -> tuple[str, ...]:
    """'English, ja' -> ('en', 'ja'), in the order typed. ValueError says what's wrong."""
    typed = [t.strip() for t in text.split(",") if t.strip()]
    if not typed:
        raise ValueError("Enter at least one language, like English")
    unknown = [t for t in typed if t.lower() not in _TYPED]
    if unknown:
        raise ValueError(f"AMA doesn't know {', '.join(unknown)}. Use names like English, "
                         "Japanese or codes like en, ja")
    codes: list[str] = []
    for t in typed:
        if (code := _TYPED[t.lower()]) not in codes:
            codes.append(code)
    return tuple(codes)
