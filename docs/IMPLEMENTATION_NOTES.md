# TaMap 実装メモ（ハッカソン MVP・Grok Botアプリ内完結版）

README はチャット内完結の方式に書き換え済み（UX_DESIGN P7）。ここには **実際に動かして確認したこと** と **未確認のこと** を分けて書きます。
（最終検証：2026-10-11 13:07 JST ごろ、Grok Bot の box（Linux）上）

## 方針（2026-10-11 13:04〜13:06 JST に変更）

- 公開URL・Web UI・cloudflared は廃止。**Grok Bot のチャット内で完結**させる。
- MCPツールの返すチャット用テキストは **mermaid コードブロックのみ**（タスクマップは下に revision の1行、Bot稼働図は下に直近の変更履歴）。PM Bot はこれをそのまま投稿する。
- 優先アクション等の文章は PM Bot が書く。ツールは構造化データ（structuredContent）で事実（検証結果・合流点・ボトルネック・影響先）を返す。
- チャットは書き換えられないため、途中の状態は `set_bot_status` で記録だけし、結果に流れのGIF（`render_flow_gif`）を1本添付する（UX_DESIGN 4.1 案C）。稼働図を貼るのはエラー時と「Botの状態を見る」のときだけ。
- Grok Bot への組み込み方と4体の指示文の案は `docs/GROKBOT_INTEGRATION.md`。
- **例外（2026-10-11、Yuu さんの決定）**：閲覧専用のライブページ（`tamap/live.py`、`scripts/live_view.sh`、既定は 127.0.0.1:8765 の `/live/{map_id}`）。書き込み用のエンドポイントは無い。チャットの流れは変えない。外部への公開は未確認（`docs/LIVE_VIEW.md`）。

## 構成

| パス | 役割 |
| --- | --- |
| `tamap/core.py` | 検証（重複ID / 存在しない参照 / 自己依存 / 循環 / 不正status）、遅延影響（到達可能な後続）、下流タスク数・合流点・ボトルネック候補・クリティカルパス候補。LLM不使用、標準ライブラリのみ |
| `tamap/store.py` | 共有ストア `data/maps/{map_id}.json`（`TAMAP_DATA_DIR` で変更可）。fcntlロック＋アトミック書き込み。`update_map` は `expected_revision` 不一致を拒否。Bot状態（`bots`, `bot_history` 直近30件）も同じファイルに保持 |
| `tamap/render.py` | mermaid 生成（タスクマップ `graph LR`／Bot稼働 `flowchart LR`）。ラベル中の `" < > & `` ` は mermaid のエンティティコードでエスケープ |
| `tamap/animate.py` | 流れのGIF（Pillow）。`bot_history` の直近1周から `out/{map_id}_flow.gif`（`TAMAP_OUT_DIR` で変更可）。作業中のBotだけ光る、依頼=青／結果=黄の封筒、最後にボトルネックからの影響の広がりと3アクション、QRバッジ（件数は `analysis.quality.items`） |
| `tamap/persona.py` / `tamap/sprites.py` | 4 体のキャラクター（役割・色・モチーフ・口調・状態の顔文字）と、レトロなドット絵（16×14 の格子＋小物）。GIF・稼働図 mermaid・指示文で共通に使う |
| `tamap/mcp_server.py` | stdio MCP サーバー（公式 `mcp` Python SDK 1.x の FastMCP） |
| `scripts/mcp_server.sh` | MCPサーバーの起動口（Grok Bot に登録するコマンド） |
| `tamap/live.py` / `scripts/live_view.sh` | 閲覧専用のライブページ（標準ライブラリの http.server＋SSE）。ストアのファイルを監視し、`bot_history` に合わせてドット絵のキャラを canvas に描く（スプライトと配置は GIF と共通） |
| `scripts/tamap_cli.sh` | MCP を登録できない場合のシェル用の代替。同じツール関数を呼ぶ（stdout=チャット用テキスト、stderr=structuredContent） |
| `samples/readme_example.json` / `samples/broken_example.json` | README例 T1〜T7 ／ わざと不整合（T5→存在しないT9、T6⇄T7 循環、T2 重複ID） |
| `tests/test_core.py` / `tests/e2e_mcp.py` | Core の unittest ／ 公式 mcp クライアントで stdio サーバーを起動し全ツールを呼ぶE2E（結果を `docs/sample_output.md` に保存） |
| `docs/sample_output.md` | 各ツールが実際に返したチャット用テキスト |

## MCPツール

| ツール | 内容 | revision |
| --- | --- | --- |
| `create_map(title, tasks, analysis?, source?)` | 新規作成。検証エラーがあっても保存し、図の中で赤く示す | 1 |
| `update_map(map_id, expected_revision, tasks?, analysis?, source?, title?)` | tasks / analysis は全体置換。図の上に差分の1行（変更点 ／ ボトルネック ／ 影響先）、structuredContent に `diff`。古い revision は `revision_conflict`（isError）で拒否 | +1 |
| `get_map(map_id)` | 現在の図。structuredContent に tasks と analysis | 不変 |
| `simulate_delay(map_id, task_id)` | what-if。遅延元を太枠、影響タスクとそのエッジを黄色。保存しない | 不変 |
| `list_maps()` | map_id 一覧（短い箇条書き） | - |
| `set_bot_status(map_id, bot, status, note?)` | bot: pm / map_architect / risk_analyst / quality_reviewer、status: idle / working / done / error。稼働図を返す。専門Botが working になると pm を自動で idle（「〜の結果待ち」）にし、履歴にも残す | 不変 |
| `render_flow_gif(map_id)` | 直近1周の流れを GIF に書き出し、パスを返す（キャラのふきだしは `set_bot_status` の `say`、無ければ口ぐせ） | 不変 |
| `render_team_card()` | 4 体のチーム紹介の GIF（`out/tamap_team.gif`） | - |
| `get_live_url(map_id)` | ライブページの URL と、ライブページのサーバーが起動しているか（`running`） | 不変 |
| `get_status(map_id)` | 稼働図（ユーザー → TaMap PM → Map Architect → Risk Analyst → Quality Reviewer → PM） | 不変 |

タスクマップ図の表現：状態色（完了=緑／進行中=青／未着手=灰／ブロック中=橙）、遅延影響=黄、検証エラー=赤ノード、存在しない参照は赤ノード＋赤破線「未定義」、循環は赤破線「循環」、合流点は「◆合流点」、ボトルネックは「▲ボトルネック」＋破線太枠、クリティカルパス候補は太線（`==>`）、警告は「△…」。
稼働図：待機=灰／作業中=青／完了=緑／エラー=赤、作業中Botへ入るエッジを青の太線。PM が作業中のときは、他Botが動いていれば「検証結果→PM」、全員待機なら「依頼→PM」を強調。時刻は JST HH:MM:SS。

## 実際に動作を確認したこと

- `uv run python -m unittest tests.test_core` → 4件 OK（README例：合流点 T6、T4遅延→T6・T7、クリティカルパス候補 T1→T3→T4→T6→T7、ボトルネック T3／不整合サンプル：重複ID・存在しない参照・T6→T7→T6 循環を検出／3ノード循環・自己依存・不正status）。
- `uv run python tests/e2e_mcp.py` → 46項目すべて PASS（stdio で実際にツール呼び出し、一時データディレクトリ使用）。チャット用テキストが mermaid 1ブロック＋1行であること、表（`|`）が無いこと、T4 blocked 更新、古い revision の拒否、simulate_delay(T4)=T6・T7 と revision 不変、Bot状態の色・強調エッジ・履歴、未知の bot / status の拒否、Bot状態で map revision が変わらないこと、不整合サンプルの赤ノード・赤破線、記号入りタイトルのエスケープ、actions 4件の拒否。
- `docs/sample_output.md` の mermaid 9ブロックすべてを、headless Chrome 上の mermaid v11（jsDelivr CDN）で `parse` と `render` してエラーなし。何枚かはスクリーンショットで目視し、色・破線・太線が意図どおりなのを確認。
- 登録コマンド `scripts/mcp_server.sh` は、別ディレクトリ（cwd=/tmp）から起動しても動くことを前の版で確認済み。今回の版では e2e がこのスクリプト経由で起動している。

## 追加で確認したこと（UX_DESIGN P2〜P4・P7、開発用 VM 上）

- `uv run python -m unittest tests.test_core` → 8件 OK：PM の自動待機、差分の1行（T4 ブロック中 → ボトルネック T3→T4、T3 完了 → 変化なし）、`before` の保存、GIF の生成。
- `uv run python tests/e2e_mcp.py` → 60項目すべて PASS：上記に加え、`render_flow_gif`、`tamap_cli.sh`。
- GIF（キャラクター化の前の版）：サンプル1周（10イベント）で 71フレーム・約25秒・約480KB。フレームを PNG で取り出して目視した（フォントは WenQuanYi Micro Hei）。Grok Bot の box でのフォントと添付は未確認。
- P0（Grok Bot のチャットでの mermaid 描画と GIF の再生）は確認済みと報告を受けている（本作業では実施していない）。
- キャラクター化（Yuu さんのフィードバック）：unittest 9件 OK、e2e 73項目 PASS。flow GIF（サンプル1周で約25秒・約650KB）とチーム紹介の GIF（5フレーム・約1.7秒・約70KB）を目視した。`docs/sample_output.md` の mermaid 11ブロックを headless Chrome＋mermaid v11 で描画してエラーなし（稼働図の絵文字・顔文字を含む）。

- ライブページ：unittest 10件 OK、e2e 83項目 PASS。headless Chrome で、5 回の状態変化がそれぞれ約 0.5 秒（CLI の起動を含む）で反映された。ドット絵は表示倍率 1・2 の両方で `bot_pixels` と一致し、ずれは 0。スクリーンショットは PR に添付。

## 未確認

- **Grok Bot から この MCP サーバーを実際に登録・呼び出しできるか**（README 0:00–0:30 の疎通試験そのもの）。
- Grok Bot のチャットの mermaid のバージョン（classDef / linkStyle / style / 破線・太線 / `<br>` の描画は P0 で確認済み）。エンティティコード（`#quot;` など）の描画は個別には未確認。
- 4 Bot 連携・再分析は未実施（指示文の案は `docs/GROKBOT_INTEGRATION.md`）。
- `render_flow_gif` が box 上で作った GIF を Grok Bot で添付・再生できるか、box に日本語フォントがあるか。
- ライブページ：Grok Bot の box で常駐させられるか、box の中のブラウザで開けるか、外部への公開（`docs/LIVE_VIEW.md` の選択肢はすべて未実施）。
- 書き込みの認証：stdio MCP を起動できる＝box にアクセスできる人だけが書ける、という境界のみ。トークン認証は無し。

## 削除したもの

Web UI（`tamap/web.py`、`tamap/web/`）、`scripts/start.sh` / `stop.sh`、cloudflared バイナリと `run/`、公開URL・view URL の概念、旧テストデータ `data/views/`。常駐していた Web サーバーとトンネルは停止済み（cloudflared のトンネルは box から外向き 7844 番ポートが遮断されていて、もともと成立していなかった）。※ 後から、閲覧専用のライブページだけを例外として追加した（上の「方針」）。
