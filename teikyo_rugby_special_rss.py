import os
import sys
import time
import hashlib
import requests
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
from email.utils import format_datetime
from urllib.parse import urljoin


# ============================================================
# 設定
# ============================================================

BASE_URL = "https://www.teikyo-sports.jp"
LIST_URL = "https://www.teikyo-sports.jp/rugby/special/"

OUTPUT_FILE = "teikyo_rugby_special.xml"

FEED_TITLE = "帝京大学ラグビー部 SPECIAL"
FEED_LINK = LIST_URL
FEED_DESCRIPTION = "帝京大学ラグビー部 SPECIAL 新着記事RSS"

# 新着監視として十分な範囲。
# 1ページ20件なので3ページ＝最大60件を毎回確認する。
MAX_PAGES = 3

REQUEST_TIMEOUT = 30
REQUEST_INTERVAL = 1

JST = timezone(timedelta(hours=9))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/155.0.0.0 Safari/537.36"
    )
}


# ============================================================
# 補助関数
# ============================================================

def rss_date(dt):
    """datetimeをRSS用RFC 2822形式へ変換"""
    return format_datetime(dt)


def parse_date(text):
    """
    2026-10-20 のような掲載日をJSTのdatetimeへ変換。
    サイトには時刻がないため、00:00:00として扱う。
    """
    return datetime.strptime(text.strip(), "%Y-%m-%d").replace(tzinfo=JST)


def make_guid(url):
    """URLから安定したGUIDを作成"""
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def get_page(url):
    print(f"GET {url}")

    r = requests.get(
        url,
        headers=HEADERS,
        timeout=REQUEST_TIMEOUT
    )

    print(f"HTTP: {r.status_code} / {len(r.content)} bytes")

    r.raise_for_status()

    return r


# ============================================================
# 帝京大学SPECIAL一覧取得
# ============================================================

def fetch_articles():
    articles = {}
    successful_pages = 0

    for page_no in range(1, MAX_PAGES + 1):

        if page_no == 1:
            url = LIST_URL
        else:
            url = f"{LIST_URL}?pageID={page_no}"

        print()
        print(f"一覧ページ取得: {page_no}/{MAX_PAGES}")

        r = get_page(url)
        successful_pages += 1

        soup = BeautifulSoup(r.content, "html.parser")

        page_count = 0

        for tr in soup.find_all("tr"):

            date_td = tr.find("td", class_="cel1")
            title_td = tr.find("td", class_="cel3")

            if not date_td or not title_td:
                continue

            a = title_td.find(
                "a",
                href=lambda x: x and "/rugby/special/page/id=" in x
            )

            if not a:
                continue

            date_text = date_td.get_text(" ", strip=True)
            title = a.get_text(" ", strip=True)
            article_url = urljoin(BASE_URL, a.get("href"))

            try:
                published = parse_date(date_text)
            except ValueError:
                print(f"日付を解釈できないためスキップ: {date_text} / {title}")
                continue

            # URLをキーに重複排除
            articles[article_url] = {
                "title": title,
                "url": article_url,
                "published": published,
            }

            page_count += 1

        print(f"このページの記事取得件数: {page_count}")

        # 取得できなければ、HTML構造変更の可能性があるため停止
        if page_count == 0:
            raise RuntimeError(
                f"ページ{page_no}から記事を取得できませんでした。"
                "サイトのHTML構造が変更された可能性があります。"
            )

        if page_no < MAX_PAGES:
            time.sleep(REQUEST_INTERVAL)

    if successful_pages == 0:
        raise RuntimeError("一覧ページを1ページも取得できませんでした。")

    print()
    print(f"今回取得できたユニーク記事数: {len(articles)}")

    return articles


# ============================================================
# 既存RSS読込
# ============================================================

def load_existing_feed():
    existing = {}

    if not os.path.exists(OUTPUT_FILE):
        print("既存RSSなし：新規作成します")
        return existing

    try:
        tree = ET.parse(OUTPUT_FILE)
        root = tree.getroot()

        for item in root.findall("./channel/item"):

            title_el = item.find("title")
            link_el = item.find("link")
            pubdate_el = item.find("pubDate")

            if link_el is None or not link_el.text:
                continue

            url = link_el.text.strip()

            title = ""
            if title_el is not None and title_el.text:
                title = title_el.text.strip()

            published = None

            if pubdate_el is not None and pubdate_el.text:
                try:
                    from email.utils import parsedate_to_datetime

                    published = parsedate_to_datetime(
                        pubdate_el.text.strip()
                    )

                    if published.tzinfo is None:
                        published = published.replace(tzinfo=JST)

                    published = published.astimezone(JST)

                except Exception:
                    published = None

            existing[url] = {
                "title": title,
                "url": url,
                "published": published,
            }

        print(f"既存RSS件数: {len(existing)}")

    except Exception as e:
        raise RuntimeError(
            f"既存RSSの読み込みに失敗しました: {e}"
        )

    return existing


# ============================================================
# RSS生成
# ============================================================

def build_rss(articles):
    rss = ET.Element(
        "rss",
        {
            "version": "2.0",
        }
    )

    channel = ET.SubElement(rss, "channel")

    ET.SubElement(channel, "title").text = FEED_TITLE
    ET.SubElement(channel, "link").text = FEED_LINK
    ET.SubElement(channel, "description").text = FEED_DESCRIPTION
    ET.SubElement(channel, "language").text = "ja"
    ET.SubElement(channel, "lastBuildDate").text = rss_date(
        datetime.now(JST)
    )

    # 新しい順
    sorted_articles = sorted(
        articles.values(),
        key=lambda x: x["published"],
        reverse=True
    )

    for article in sorted_articles:

        item = ET.SubElement(channel, "item")

        ET.SubElement(
            item,
            "title"
        ).text = article["title"]

        ET.SubElement(
            item,
            "link"
        ).text = article["url"]

        guid = ET.SubElement(
            item,
            "guid",
            {
                "isPermaLink": "false"
            }
        )

        guid.text = make_guid(article["url"])

        ET.SubElement(
            item,
            "pubDate"
        ).text = rss_date(article["published"])

        ET.SubElement(
            item,
            "description"
        ).text = article["title"]

    tree = ET.ElementTree(rss)

    try:
        ET.indent(tree, space="  ")
    except AttributeError:
        pass

    tree.write(
        OUTPUT_FILE,
        encoding="utf-8",
        xml_declaration=True
    )

    print()
    print(f"保存完了: {OUTPUT_FILE} ({len(sorted_articles)}件)")


# ============================================================
# メイン処理
# ============================================================

def main():

    print("帝京大学ラグビー部 SPECIAL RSS生成")
    print("=" * 50)

    # 既存RSSを先に読み込む
    existing = load_existing_feed()

    try:
        current = fetch_articles()

    except Exception as e:

        print()
        print("記事一覧の取得に失敗しました。")
        print("既存RSSは変更しません。")
        print(f"エラー: {e}")

        sys.exit(1)

    # --------------------------------------------------------
    # 既存RSS＋今回取得分を累積
    # --------------------------------------------------------

    combined = dict(existing)

    new_count = 0

    for url, article in current.items():

        if url not in combined:
            new_count += 1

        # サイトの一覧に現在掲載されている記事については、
        # サイト側の日付・タイトルを最新情報として採用する。
        combined[url] = article

    print()
    print(f"今回取得した記事: {len(current)}")
    print(f"今回初めて確認した記事: {new_count}")
    print(f"累積RSS件数: {len(combined)}")

    # --------------------------------------------------------
    # 上位20件を確認表示
    # --------------------------------------------------------

    preview = sorted(
        combined.values(),
        key=lambda x: x["published"],
        reverse=True
    )

    print()
    print("--- RSS上位20件 ---")

    for i, article in enumerate(preview[:20], 1):

        print(
            f"{i}. "
            f"{article['published'].strftime('%Y-%m-%d')} "
            f"{article['title']}"
        )

        print(article["url"])

    # --------------------------------------------------------
    # RSS保存
    # --------------------------------------------------------

    build_rss(combined)


if __name__ == "__main__":
    main()