# TaMap 🗺️

**タスクをつなぎ、未来を描く。**

TaMap（タマップ）は、**Grok Bot の AI チームがプロジェクトのタスクと依存関係を分析し、その結果をチャットの中のタスクマップ（mermaid）として更新し続ける**、会話型のプロジェクト支援システムです。

ユーザーが話しかけるのは **TaMap PM（Grok Bot のメインBot）だけ** です。PM が 3 体の専門Bot（Map Architect／Risk Analyst／Quality Reviewer）に分析を頼み、TaMap の MCP ツールが返す mermaid 図と GIF を、そのままチャットに貼ります。入力から結果、追加の質問までがチャットの中で完結します。例外として、4 体のキャラがリアルタイムに動く **閲覧専用のライブページ**（box 内の `http://127.0.0.1:8765/live/{map_id}`）を別に用意しています（[docs/LIVE_VIEW.md](docs/LIVE_VIEW.md)）。書き込みや操作はできません。

> **現在の状態：ハッカソン MVP。** TaMap Core と stdio MCP サーバーは実装済みで、テストで動作を確認しています。Grok Bot の 4 体の連携は、指示文の案（[docs/GROKBOT_INTEGRATION.md](docs/GROKBOT_INTEGRATION.md)）までです。何を確認したかは下の「検証チェックリスト」を見てください。

## 名前の由来

**TaMap = Task-aware Multi-Agent Planning**

- **Task-aware**：タスクと依存関係、進捗状況を理解する
- **Multi-Agent**：専門性の異なる複数のBotが協力する
- **Planning**：根拠に基づき次の行動を計画する

「**Task + Map**（タスクの地図）」の意味も込めています。

## 解決したい課題

タスク一覧だけでは、何が終わらないと次に進めないか、遅延がどこに波及するか、今何を優先すべきかが分かりづらくなります。また、会話の中だけで分析すると、更新前後の状態やBotの判断根拠を追いづらくなります。

TaMap は **会話による分析** と、**同じ map_id で revision を上げていく共有状態** を組み合わせて、この課題を解決します。

## AIチーム構成

| Bot | 役割 | 主な出力 |
| --- | --- | --- |
| **TaMap PM（Grok Bot のメインBot）** | ユーザーとの対話、専門Botへの依頼、結果の統合、MCPツールの呼び出し | 結論・タスクマップ・次の3アクション・ボタン |
| **Map Architect** | タスク分解と依存関係の整理 | タスク・依存関係の構造化データ |
| **Risk Analyst** | ボトルネックと遅延の波及を分析 | 影響の起点・対処案 |
| **Quality Reviewer** | 根拠・断定しすぎ・矛盾を確認 | 「直す前→直した後」の指摘 |

TaMap PM はメインBotそのものです。メインBotとPMを別々のBotとして置くことはしません。

## 主な機能

1. **Task Mapping**：タスクと依存関係を mermaid のタスクマップで表示する（状態の色、合流点、ボトルネック、クリティカルパス候補）。
2. **Bottleneck Analysis**：後続タスクへの影響が大きいタスクを、コードで計算する。
3. **What-if Simulation**：「T4 が遅れたら？」に対して、到達できる後続タスクを黄色で示す（保存はしない）。
4. **Action Planning**：PM が次の行動を最大 3 件提案する（ツール側でも 4 件以上は受け付けない）。
5. **Quality Check**：重複ID、存在しない参照、自己依存、循環、不正な状態をコードで検出し、図の中で赤く示す。Quality Reviewer の指摘は「直す前→直した後」の形で保存する。
6. **revision と差分**：更新は同じ `map_id` の `revision` を 1 つ上げる。古い revision からの更新は拒否する。更新すると、変更点・ボトルネック・影響先の差分が 1 行で返る。
7. **流れのGIF**：Bot の状態の履歴（`bot_history`）から、PM→Map Architect→Risk Analyst→Quality Reviewer→PM の 1 周をレトロなドット絵の GIF にする。
8. **キャラクター**：4 体はそれぞれ色・モチーフ・口調を持つキャラクター（📋まとめ役／🗺️地図職人／⚠️心配性の探偵／✅赤ペン先生）。GIF のふきだし、チーム紹介の GIF、稼働図の顔文字に出る（`tamap/persona.py`、詳細は docs/GROKBOT_INTEGRATION.md 3.5 章）。

入力されていない数値（所要日数など）は計算しません。推定と未確認の事項は、そう分かるように書きます。

## アーキテクチャ

```text
ユーザー
   │ チャット（Markdown / mermaid / GIF / 質問ボタン）
   ▼
TaMap PM（Grok Bot のメインBot）
   ├── 🗺️ Map Architect   ─┐
   ├── ⚠️ Risk Analyst      ├── 分析結果（teammate メッセージ）
   └── ✅ Quality Reviewer ─┘
   │ MCP ツール呼び出し（stdio）
   ▼
TaMap MCP サーバー（scripts/mcp_server.sh → tamap/mcp_server.py, FastMCP）
│  ツール：create_map / update_map / get_map / simulate_delay / list_maps /
│          set_bot_status / get_status / render_flow_gif / render_team_card /
│          get_live_url / parse_handoff
│  （MCP を登録できないときは scripts/tamap_cli.sh で同じツールをシェルから呼ぶ）
   ├── TaMap Core（tamap/core.py）  検証・影響計算・ボトルネック（LLM 不使用）
   ├── 共有ストア（tamap/store.py） data/maps/{map_id}.json（revision・履歴・Bot状態）  ← 書き込むのはここだけ
   ├── mermaid 生成（tamap/render.py）
   ├── キャラクター（tamap/persona.py 設定・口調、tamap/sprites.py ドット絵）
   └── GIF 生成（tamap/animate.py）
         ├── render_flow_gif  → out/{map_id}_flow.gif
         └── render_team_card → out/tamap_team.gif

閲覧専用ライブページ（チャット内完結の例外・任意）
   scripts/live_view.sh → tamap/live.py（標準ライブラリの http.server）
   ├── data/maps/{map_id}.json を読むだけ（0.2 秒ごとに監視。書き込みなし、GET/HEAD 以外は 405）
   ├── SSE（/events/{map_id}）で Bot の状態・bot_history・say・タスクマップを送る
   ├── ドット絵と配置は sprites.py / persona.py / animate.py を共有（GIF と同じ見た目を canvas に描く）
   └── ブラウザ（box の中）→ http://127.0.0.1:8765/live/{map_id}   ※ URL は get_live_url で取れる
```

### 設計原則

- **入口は PM だけ**：ユーザーは PM に話しかけ、PM が専門Botの結果をまとめてツールに登録する。
- **チャットの中で完結**：ツールは、チャットに貼る mermaid ブロックをそのまま返す。操作用の Web UI は持たない。ライブページは閲覧専用の例外で、チャットの流れには影響しない。
- **決定的な検証はコード側**：ID の参照、循環の検出、到達できる後続タスクの計算などはプログラムで行う。LLM の説明で検証結果を上書きしない。
- **状態の正本は共有ストア**：`data/maps/{map_id}.json` が正本。同じ `map_id` を使い、`revision`・更新時刻・情報源（source）を残す。古い revision での上書きは拒否する。
- **送信済みメッセージは書き換えられない**：途中の状態は `set_bot_status` で記録だけしておき、最後に GIF 1 本で見せる（[docs/UX_DESIGN.md](docs/UX_DESIGN.md)）。

## MCP ツール

| ツール | 内容 | revision |
| --- | --- | --- |
| `create_map(title, tasks, analysis?, source?)` | 新規作成。検証エラーがあっても保存し、図の中で赤く示す | 1 |
| `update_map(map_id, expected_revision, tasks?, analysis?, source?, title?)` | tasks / analysis / title は全体を置き換える。正規化後に同じなら revision は上げず、「変更なし（revision N のまま）」と `unchanged: true` を返す。変わったときだけ差分の 1 行と `diff` を返す。古い revision は、中身が同じでも `revision_conflict` で拒否 | 変わったときだけ +1 |
| `get_map(map_id)` | 現在の図。structuredContent に tasks と analysis | 変わらない |
| `simulate_delay(map_id, task_id)` | What-if。遅延元を太枠、影響を受けるタスクとエッジを黄色で示す。保存しない | 変わらない |
| `list_maps()` | map_id の一覧 | - |
| `set_bot_status(map_id, bot, status, note?, say?)` | Bot の状態を記録する。専門Botが `working` になると、PM は自動で `idle`（「〜の結果待ち」）になる。`say` はそのBotの口調の一言（GIF のふきだし）。ツール一覧に `say` が無いときは、`note` に `｜ say:一言` または `{"note","say"}` と書く | 変わらない |
| `parse_handoff(text, bot?, role?)` | 専門Botの返信を毎回これに渡す（自分ではパースしない）。前置き、json のコードフェンス、末尾カンマ、スマートクォートを除いて JSON を1つ取り出す。`bot`（`role` でも同じ）を付けると必要な項目を検査する。オブジェクトは structuredContent の `data` | - |
| `get_status(map_id)` | Bot の稼働図（mermaid）と直近の履歴 | 変わらない |
| `render_flow_gif(map_id)` | 直近 1 周の流れを `out/{map_id}_flow.gif` に書き出し、そのパスを返す | 変わらない |
| `render_team_card()` | 4 体のチーム紹介の GIF を `out/tamap_team.gif` に書き出す（挨拶に添付） | - |
| `get_live_url(map_id)` | 閲覧専用のライブページの URL と、ライブページのサーバーが起動しているかを返す（`create_map` の structuredContent にも `live_url`） | 変わらない |

`update_map` が返すチャット用テキストの例：

````text
変更点：T3 進行中→完了 ／ ボトルネック：変化なし（T4） ／ 影響先：変化なし（T6・T7）

```mermaid
graph LR …
```
revision 3 ・ map_id `JbeSRnxW` ・ 更新 13:58:10 JST ・ 検証OK
````

各ツールが実際に返したテキストは [docs/sample_output.md](docs/sample_output.md) にあります（e2e テストで自動生成）。

## セットアップ

```bash
uv sync                       # .venv を作る（mcp, pillow）
scripts/mcp_server.sh         # stdio MCP サーバー（Grok Bot に登録するコマンド）
scripts/live_view.sh          # 閲覧専用のライブページ（任意。127.0.0.1:8765、tmux などで常駐）
```

- データの置き場所：`data/maps/`（`TAMAP_DATA_DIR` で変更可）。GIF の出力先：`out/`（`TAMAP_OUT_DIR` で変更可）。
- GIF の日本語は、Noto Sans CJK・IPA・WenQuanYi などのフォントを自動で探して使います。見つからないときは `TAMAP_FONT` にフォントファイルのパスを指定してください。
- Grok Bot への組み込み方（MCP 登録、専門Botの役割分担、指示文の案）は [docs/GROKBOT_INTEGRATION.md](docs/GROKBOT_INTEGRATION.md) を見てください。

## 使用イメージ

1. ユーザーが PM にタスクの一覧を送る（または［サンプル（タスク管理アプリ T1〜T7）で試す］を押す）。
2. PM が開始の 1 行を投稿し、Map Architect → Risk Analyst → Quality Reviewer の順に依頼する。そのたびに `set_bot_status` で記録する。
3. PM が `create_map`／`update_map` を呼び、結果を 1 通で投稿する：結論、タスクマップ（mermaid と revision の行）、次の 3 アクション、レビューで直した点、推定・未確認、GIF、質問ボタン。
4. ユーザーが［T4が遅れたら？］を押すと、PM が `simulate_delay` を 1 回呼んで黄色の影響図を返す（revision は変わらない）。
5. ユーザーが［T3を完了にする］を押すと、PM が `update_map` を呼び、同じ `map_id` の revision が上がる。差分の 1 行が付く。

詳しいメッセージの文面とデモの台本は [docs/UX_DESIGN.md](docs/UX_DESIGN.md) にあります。

### 入力例

**プロジェクト：タスク管理アプリ開発**（`samples/readme_example.json`）

- T1 要件整理：完了、依存なし
- T2 UI設計：完了、T1に依存
- T3 DB設計：進行中、T1に依存
- T4 API実装：未着手、T3に依存
- T5 画面実装：進行中、T2に依存
- T6 統合テスト：未着手、T4とT5に依存
- T7 リリース：未着手、T6に依存

**質問：** 依存関係とボトルネックを整理し、T4が遅延した場合の影響範囲と、次に取るべき3つのアクションを教えてください。

この入力に対する TaMap Core の計算結果（テストで確認済み）：合流点は T6、T4 が遅れると影響するのは T6・T7、クリティカルパス候補は T1→T3→T4→T6→T7、ボトルネック候補は T3。わざと不整合を入れたサンプル（`samples/broken_example.json`）では、重複ID・存在しない参照（T9）・T6⇄T7 の循環を検出します。

## テスト

```bash
uv run python -m unittest tests.test_core tests.test_handoff   # Core・ストア・ハンドオフ・GIF・ライブページ
uv run python tests/e2e_mcp.py              # stdio MCP サーバーを公式クライアントで起動し、全ツールを呼ぶ（ライブページ・CLI も含む）
# 任意：ライブページを headless Chrome で開いてスクリーンショットを撮る（Chrome と puppeteer-core が必要。docs/LIVE_VIEW.md）
# node tests/live_browser.js <base_url> <data_dir> <map_id> <out_dir>
```

## 検証チェックリスト

チェックを付けたのは、テストを実際に実行して確認した項目だけです。

- [ ] PM と 3 体の専門Botが、役割に沿って結果を引き継ぐ（Grok Bot 上では未確認。指示文の案は docs/GROKBOT_INTEGRATION.md）
- [x] タスクIDの不整合・存在しない参照・循環が検出される（unittest・e2e）
- [x] 遅延したタスクから到達できる後続タスクが正しく計算される（unittest・e2e）
- [x] Quality Reviewer の指摘が「直す前→直した後」の形でマップに保存される（e2e）
- [ ] Quality Reviewer の指摘が PM の最終回答に反映される（Grok Bot 上では未確認）
- [x] MCP ツールの戻り値から map_id と最新の図（mermaid）を取得できる（e2e。Grok Bot から MCP として呼べるかは未確認）
- [x] 追加の更新で、**同じ map_id** の revision と図が更新され、差分の 1 行が付く。古い revision からの更新は拒否される（e2e）
- [x] Bot の状態を記録すると、作業中のBotだけが光る（専門Botが作業中なら PM は待機）。その流れを GIF に書き出せる。4 体のキャラクター（ドット絵・ふきだし・チーム紹介）も含む（unittest・e2e。GIF は開発用 VM で生成して目視）
- [x] ライブページは読み取り専用（書き込みメソッドは 405、ファイルは変わらない）。`set_bot_status` の後、SSE で 1 秒以内に反映される（unittest・e2e・headless Chrome。Grok Bot の box では未確認）
- [ ] 書き込みの認証：stdio MCP サーバーを起動できる人（＝ box にアクセスできる人）だけが書ける、という境界しかない。トークンによる認証は無い
- [ ] 90 秒以内に一連の流れを実演できる（未リハーサル）

## 開発方針と非目標

この MVP では、**操作用の Web UI、外部への公開（ライブページの外部公開は未確認。docs/LIVE_VIEW.md）、GitHub 連携、Issue/PR の自動割り当て・実装・マージ、日数の計算、常時無停止の自律実行、外部 DB の本格運用** は扱いません。必要になったら後から追加します。

実装と検証が終わった機能だけを「動作済み」と書き、終わっていないものは未完了と明記します。

---

**TaMap — タスクをつなぎ、未来を描く。**
