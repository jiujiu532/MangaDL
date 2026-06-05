import time
import zipfile
from io import BytesIO

from download_manager import extract_chapter_number, format_chapter_dir

from .utils import detect_image_extension, safe_filename


def stream_zip(chapter_groups, source_resolver, archive_name_resolver):
    """按漫画/章节组流式生成 ZIP。"""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def generate():
        buf = BytesIO()
        zf = zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED)
        written = 0

        def _flush():
            nonlocal written
            buf.seek(0, 2)
            new_pos = buf.tell()
            if new_pos > written:
                buf.seek(written)
                data = buf.read(new_pos - written)
                written = new_pos
                return data
            return b""

        with ThreadPoolExecutor(max_workers=128) as pool:
            for group in chapter_groups:
                source = source_resolver(group)
                chapters = group.get("chapters", [])
                if not source or not chapters:
                    continue

                def _dl_img(img_url, current_source=source):
                    for attempt in range(3):
                        data = current_source.download_image(img_url, timeout=20)
                        if data:
                            return data
                        time.sleep(0.2 * attempt)
                    return None

                def _prefetch(ch_url, current_source=source):
                    try:
                        return current_source.get_chapter_images(ch_url)
                    except Exception:
                        return []

                next_images_future = pool.submit(_prefetch, chapters[0].get("url", "")) if chapters else None
                manga_dir = safe_filename(archive_name_resolver(group))

                for ch_idx, chapter in enumerate(chapters):
                    ch_title = chapter.get("title", f"Chapter_{ch_idx + 1}")
                    ch_num = extract_chapter_number(ch_title)
                    is_raw = "raw" in ch_title.lower()
                    safe_ch = format_chapter_dir(ch_num, is_raw)

                    images = next_images_future.result() if next_images_future else []
                    next_images_future = None

                    if ch_idx + 1 < len(chapters):
                        next_images_future = pool.submit(_prefetch, chapters[ch_idx + 1].get("url", ""))

                    if not images:
                        continue

                    futures = {pool.submit(_dl_img, url): idx for idx, url in enumerate(images)}
                    img_data = {}

                    for future in as_completed(futures):
                        idx = futures[future]
                        raw = future.result()
                        if raw:
                            img_data[idx] = raw

                    for idx in range(len(images)):
                        if idx not in img_data:
                            continue
                        raw = img_data[idx]
                        ext = detect_image_extension(raw)
                        filename = f"{manga_dir}/{safe_ch}/{str(idx + 1).zfill(3)}{ext}"
                        zf.writestr(filename, raw)
                        del img_data[idx]
                        chunk = _flush()
                        if chunk:
                            yield chunk

        zf.close()
        chunk = _flush()
        if chunk:
            yield chunk

    return generate
