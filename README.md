# TaMap

**タスクをつなぎ、未来を描く。**

TaMap（タマップ）は、Grok Bot の 4 体がプロジェクトのタスクと依存関係を分析し、その結果をチャットのタスクマップ（mermaid）として更新し続ける会話型の支援システムです。

話しかける相手は **TaMap PM**（Grok Bot のメインBot）だけです。PM が Map Architect、Risk Analyst、Quality Reviewer に分析を頼み、MCP ツールが返す mermaid と GIF をチャットに貼ります。状態の正本は `data/maps/{map_id}.json` で、中身が変わったときだけ同じ `map_id` の `revision` が 1 つ上がります。

4 体のドット絵が記録に合わせて動く閲覧専用ページは、`http://127.0.0.1:8765/live/{map_id}` です（[docs/LIVE_VIEW.md](docs/LIVE_VIEW.md)）。

> **2026-10-11 JST 時点。** Grok Bot 上で、stdio MCP の呼び出し、4 体の一周、チャットの mermaid と GIF、box 内のライブページまで動作を確認しています。ライブページの外部公開と、90 秒デモのリハーサルはまだです。

## 名前

**TaMap = Task-aware Multi-Agent Planning。** タスクと依存・進捗を理解し、役割の違う Bot が協力し、根拠のある次の行動を出します。「Task + Map（タスクの地図）」でもあります。

## 4 体のキャラクター

見た目と口調の正本は `tamap/persona.py` です。GIF、稼働図、Bot の指示文はここに合わせます。体は共通の丸いロボットで、色とモチーフで見分けます。

| Bot | 役割 | 見た目 | 口調の例 |
| --- | --- | --- | --- |
| 📋 **TaMap PM** | まとめ役。対話、依頼、MCP の呼び出し、結果の投稿 | 藍色。旗つきアンテナとヘッドセット | 「まかせてください！」 |
| 🗺️ **Map Architect** | 地図職人。タスクと依存関係への分解 | 青緑。黄色いヘルメットと巻いた地図 | 「地図、できたっす！」 |
| ⚠️ **Risk Analyst** | 心配性の探偵。遅延の起点と対処案 | 琥珀色。虫めがねと「！」のアンテナ | 「ここ、あやしいかも…」 |
| ✅ **Quality Reviewer** | 赤ペン先生。断定しすぎ・根拠の弱さ・計算との食い違いを、直す前→直した後で返す | ピンク。赤ペンとチェックのバッジ | 「ちょっとだけ直すね」 |

口調を使うのはふきだし・挨拶・レビュー見出しの 1 行です。結論、3 アクション、推定・未確認は、事実が分かる普通の文で書きます。

## しくみ

```text
ユーザー
  │ チャット（Markdown / mermaid / GIF / 質問ボタン 最大6）
  ▼
TaMap PM                         Grok Bot のメインBot。create_map / update_map はここだけ
  │ teammate。日本語の依頼文 + ```json フェンス 1 つ（メッセージ全体は JSON にしない）
  ├── 🗺️ Map Architect          tasks
  ├── ⚠️ Risk Analyst            起点 ID と対処案
  └── ✅ Quality Reviewer        before / text / reason
  │ stdio MCP（登録できないときは scripts/tamap_cli.sh）
  ▼
scripts/mcp_server.sh  →  python -m tamap.mcp_server
  FastMCP。実装上の名前は tamap。Grok Bot に登録したコネクタ名は tamap-v2
  ├── tamap/core.py       検証、遅延の到達先、合流点、ボトルネック、クリティカルパス候補
  ├── tamap/store.py      data/maps/{map_id}.json（fcntl ロックのあと一時ファイルを os.replace）
  ├── tamap/handoff.py    専門Botの返信から JSON を 1 つ読む（ツール parse_handoff）
  ├── tamap/render.py     チャットに貼る mermaid
  ├── tamap/persona.py    役割・色・口調
  ├── tamap/sprites.py    16×14 のドット絵
  └── tamap/animate.py    out/{map_id}_flow.gif と out/tamap_team.gif

scripts/live_view.sh  →  python -m tamap.live     標準ライブラリの http.server + SSE
  http://127.0.0.1:8765/live/{map_id}
  data/maps を 0.2 秒ごとに見るだけ。GET / HEAD 以外は 405。描画は sprites / persona / animate と共通
```

- 入口は PM です。専門Botは PM への返信だけを返します。
- ID の参照、循環、到達できる後続、ボトルネックは `tamap/core.py` が計算します。所要日数が未入力のときは、到達できる後続だけを返します。
- 正本は `data/maps/{map_id}.json` です。`expected_revision` が現在と違う更新は `revision_conflict` で拒否します。正規化のあとで tasks / analysis / title が同じ `update_map` は、ファイルを書き換えず revision を維持します。
- 送ったチャットは書き換えられないので、途中の状態は `set_bot_status` に残し、結果の投稿で流れの GIF を 1 本添付します（[docs/UX_DESIGN.md](docs/UX_DESIGN.md)）。

タスクマップの見方: 完了は緑、進行中は青、未着手は灰、ブロック中は橙、検証エラーは赤、遅延の影響は黄。◆は合流点、▲はボトルネック（破線の太枠）、クリティカルパス候補は太線（`==>`）。存在しない参照と循環は赤の破線です。

## クイックスタート（Grok Bot の box）

指示文が参照する配置は `/workspace/tamap` です。別のディレクトリに clone したときは、指示文のパスをその場所に読み替えます。

```bash
cd /workspace/tamap
uv sync                          # .venv（mcp, pillow）
```

1. **MCP を登録する。** コマンドは `/workspace/tamap/scripts/mcp_server.sh`、トランスポートは stdio。動作確認したコネクタ名は `tamap-v2`（確認時の表示は 10 ツール。コードの `list_tools` は 11。下記）。
2. **ライブページ（任意）。** `scripts/live_view.sh` を tmux などで常駐させる。既定は `127.0.0.1:8765`。URL は `get_live_url`。`TAMAP_LIVE_TOKEN` を置くと `?token=` が必要になる。
3. **Bot を 4 体作る。** 指示文は [docs/GROKBOT_INTEGRATION.md](docs/GROKBOT_INTEGRATION.md) から、それぞれの Bot に入れる。
   - 5.1 TaMap PM（メインBot。ユーザーはここにだけ話す）
   - 5.2 Map Architect
   - 5.3 Risk Analyst
   - 5.4 Quality Reviewer
4. **サンプルを渡す。** PM に `samples/readme_example.json` のタスクを送る。ボタンの文は「サンプル（タスク管理アプリ T1〜T7）で試す」。

MCP を登録できないときは、同じ関数をシェルから呼びます。標準出力がチャット用テキスト、標準エラー出力が structuredContent、ツールのエラーは終了コード 1 です。ツール名の許可リストはサーバーの `list_tools` から作ります。

```bash
scripts/tamap_cli.sh list_maps
scripts/tamap_cli.sh simulate_delay '{"map_id":"…","task_id":"T4"}'
scripts/tamap_cli.sh create_map < /tmp/tamap_args.json
```

| 変数 | 既定 | 用途 |
| --- | --- | --- |
| `TAMAP_DATA_DIR` | `data/maps` | マップ JSON |
| `TAMAP_OUT_DIR` | `out` | GIF |
| `TAMAP_FONT` | 自動（Noto Sans CJK / IPA / WenQuanYi） | GIF の日本語 |
| `TAMAP_LIVE_HOST` / `TAMAP_LIVE_PORT` | `127.0.0.1` / `8765` | ライブページ |
| `TAMAP_LIVE_BASE_URL` | 上記から組み立て | URL の先頭（公開したとき） |
| `TAMAP_LIVE_TOKEN` | なし | ライブページの `?token=` |

## MCP ツール

`python -m tamap.mcp_server` の `list_tools` は次の 11 個です。`tests/e2e_mcp.py` がこの集合を確認します。

Grok Bot での動作確認（2026-10-11）では、コネクタ名 `tamap-v2`、**10 ツール**として登録され、呼び出せました。コードの 11 個との差は `parse_handoff` です（PR #3 で追加済み。接続が古い一覧を覚えているときは、登録を読み直すとこのツールも出ます）。

| ツール | 内容 | revision |
| --- | --- | --- |
| `create_map(title, tasks, analysis?, source?)` | 新規作成。検証エラーがあっても保存し、図の中で赤く示す。structuredContent に `live_url` | 1 |
| `update_map(map_id, expected_revision, tasks?, analysis?, source?, title?)` | tasks / analysis / title を全体置換。正規化後に同じなら「変更なし（revision N のまま）」、`unchanged: true`。変わったときだけ差分の 1 行と `diff`。`expected_revision` が違うときは、中身が同じでも `revision_conflict` | 変わったときだけ +1 |
| `get_map(map_id)` | 現在の図。structuredContent に tasks と analysis | 不変 |
| `simulate_delay(map_id, task_id)` | What-if。遅延元を太枠、影響を受けるタスクとエッジを黄で示す。保存しない | 不変 |
| `list_maps()` | map_id の一覧 | — |
| `set_bot_status(map_id, bot, status, note?, say?)` | 稼働図を返す。bot は `pm` / `map_architect` / `risk_analyst` / `quality_reviewer`、status は `idle` / `working` / `done` / `error`。専門Botが `working` になると PM は自動で `idle`（「〜の結果待ち」）。`say` は 30 文字までのふきだし。引数が無い接続では `note` の `｜ say:一言` または `{"note","say"}` | 不変 |
| `parse_handoff(text, role?)` | 専門Botのプレーンテキストから JSON を 1 つ取る（前置き、json フェンス、末尾カンマ、スマートクォートを除く）。role は `map_architect` / `risk_analyst` / `quality_reviewer`。成功時は `structuredContent.data` を使う。この 1 行はユーザーには貼らない | — |
| `get_status(map_id)` | 稼働図（ユーザー → PM → 3 体 → PM）と直近の履歴 | 不変 |
| `render_flow_gif(map_id)` | 直近 1 周を `out/{map_id}_flow.gif` に書き、パスを返す | 不変 |
| `get_live_url(map_id)` | ライブページの URL と、サーバーが起動しているか（`running`） | 不変 |
| `render_team_card()` | チーム紹介の `out/tamap_team.gif`。PM の最初の挨拶に添付する | — |

`update_map` がチャット用に返すテキストの形:

````text
変更点：T3 進行中→完了 ／ ボトルネック：変化なし（T4） ／ 影響先：変化なし（T6・T7）

```mermaid
graph LR …
```
revision 3 ・ map_id `…` ・ 更新 13:58:10 JST ・ 検証OK
````

各ツールの実戻り値は [docs/sample_output.md](docs/sample_output.md) にあります。

## チャットでの流れ

詳しい文面は [docs/UX_DESIGN.md](docs/UX_DESIGN.md) です。

- 1 回の分析で PM の投稿は 2 つです。開始の 1 行（担当の順）と、結果の 1 通。途中の稼働図は投稿しません。
- 結果の順は、結論、（あれば）矛盾・検証エラー、タスクマップ（ツールの mermaid をそのまま）、次の 3 アクション、レビューで直した点（直す前→直した後。0 件なら「指摘なし」）、推定・未確認、流れの GIF、質問ボタンです。
- 「T4が遅れたら？」は `simulate_delay` だけです。保存しないので revision は変わりません。
- 「T3を完了にする」は `update_map` だけです。中身が変わったときだけ revision が上がり、差分の 1 行が付きます。`unchanged: true` のときは「rev N → N+1」と書きません。
- ボタンの文は、押すとそのままユーザーの発言になります。チーム全体の再分析は「チームで再分析」のときだけです。
- 開始の案内文は「約 1 分半」です。README サンプルの実測は下の動作確認のとおり、約 61〜80 秒でした。

## サンプル

`samples/readme_example.json`（タスク管理アプリ）:

- T1 要件整理：完了、依存なし
- T2 UI設計：完了、T1 に依存
- T3 DB設計：進行中、T1 に依存
- T4 API実装：未着手、T3 に依存
- T5 画面実装：進行中、T2 に依存
- T6 統合テスト：未着手、T4 と T5 に依存
- T7 リリース：未着手、T6 に依存

`tamap/core.py` の計算（テストで確認）: 合流点は T6。T4 が遅れると影響するのは T6・T7。クリティカルパス候補は T1→T3→T4→T6→T7。ボトルネック候補は T3。所要時間は未入力なので、これは未完了タスクを重み 1 とした最長チェーンです。

`samples/broken_example.json` は、重複 ID、存在しない参照（T9）、T6⇄T7 の循環を検出します。循環があるときはクリティカルパスを計算しません。

## 動作確認

### 動作確認済み（2026-10-11 JST、Grok Bot）

- [x] チャットが mermaid（classDef、linkStyle、破線・太線、`<br>`）を描画し、GIF 添付を再生する
- [x] stdio MCP を登録して呼び出せた（コネクタ名 `tamap-v2`、10 ツール）。`scripts/tamap_cli.sh` も代替として動いた
- [x] 4 体（TaMap PM、Map Architect、Risk Analyst、Quality Reviewer）が README サンプルで一周を完走した。1 回目 約 80 秒、2 回目 約 61 秒（専門Botは各 約 13〜15 秒）。タイムアウトも revision の競合もなし。`say` は 8/8 渡った。中身が同じ更新は revision を維持した。流れの GIF（約 24〜26 秒）を生成した
- [x] 閲覧専用ライブページ（`http://127.0.0.1:8765/live/{map_id}`）が、Bot の状態記録に合わせて box のブラウザでリアルタイムに更新された

### 動作確認済み（テスト）

- [x] 重複 ID、存在しない参照、自己依存、循環、不正な状態を検出する（`tests/test_core.py`）
- [x] 遅延したタスクから到達できる後続を計算する。README 例は T4 → T6・T7
- [x] Quality Reviewer の指摘（before / text / reason）をマップに保存する
- [x] 同じ `map_id` で、変わった更新だけ revision が上がり、差分の 1 行が付く。古い revision は拒否する。中身が同じ更新は revision を維持する
- [x] 専門Botが作業中になると PM が自動で待機になる。流れの GIF とチーム紹介の GIF を書き出せる
- [x] ライブページは GET / HEAD だけを受け、それ以外は 405 で、マップのファイルは変わらない

### 未確認

- [ ] ライブページの外部公開（候補は [docs/LIVE_VIEW.md](docs/LIVE_VIEW.md)。いずれも未実施）
- [ ] 90 秒デモのリハーサル（台本は [docs/UX_DESIGN.md](docs/UX_DESIGN.md) の 7 章）
- [ ] 書き込みの認証。今の境界は、stdio MCP を起動できる人（box に入れる人）が書けること。`TAMAP_LIVE_TOKEN` はライブページの閲覧用
- [ ] 稼働図の絵文字と顔文字が、Grok Bot の mermaid で崩れずに出るか（classDef 等は確認済み）
- [ ] routine からの再評価。GitHub の Issue / PR をマップの入力にすること

指示文とつなぎ方の詳細は [docs/GROKBOT_INTEGRATION.md](docs/GROKBOT_INTEGRATION.md)、実装時の確認メモは [docs/IMPLEMENTATION_NOTES.md](docs/IMPLEMENTATION_NOTES.md) です。実機で確認できた範囲は、この「動作確認」が 2026-10-11 時点の結果です。

## ロードマップ

- ライブページを box の外から開く。サーバーは 127.0.0.1 のまま、トンネルで転送し、`TAMAP_LIVE_TOKEN` を必須にする
- [90 秒デモ](docs/UX_DESIGN.md) を台本どおり通す（本番で回すのは What-if と状態変更。一周は事前に済ませる）
- PM の routine で、ブロック中のタスクがあり、最終更新から時間がたっているマップだけ、1 行とボタンを出す。routine から `update_map` は呼ばない
- GitHub の Issue / PR をタスクとして取り込む。コードを書いて PR を出す Bot は、分析の 4 体とは別にする
- 工数・期限が入力されたときの、遅延日数の計算

## テスト

```bash
uv run python -m unittest tests.test_core tests.test_handoff
uv run python tests/e2e_mcp.py
# 任意。Chrome と puppeteer-core が必要（docs/LIVE_VIEW.md）
# node tests/live_browser.js <base_url> <data_dir> <map_id> <out_dir>
```

---

**TaMap — タスクをつなぎ、未来を描く。**
