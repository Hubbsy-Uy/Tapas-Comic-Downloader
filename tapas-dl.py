#!/usr/bin/env python3
import argparse
import os
import re
import requests
import http.cookiejar
from pathlib import Path
from pyquery import PyQuery as pq

# ------------------------------
# Helpers
# ------------------------------

def lead0(num, max):
    return str(num).zfill(len(str(max)))


def check_path(path, slash=True, fat=False):
    evil_chars = []
    if slash:
        evil_chars.append('/')
    if fat:
        evil_chars += ['?', '<', '>', '\\', ':', '*', '|', '"', '^']
    return ''.join([char for char in path if char not in evil_chars])


def printLine(msg='', noNewLine=False):
    if args.verbose or not noNewLine:
        print(msg)


# ------------------------------
# Setup argparse
# ------------------------------

parser = argparse.ArgumentParser(
    description="Download comics or novels from Tapas (tapas.io).",
    formatter_class=argparse.RawTextHelpFormatter
)

parser.add_argument("url", metavar="URL/name", type=str, nargs="+",
                    help="URL or short name of the comic/novel.\n"
                         "Examples:\n"
                         "  https://tapas.io/series/Erma\n"
                         "  RavenWolf")

parser.add_argument("-f", "--force", action="store_true", help="Redownload even if folder exists.")
parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging.")
parser.add_argument("-r", "--restrict-characters", action="store_true",
                    help="Remove special characters from filenames.")
parser.add_argument("-c", "--cookies", type=str, nargs="?", default="", dest="cookies", metavar="PATH",
                    help="Optional cookies.txt file (for mature/locked episodes).")
parser.add_argument("-o", "--output-dir", type=str, nargs="?", default="", dest="baseDir", metavar="PATH",
                    help="Output directory. Default = script folder.")

args = parser.parse_args()

# ------------------------------
# Session
# ------------------------------

s = requests.Session()
s.headers.update({
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/122.0 Safari/537.36",
    "Referer": "https://tapas.io/"
})

if args.cookies:
    s.cookies = http.cookiejar.MozillaCookieJar()
    s.cookies.load(args.cookies, ignore_discard=True, ignore_expires=True)

# ------------------------------
# Tapas API Helpers
# ------------------------------

GRAPHQL_URL = "https://tapas.io/graphQL"

def get_series_id(url_or_name: str):
    if url_or_name.startswith("http"):
        # full URL
        return url_or_name.split("/series/")[1].split("/")[0]
    return url_or_name


def fetch_series(series_id: str):
    query = """
    query SeriesData($seriesId: Int!, $page: Int!, $size: Int!) {
      series(id: $seriesId) {
        id
        title
        creator { name }
        episodes(page: $page, size: $size, sort: OLDEST) {
          entries {
            id
            title
            free
            isAccessible
          }
        }
      }
    }
    """
    variables = {"seriesId": int(series_id), "page": 1, "size": 5000}
    r = s.post(GRAPHQL_URL, json={"query": query, "variables": variables})
    r.raise_for_status()
    return r.json()["data"]["series"]


def fetch_episode_content(ep_id: int):
    url = f"https://tapas.io/episode/{ep_id}"
    r = s.get(url)
    r.raise_for_status()
    return r.text


def parse_comic_images(html):
    doc = pq(html)
    imgs = []
    # images are now in <img> with srcset or data-src
    for img in doc("img.content__img"):
        src = pq(img).attr("src") or pq(img).attr("data-src")
        if src:
            imgs.append(src.split("?")[0])  # strip query
    return imgs


def parse_novel_text(html):
    doc = pq(html)
    paras = []
    for p in doc("article.viewer__body p"):
        txt = pq(p).text()
        if txt:
            paras.append(txt)
    return "\n\n".join(paras)

# ------------------------------
# Main
# ------------------------------

basePath = Path(args.baseDir) if args.baseDir else Path(".")

for urlCount, url in enumerate(args.url):
    seriesName = get_series_id(url)
    try:
        series = fetch_series(seriesName)
    except Exception as e:
        printLine(f"Error fetching series {seriesName}: {e}")
        continue

    name = series["title"]
    author = series["creator"]["name"]
    episodes = series["episodes"]["entries"]

    printLine(f"Series: {name} by {author} ({len(episodes)} episodes)")

    savePath = basePath / check_path(f"{name} [{seriesName}]", fat=args.restrict_characters)
    if not savePath.exists():
        savePath.mkdir(parents=True)
        printLine(f"Created folder {savePath}")
    elif not args.force:
        printLine(f"Found existing folder {savePath}, skipping. Use -f to redownload.")
        continue

    # Loop episodes
    for ep_idx, ep in enumerate(episodes, 1):
        ep_id = ep["id"]
        ep_title = ep["title"]

        printLine(f"[{ep_idx}/{len(episodes)}] Downloading '{ep_title}' (id={ep_id})...", True)

        html = fetch_episode_content(ep_id)

        # Try to detect comic or novel
        imgs = parse_comic_images(html)
        if imgs:
            # save each image
            for img_idx, img_url in enumerate(imgs, 1):
                fname = check_path(
                    f"{lead0(ep_idx, len(episodes))} - {lead0(img_idx, len(imgs))} - {ep_title}.{img_url.split('.')[-1]}",
                    fat=args.restrict_characters
                )
                fpath = savePath / fname
                if not fpath.exists():
                    imgdata = s.get(img_url).content
                    with open(fpath, "wb") as f:
                        f.write(imgdata)
        else:
            # treat as novel
            text = parse_novel_text(html)
            fname = check_path(f"{lead0(ep_idx, len(episodes))} - {ep_title}.txt",
                               fat=args.restrict_characters)
            with open(savePath / fname, "w", encoding="utf-8") as f:
                f.write(text)

    printLine(f"Finished series: {name}")

printLine("All done!")
