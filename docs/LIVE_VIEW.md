# TaMap ライブページ（閲覧専用）

`set_bot_status` の記録（`bot_history`）に合わせて、4 体のドット絵キャラがリアルタイムに動くページ。Yuu さんの決定（2026-10-11）による、「チャット内で完結」の方針の **例外** として追加した閲覧専用の機能。チャットの流れ（分析 1 回につき投稿 2 つ、結果の GIF）は変えない。ライブページは「見たい人が、別の画面で見られる」おまけの位置づけ。

## 使い方

```bash
scripts/live_view.sh                    # 既定：127.0.0.1:8765 で待ち受け（box の中からだけ開ける）
scripts/live_view.sh --port 9000        # ポートを変える
TAMAP_LIVE_TOKEN=xxxx scripts/live_view.sh   # すべてのページで ?token=xxxx を必須にする
```

- **ページ**：`http://127.0.0.1:8765/live/{map_id}`。`/` は map の一覧。
- **常駐のさせ方**：box 上で tmux などを使って常駐させる想定。
- **ストア**：MCP サーバーと同じ `data/maps/`（`TAMAP_DATA_DIR`）を読む。
- **URL の取り方**（PM 用）：
  - MCP ツール `get_live_url(map_id)` が 1 行で URL を返す。サーバーが起動していなければ、その旨も書く。
  - `create_map` の structuredContent にも `live_url` が入る（チャット用のテキストは変えていない）。
  - URL の先頭部分は `TAMAP_LIVE_BASE_URL` で上書きできる（外部に公開した場合など）。

## しくみ

- **依存**：標準ライブラリだけ（`http.server` の `ThreadingHTTPServer` と Server-Sent Events）。ファイルは `tamap/live.py`。
- **読み取り専用**：
  - サーバーは `store.read_map` で JSON を読むだけで、書き込む処理を持たない。
  - 受け付ける HTTP メソッドは GET と HEAD だけ。POST・PUT・DELETE・PATCH・OPTIONS には 405 を返す。
  - `map_id` はストアと同じ正規表現で検証し、それ以外のパスは 404 にする。
- **更新を届ける方法**：
  - `/events/{map_id}`（SSE）の接続ごとに、0.2 秒間隔でファイルの stat（mtime・サイズ・inode）を見る。ストアはアトミックに置き換えるので、変化したらスナップショットを 1 件送る。
  - 接続した直後にも、今の状態を 1 件送る。15 秒ごとに keep-alive（ハートビート）を送る。
  - 届くのは、bot の状態、`bot_history`、`say`（ふきだし）、タスクマップ（状態・ボトルネック・検証エラー）、revision。
- **GIF と同じ見た目**：
  - ドット絵は、`sprites.bot_pixels()` が返す「格子の位置と色」のリストを `/api/scene` でそのまま渡し、canvas に同じ順番で塗る。
  - 配置の数値（960×540 の座標、各Botの x 座標、スプライトの倍率、ふきだし・字幕の位置）と、タスクの配置（`animate.task_layout`）も、GIF と同じ関数・定数を使う。
  - 高解像度の画面では、canvas を整数倍（`round(devicePixelRatio)`）で描く。こうするとドット 1 つが必ず整数のピクセルに乗り、にじまない。
- **表現**（GIF と同じ）：
  - 光るのは作業中の 1 体だけ。青い枠が付き、跳ねて、キラッと光り、まばたきする。
  - 待機中のBotはうすくなって「zZ」。完了は笑顔、エラーは「> <」と汗。
  - 一番新しい記録のBotが、ふきだしで一言しゃべる（`say` が無ければ口ぐせ）。
  - 新しい記録が届いたら、封筒が飛ぶ：依頼は PM→専門Bot（青）、結果は専門Bot→PM（黄）、エラーは赤。
  - Quality Reviewer が完了したら、「指摘N件 → PMが修正」のバッジを出す。
  - 下に、直近 8 件の履歴を表示する。

## 確認したこと（開発用 VM で実行）

**unittest**（`tests/test_core.py` の `test_live_page_read_only_and_sse`）
- `/live/{id}`・`/api/maps/{id}`・`/api/scene` が返る。
- 5 種類の書き込みメソッド × 4 つのパスがすべて 405 になり、map のファイルは 1 バイトも変わらない。データのディレクトリに新しいファイルもできない。
- 不正なパスは 404 になる。
- SSE：接続した直後のスナップショットが届く。`set_bot_status` の後と `update_map` の後に、新しいスナップショットが 3 秒以内に届く。
- `TAMAP_LIVE_TOKEN` を設定すると、トークンが無い・違うときは 403、正しいときは 200 になる。

**e2e**（`tests/e2e_mcp.py`）
- `scripts/live_view.sh` を起動できる。
- `create_map` の `live_url` と `get_live_url` が同じ URL を返す。`running` は、起動前が false、起動後が true になる。
- 書き込みメソッドは 405 になり、ファイルは変わらない。
- `tamap_cli.sh set_bot_status` で記録すると、SSE で `say` まで届く。

**headless Chrome**（`tests/live_browser.js`。Chrome と `puppeteer-core` が必要で、必須のテストではない）
- 5 つのステップで状態を変え、どれもページに届いた。CLI の起動を含めて約 0.4〜0.5 秒。
- ステップごとにスクリーンショットを保存した。
- canvas のドット絵を、Map Architect（完了）と Quality Reviewer（エラー）について、格子 1 マスずつ `bot_pixels` の色と照合した。表示倍率 1 と 2 の両方で、ずれは 0 だった。
- コンソールのエラーは 0。

## 未確認（Grok Bot の box 上）

- Grok Bot の box でライブページのサーバーを常駐させられるか（tmux などのプロセスが残るか）。
- box の中に、ユーザーが画面を見られるブラウザがあるか。
- box の Chrome・フォントで、同じように描画されるか。

## 外部に公開する方法（すべて未確認・未実施）

いずれもまだ試していない。どれを使う場合も、`TAMAP_LIVE_TOKEN` を設定し、サーバーは 127.0.0.1 で待ち受けたままにして、トンネルから 127.0.0.1:8765 に転送する形にすること。

1. **SSH のポート転送**：利用者の PC から `ssh -L 8765:127.0.0.1:8765 <box>` で転送し、PC のブラウザで開く。
   - 外から box に SSH でつなげるかは未確認。
2. **cloudflared の quick tunnel を HTTP/2 で使う**：前回の失敗は、外向きの 7844 番（QUIC/UDP）が封じられていたことが原因だった（IMPLEMENTATION_NOTES）。`cloudflared tunnel --protocol http2 --url http://127.0.0.1:8765` なら TCP 443 を使うので、通る可能性がある。
   - 未確認。また SSE が途中で切られないかも未確認。
3. **Tailscale**（tailnet 内で共有する、または Funnel で公開する）：box で tailscaled（ユーザー空間ネットワークでもよい）が動くか、外向きの通信が許されるかは未確認。
4. **ngrok などのトンネルサービス**：アカウントが必要。外向きの通信と SSE の扱いは未確認。
5. **Grok Bot 自身に、ポートを公開・プレビューする機能があるか**：与えられた前提には無いので、不明。

**公開するときの注意**
- 書き込み用のエンドポイントは無い。それでも、URL を知っている人にはタスクとBotのメモが見える。そのためトークンを必須にする。
- トークンは URL に入るので、ページは `Referrer-Policy: no-referrer` を返している。
- トンネルのログやチャット上でトークンが漏れないかにも注意する。
