# TaMap 実装メモ（ハッカソン MVP・Grok Botアプリ内完結版）

README本体はまだ書き換えていません。ここには **実際に動かして確認したこと** と **未確認のこと** を分けて書きます。
（最終検証：2026-10-11 13:07 JST ごろ、Grok Bot の box（Linux）上）

## 方針（2026-10-11 13:04〜13:06 JST に変更）

- 公開URL・Web UI・cloudflared は廃止。**Grok Bot のチャット内で完結**させる。
- MCPツールの返すチャット用テキストは **mermaid コードブロックのみ**（タスクマップは下に revision の1行、Bot稼働図は下に直近の変更履歴）。PM Bot はこれをそのまま投稿する。
- 優先アクション等の文章は PM Bot が書く。ツールは構造化データ（structuredContent）で事実（検証結果・合流点・ボトルネック・影響先）を返す。
- チャットは書き換えられないため、PM は各ハンドオフ時に `set_bot_status` の返す稼働図を投稿する運用。

## 構成

| パス | 役割 |
| --- | --- |
| `tamap/core.py` | 検証（重複ID / 存在しない参照 / 自己依存 / 循環 / 不正status）、遅延影響（到達可能な後続）、下流タスク数・合流点・ボトルネック候補・クリティカルパス候補。LLM不使用、標準ライブラリのみ |
| `tamap/store.py` | 共有ストア `data/maps/{map_id}.json`（`TAMAP_DATA_DIR` で変更可）。fcntlロック＋アトミック書き込み。`update_map` は `expected_revision` 不一致を拒否。Bot状態（`bots`, `bot_history` 直近30件）も同じファイルに保持 |
| `tamap/render.py` | mermaid 生成（タスクマップ `graph LR`／Bot稼働 `flowchart LR`）。ラベル中の `" < > & `` ` は mermaid のエンティティコードでエスケープ |
| `tamap/mcp_server.py` | stdio MCP サーバー（公式 `mcp` Python SDK 1.x の FastMCP） |
| `scripts/mcp_server.sh` | MCPサーバーの起動口（Grok Bot に登録するコマンド） |
| `samples/readme_example.json` / `samples/broken_example.json` | README例 T1〜T7 ／ わざと不整合（T5→存在しないT9、T6⇄T7 循環、T2 重複ID） |
| `tests/test_core.py` / `tests/e2e_mcp.py` | Core の unittest ／ 公式 mcp クライアントで stdio サーバーを起動し全ツールを呼ぶE2E（結果を `docs/sample_output.md` に保存） |
| `docs/sample_output.md` | 各ツールが実際に返したチャット用テキスト |

## MCPツール

| ツール | 内容 | revision |
| --- | --- | --- |
| `create_map(title, tasks, analysis?, source?)` | 新規作成。検証エラーがあっても保存し、図の中で赤く示す | 1 |
| `update_map(map_id, expected_revision, tasks?, analysis?, source?, title?)` | tasks / analysis は全体置換。古い revision は `revision_conflict`（isError）で拒否 | +1 |
| `get_map(map_id)` | 現在の図。structuredContent に tasks と analysis | 不変 |
| `simulate_delay(map_id, task_id)` | what-if。遅延元を太枠、影響タスクとそのエッジを黄色。保存しない | 不変 |
| `list_maps()` | map_id 一覧（短い箇条書き） | - |
| `set_bot_status(map_id, bot, status, note?)` | bot: pm / map_architect / risk_analyst / quality_reviewer、status: idle / working / done / error。稼働図を返す | 不変 |
| `get_status(map_id)` | 稼働図（ユーザー → TaMap PM → Map Architect → Risk Analyst → Quality Reviewer → PM） | 不変 |

タスクマップ図の表現：状態色（完了=緑／進行中=青／未着手=灰／ブロック中=橙）、遅延影響=黄、検証エラー=赤ノード、存在しない参照は赤ノード＋赤破線「未定義」、循環は赤破線「循環」、合流点は「◆合流点」、ボトルネックは「▲ボトルネック」＋破線太枠、クリティカルパス候補は太線（`==>`）、警告は「△…」。
稼働図：待機=灰／作業中=青／完了=緑／エラー=赤、作業中Botへ入るエッジを青の太線。PM が作業中のときは、他Botが動いていれば「検証結果→PM」、全員待機なら「依頼→PM」を強調。時刻は JST HH:MM:SS。

## 実際に動作を確認したこと

- `uv run python -m unittest tests.test_core` → 4件 OK（README例：合流点 T6、T4遅延→T6・T7、クリティカルパス候補 T1→T3→T4→T6→T7、ボトルネック T3／不整合サンプル：重複ID・存在しない参照・T6→T7→T6 循環を検出／3ノード循環・自己依存・不正status）。
- `uv run python tests/e2e_mcp.py` → 46項目すべて PASS（stdio で実際にツール呼び出し、一時データディレクトリ使用）。チャット用テキストが mermaid 1ブロック＋1行であること、表（`|`）が無いこと、T4 blocked 更新、古い revision の拒否、simulate_delay(T4)=T6・T7 と revision 不変、Bot状態の色・強調エッジ・履歴、未知の bot / status の拒否、Bot状態で map revision が変わらないこと、不整合サンプルの赤ノード・赤破線、記号入りタイトルのエスケープ、actions 4件の拒否。
- `docs/sample_output.md` の mermaid 9ブロックすべてを、headless Chrome 上の mermaid v11（jsDelivr CDN）で `parse` と `render` してエラーなし。何枚かはスクリーンショットで目視し、色・破線・太線が意図どおりなのを確認。
- 登録コマンド `scripts/mcp_server.sh` は、別ディレクトリ（cwd=/tmp）から起動しても動くことを前の版で確認済み。今回の版では e2e がこのスクリプト経由で起動している。

## 未確認

- **Grok Bot から この MCP サーバーを実際に登録・呼び出しできるか**（README 0:00–0:30 の疎通試験そのもの）。
- **Grok Bot のチャットで mermaid が描画されるか、どの mermaid バージョンか**。確認したのは box の headless Chrome＋mermaid v11 のみ。`classDef` / `linkStyle` / `style` / `<br>` / エンティティコードに非対応の描画系だと、色や改行が崩れる可能性がある。
- 4 Bot 連携・再分析（README 2:40 以降）は未着手。
- 書き込みの認証：stdio MCP を起動できる＝box にアクセスできる人だけが書ける、という境界のみ。トークン認証は無し。

## 削除したもの

Web UI（`tamap/web.py`、`tamap/web/`）、`scripts/start.sh` / `stop.sh`、cloudflared バイナリと `run/`、公開URL・view URL の概念、旧テストデータ `data/views/`。常駐していた Web サーバーとトンネルは停止済み（cloudflared のトンネルは box から外向き 7844 番ポートが遮断されていて、もともと成立していなかった）。
