"""
漫画源适配器集合
"""
from .base import MangaSource
from .madara import MadaraSource
from .manhwahub import ManhwaHubSource
from .mangadna import MangaDNASource
from .manga18 import Manga18Source
from .xtoon import XToonSource



def get_all_sources() -> list[MangaSource]:
    """获取所有可用的漫画源"""
    return [
        MadaraSource("https://mangaforfree.net", "MangaForFree", "📗"),
        MadaraSource("https://manhwaclub.net", "ManhwaClub", "📘"),
        MadaraSource("https://www.mangaread.org", "MangaRead", "📙"),
        ManhwaHubSource(),
        MangaDNASource(),
        XToonSource(),
        Manga18Source(),
    ]
