import difflib
import os
import re


def normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", title.lower())


def fuzzy_match(query: str, candidate: str) -> float:
    nq, nc = normalize_title(query), normalize_title(candidate)
    if nq == nc:
        return 1.0
    if nq in nc or nc in nq:
        return 0.9
    char_ratio = difflib.SequenceMatcher(None, nq, nc).ratio()
    q_words = set(re.findall(r"[a-z0-9\u4e00-\u9fff]+", query.lower()))
    c_words = set(re.findall(r"[a-z0-9\u4e00-\u9fff]+", candidate.lower()))
    if q_words:
        word_overlap = len(q_words & c_words) / len(q_words)
    else:
        word_overlap = 0
    if word_overlap < 0.5:
        return min(char_ratio, 0.5)
    return char_ratio


def get_source_by_name_or_url(sources, src_name: str = "", url: str = ""):
    source = sources[0] if sources else None
    for item in sources:
        if src_name and item.name == src_name:
            return item
        if url and item.base_url in url:
            source = item
    return source


def chapter_range(chapters, extract_chapter_number):
    ch_nums = [extract_chapter_number(ch.get("title", "")) for ch in chapters]
    ch_nums_float = []
    for value in ch_nums:
        try:
            ch_nums_float.append((float(value), value))
        except Exception:
            pass
    if not ch_nums_float:
        return "", ""
    ch_nums_float.sort()
    return ch_nums_float[0][1], ch_nums_float[-1][1]


def safe_filename(name: str, suffix: str = "") -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|]", "_", name).strip()
    return f"{cleaned}{suffix}"


def detect_image_extension(raw: bytes) -> str:
    if raw[:4] == b"\x89PNG":
        return ".png"
    if raw[:4] == b"RIFF":
        return ".webp"
    if raw[:3] == b"GIF":
        return ".gif"
    return ".jpg"


def build_stats(download_dir, favorites_count: int):
    manga_count = 0
    total_size = 0
    img_ext = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif"}
    if os.path.exists(download_dir):
        for directory in os.listdir(download_dir):
            dpath = os.path.join(download_dir, directory)
            if not os.path.isdir(dpath):
                continue
            is_manga = False
            for sub in os.listdir(dpath):
                subpath = os.path.join(dpath, sub)
                if os.path.isdir(subpath):
                    for filename in os.listdir(subpath):
                        if os.path.splitext(filename)[1].lower() in img_ext:
                            is_manga = True
                            break
                if is_manga:
                    break
            if is_manga:
                manga_count += 1
                for root, _, files in os.walk(dpath):
                    for filename in files:
                        try:
                            total_size += os.path.getsize(os.path.join(root, filename))
                        except Exception:
                            pass
    return {
        "manga_count": manga_count,
        "total_size_mb": round(total_size / (1024 * 1024), 1),
        "favorites_count": favorites_count,
    }
