# ご飯がすすむ 公式サイト

「ご飯がすすむ」の公式情報サイト。GitHub Pagesで公開しています。

## 構成

- `index.html` — サイト本体（画像はすべてインライン埋め込み）
- `data/site.json` — 動的データ（最新動画ID・X固定ポストURL）。ページ側のJSがこれを読み込んで表示する
- `scripts/update.py` — `data/site.json` を更新するスクリプト
- `.github/workflows/update.yml` — 毎朝 5:45 JST に `update.py` を実行し、変更があればコミットするGitHub Actions

## 自動更新の仕組み

1. 毎朝 5:45 JST — GitHub Actions が YouTubeチャンネルRSSから最新動画を取得し、X固定ポストの検出を試みて `data/site.json` を更新（X側の検出に失敗した場合は前回の値を維持）
2. 毎朝 6:00 JST — Claude の定期タスクが更新結果を確認し、問題があれば修復・報告

## フォールバック

- 最新動画: `data/site.json` が読めない場合、アップロード動画プレイリストの埋め込み（常に最新の投稿が先頭）を表示
- X固定ポスト: URL未設定・埋め込み失敗時は Xプロフィールへのリンクを表示

## 手動更新

X固定ポストを変更したときは、Claude（メインCH運用プロジェクト）に伝えれば `data/site.json` の `pinned_post.url` を書き換えて反映できます。サイト内容の変更も同様にClaudeに依頼できます。
