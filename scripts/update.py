#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
毎朝の自動更新スクリプト（GitHub Actionsから実行）
- YouTube最新動画: チャンネルRSSから取得（確実）
- X固定ポスト: syndication系エンドポイントから検出を試みる（ベストエフォート、
  失敗時は前回の値を維持）
標準ライブラリのみ使用。
"""
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree

CHANNEL_ID = "UC9DMzlsk9q_8kB-1fK8J3Zw"
X_SCREEN_NAME = "ahirugohan084"
DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "site.json"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def http_get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ja,en;q=0.8"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def fetch_rss_entries(n=15):
    """YouTubeチャンネルRSSから最新n件のエントリを返す（新しい順）。"""
    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={CHANNEL_ID}"
    xml = http_get(url)
    ns = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}
    root = ElementTree.fromstring(xml)
    out = []
    for entry in root.findall("a:entry", ns):
        vid = entry.findtext("yt:videoId", namespaces=ns)
        if not vid:
            continue
        title = entry.findtext("a:title", namespaces=ns)
        published = entry.findtext("a:published", namespaces=ns)
        out.append({"id": vid, "title": title or "", "published": published or ""})
        if len(out) >= n:
            break
    if not out:
        raise RuntimeError("RSS feed has no entries")
    return out


def fetch_latest_videos(n=5):
    """表示用の最新n件（後方互換）。"""
    return fetch_rss_entries(n)


def _json_str(raw):
    """JSON文字列リテラルのエスケープ（\\uXXXX, \\/ など）を復元する。"""
    try:
        return json.loads('"' + raw + '"')
    except Exception:
        return raw


def fetch_upcoming_lives(candidate_ids, max_check=12):
    """候補の動画IDについてwatchページを調べ、開始予定の配信（プレミア含む）を返す。
    APIキー不要。watchページの ytInitialPlayerResponse から
    isUpcoming / startTimestamp / タイトル を抽出する。開始予定時刻の昇順で返す。"""
    lives = []
    now = datetime.now(timezone.utc)
    for vid in candidate_ids[:max_check]:
        try:
            html = http_get(f"https://www.youtube.com/watch?v={vid}")
        except Exception as e:
            print(f"[lives] watch fetch failed {vid}: {e}")
            continue
        if '"isUpcoming":true' not in html:
            continue  # 通常の過去動画・配信中はスキップ
        st = re.search(r'"startTimestamp":"([^"]+)"', html)
        if not st:
            print(f"[lives] {vid} isUpcoming but no startTimestamp")
            continue
        try:
            dt = datetime.fromisoformat(st.group(1))
        except Exception:
            print(f"[lives] {vid} bad startTimestamp: {st.group(1)!r}")
            continue
        if dt <= now:
            continue  # 開始時刻を過ぎている
        tm = re.search(r'"videoDetails":\{.*?"title":"((?:[^"\\]|\\.)*)"', html, re.S)
        title = _json_str(tm.group(1)) if tm else ""
        lives.append({
            "video_id": vid,
            "title": title,
            "start": st.group(1),
            "url": f"https://www.youtube.com/watch?v={vid}",
        })
        print(f"[lives] upcoming: {vid} {title!r} @ {st.group(1)}")
    lives.sort(key=lambda x: x["start"])
    return lives


def _walk(obj, found):
    """JSONを再帰的に歩いてツイートらしきオブジェクトを収集する。"""
    if isinstance(obj, dict):
        keys = obj.keys()
        if ("id_str" in keys or "rest_id" in keys) and ("full_text" in keys or "text" in keys or "legacy" in keys):
            found.append(obj)
        for v in obj.values():
            _walk(v, found)
    elif isinstance(obj, list):
        for v in obj:
            _walk(v, found)


def fetch_pinned_post():
    """X固定ポストのURL検出を試みる。見つからなければNone。"""
    url = f"https://syndication.twitter.com/srv/timeline-profile/screen-name/{X_SCREEN_NAME}"
    try:
        html = http_get(url)
    except Exception as e:
        print(f"[pinned] timeline-profile fetch failed: {e}")
        return None

    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        print("[pinned] __NEXT_DATA__ not found")
        return None
    try:
        data = json.loads(m.group(1))
    except Exception as e:
        print(f"[pinned] JSON parse failed: {e}")
        return None

    # 1) 明示的なpinnedフラグ/セクションを探す
    blob = m.group(1)
    tweets = []
    _walk(data, tweets)
    print(f"[pinned] tweet-like objects found: {len(tweets)}")

    def tweet_id(t):
        return t.get("id_str") or t.get("rest_id") or (t.get("legacy") or {}).get("id_str")

    for t in tweets:
        for key in ("pinned", "is_pinned", "isPinned"):
            if t.get(key):
                tid = tweet_id(t)
                if tid:
                    print(f"[pinned] found via flag '{key}': {tid}")
                    return f"https://x.com/{X_SCREEN_NAME}/status/{tid}"

    # 2) pinnedEntry / pinned_tweet_ids のような構造を探す
    m2 = re.search(r'"pinned[_A-Za-z]*"\s*:\s*\[?\s*"?(\d{10,25})', blob)
    if m2:
        print(f"[pinned] found via pinned key pattern: {m2.group(1)}")
        return f"https://x.com/{X_SCREEN_NAME}/status/{m2.group(1)}"

    print("[pinned] no pinned marker found in timeline data")
    return None


def main():
    data = {}
    if DATA_PATH.exists():
        data = json.loads(DATA_PATH.read_text(encoding="utf-8"))

    changed = []

    # --- YouTube ---
    entries = None
    try:
        entries = fetch_rss_entries(15)
        latests = entries[:5]
        old_ids = [v.get("id") for v in data.get("latest_videos", [])]
        new_ids = [v["id"] for v in latests]
        if old_ids != new_ids:
            changed.append(f"latest_videos -> {new_ids[0]} (+{len(new_ids)})")
        data["latest_videos"] = latests
        data["latest_video"] = latests[0]  # 後方互換（メイン埋め込み用）
        print(f"[youtube] latest: {latests[0]['id']} {latests[0]['title']!r} ({len(latests)} videos)")
    except Exception as e:
        print(f"[youtube] FAILED: {e} (keeping previous value)")

    # --- 今後のライブ配信（お知らせ自動掲載用） ---
    if entries is not None:
        try:
            lives = fetch_upcoming_lives([e["id"] for e in entries])
            old_lives = [v.get("video_id") for v in data.get("upcoming_lives", [])]
            new_lives = [v["video_id"] for v in lives]
            if old_lives != new_lives:
                changed.append(f"upcoming_lives -> {new_lives if new_lives else '(none)'}")
            data["upcoming_lives"] = lives
            print(f"[lives] {len(lives)} upcoming live(s)")
        except Exception as e:
            print(f"[lives] FAILED: {e} (keeping previous value)")
    else:
        print("[lives] skipped (RSS unavailable, keeping previous value)")

    # --- X pinned post ---
    pinned_url = fetch_pinned_post()
    if pinned_url:
        if data.get("pinned_post", {}).get("url") != pinned_url:
            changed.append(f"pinned_post -> {pinned_url}")
            data["pinned_post"] = {"url": pinned_url}
        data.setdefault("pinned_post", {})["detected_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    else:
        print("[pinned] keeping previous value")

    if changed:
        data["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    DATA_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("changes:", "; ".join(changed) if changed else "none (timestamp only)")


if __name__ == "__main__":
    sys.exit(main())
