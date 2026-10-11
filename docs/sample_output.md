# TaMap MCP 出力サンプル

`tests/e2e_mcp.py` が stdio MCP サーバーを公式 mcp クライアントで実際に呼び、各ツールが返したチャット用テキスト（mermaid）をそのまま貼ったものです（自動生成）。時刻は実行時のもの。

## create_map（README例）

```mermaid
graph LR
  n0["T1 要件整理<br>完了"]
  n1["T2 UI設計<br>完了"]
  n2["T3 DB設計<br>進行中<br>▲ボトルネック"]
  n3["T4 API実装<br>未着手"]
  n4["T5 画面実装<br>進行中"]
  n5["T6 統合テスト<br>未着手<br>◆合流点"]
  n6["T7 リリース<br>未着手"]
  n0 --> n1
  n0 ==> n2
  n2 ==> n3
  n1 --> n4
  n3 ==> n5
  n4 --> n5
  n5 ==> n6
  classDef done fill:#22c55e,stroke:#15803d,color:#ffffff
  classDef prog fill:#3b82f6,stroke:#1d4ed8,color:#ffffff
  classDef todo fill:#9ca3af,stroke:#4b5563,color:#111827
  classDef blocked fill:#f97316,stroke:#c2410c,color:#ffffff
  classDef impact fill:#facc15,stroke:#a16207,color:#111827
  classDef err fill:#ef4444,stroke:#991b1b,color:#ffffff
  class n0,n1 done
  class n2,n4 prog
  class n3,n5,n6 todo
  style n2 stroke:#7c2d12,stroke-width:4px,stroke-dasharray:6 3
```
revision 1 ・ map_id `eq9K0EQI` ・ 更新 14:28:10 JST ・ 検証OK

---

## update_map（T4をブロック中に）

変更点：T4 未着手→ブロック中 ／ ボトルネック：T3→T4 ／ 影響先：T4・T6・T7→T6・T7

```mermaid
graph LR
  n0["T1 要件整理<br>完了"]
  n1["T2 UI設計<br>完了"]
  n2["T3 DB設計<br>進行中"]
  n3["T4 API実装<br>ブロック中<br>▲ボトルネック"]
  n4["T5 画面実装<br>進行中"]
  n5["T6 統合テスト<br>未着手<br>◆合流点"]
  n6["T7 リリース<br>未着手"]
  n0 --> n1
  n0 ==> n2
  n2 ==> n3
  n1 --> n4
  n3 ==> n5
  n4 --> n5
  n5 ==> n6
  classDef done fill:#22c55e,stroke:#15803d,color:#ffffff
  classDef prog fill:#3b82f6,stroke:#1d4ed8,color:#ffffff
  classDef todo fill:#9ca3af,stroke:#4b5563,color:#111827
  classDef blocked fill:#f97316,stroke:#c2410c,color:#ffffff
  classDef impact fill:#facc15,stroke:#a16207,color:#111827
  classDef err fill:#ef4444,stroke:#991b1b,color:#ffffff
  class n0,n1 done
  class n2,n4 prog
  class n3 blocked
  class n5,n6 todo
  style n3 stroke:#7c2d12,stroke-width:4px,stroke-dasharray:6 3
```
revision 2 ・ map_id `eq9K0EQI` ・ 更新 14:28:10 JST ・ 検証OK

---

## update_map（古いrevisionで更新 → 拒否）

エラー: revision conflict: map eq9K0EQI は revision 2 です（expected_revision=1）。 get_map で最新状態を読み直してから再度 update_map してください。

---

## get_map

```mermaid
graph LR
  n0["T1 要件整理<br>完了"]
  n1["T2 UI設計<br>完了"]
  n2["T3 DB設計<br>進行中"]
  n3["T4 API実装<br>ブロック中<br>▲ボトルネック"]
  n4["T5 画面実装<br>進行中"]
  n5["T6 統合テスト<br>未着手<br>◆合流点"]
  n6["T7 リリース<br>未着手"]
  n0 --> n1
  n0 ==> n2
  n2 ==> n3
  n1 --> n4
  n3 ==> n5
  n4 --> n5
  n5 ==> n6
  classDef done fill:#22c55e,stroke:#15803d,color:#ffffff
  classDef prog fill:#3b82f6,stroke:#1d4ed8,color:#ffffff
  classDef todo fill:#9ca3af,stroke:#4b5563,color:#111827
  classDef blocked fill:#f97316,stroke:#c2410c,color:#ffffff
  classDef impact fill:#facc15,stroke:#a16207,color:#111827
  classDef err fill:#ef4444,stroke:#991b1b,color:#ffffff
  class n0,n1 done
  class n2,n4 prog
  class n3 blocked
  class n5,n6 todo
  style n3 stroke:#7c2d12,stroke-width:4px,stroke-dasharray:6 3
```
revision 2 ・ map_id `eq9K0EQI` ・ 更新 14:28:10 JST ・ 検証OK

---

## simulate_delay（T4）

```mermaid
graph LR
  n0["T1 要件整理<br>完了"]
  n1["T2 UI設計<br>完了"]
  n2["T3 DB設計<br>進行中"]
  n3["T4 API実装<br>ブロック中<br>▲ボトルネック ⏱遅延元"]
  n4["T5 画面実装<br>進行中"]
  n5["T6 統合テスト<br>未着手<br>◆合流点 遅延影響 1段先"]
  n6["T7 リリース<br>未着手<br>遅延影響 2段先"]
  n0 --> n1
  n0 ==> n2
  n2 ==> n3
  n1 --> n4
  n3 ==> n5
  n4 --> n5
  n5 ==> n6
  classDef done fill:#22c55e,stroke:#15803d,color:#ffffff
  classDef prog fill:#3b82f6,stroke:#1d4ed8,color:#ffffff
  classDef todo fill:#9ca3af,stroke:#4b5563,color:#111827
  classDef blocked fill:#f97316,stroke:#c2410c,color:#ffffff
  classDef impact fill:#facc15,stroke:#a16207,color:#111827
  classDef err fill:#ef4444,stroke:#991b1b,color:#ffffff
  class n0,n1 done
  class n2,n4 prog
  class n3 blocked
  class n5,n6 impact
  style n3 stroke:#7c2d12,stroke-width:4px,stroke-dasharray:6 3
  style n3 stroke:#ca8a04,stroke-width:5px
  linkStyle 4,6 stroke:#ca8a04,stroke-width:4px
```
revision 2 ・ map_id `eq9K0EQI` ・ 更新 14:28:10 JST ・ 検証OK ・ what-if: T4（保存なし）

---

## set_bot_status（MA作業中 → PMは自動で待機）

```mermaid
flowchart LR
  U(["ユーザー"])
  PM["📋 TaMap PM<br>(-ω-)zz 待機<br>Map Architectの結果待ち<br>14:28:10 JST"]
  MA["🗺️ Map Architect<br>(•ω•)✧ 作業中<br>「線、7本つなぐっす。」<br>T1〜T7を構造化中<br>14:28:10 JST"]
  RA["⚠️ Risk Analyst<br>(-ω-)zz 待機"]
  QR["✅ Quality Reviewer<br>(-ω-)zz 待機"]
  U -- 依頼 --> PM
  PM -- 分解 --> MA
  MA -- 構造 --> RA
  RA -- リスク --> QR
  QR -- 検証結果 --> PM
  classDef idle fill:#9ca3af,stroke:#4b5563,color:#111827
  classDef working fill:#3b82f6,stroke:#1d4ed8,color:#ffffff
  classDef done fill:#22c55e,stroke:#15803d,color:#ffffff
  classDef error fill:#ef4444,stroke:#991b1b,color:#ffffff
  classDef user fill:#ffffff,stroke:#4b5563,color:#111827
  class U user
  class PM,RA,QR idle
  class MA working
  linkStyle 1 stroke:#2563eb,stroke-width:5px
```
map `eq9K0EQI` のBot稼働状況 ・ 直近の変更（新しい順）:
- 14:28:10 Map Architect: 作業中（T1〜T7を構造化中）
- 14:28:10 TaMap PM: 待機（Map Architectの結果待ち）
- 14:28:10 TaMap PM: 作業中（依頼を受付）

---

## set_bot_status（Risk Analyst 作業中）

```mermaid
flowchart LR
  U(["ユーザー"])
  PM["📋 TaMap PM<br>(-ω-)zz 待機<br>Map Architectの結果待ち<br>14:28:10 JST"]
  MA["🗺️ Map Architect<br>(^ω^) 完了<br>7タスク・7依存<br>14:28:10 JST"]
  RA["⚠️ Risk Analyst<br>(•ω•)✧ 作業中<br>「ここ、あやしいかも…」<br>T4遅延の波及を分析中<br>14:28:10 JST"]
  QR["✅ Quality Reviewer<br>(-ω-)zz 待機"]
  U -- 依頼 --> PM
  PM -- 分解 --> MA
  MA -- 構造 --> RA
  RA -- リスク --> QR
  QR -- 検証結果 --> PM
  classDef idle fill:#9ca3af,stroke:#4b5563,color:#111827
  classDef working fill:#3b82f6,stroke:#1d4ed8,color:#ffffff
  classDef done fill:#22c55e,stroke:#15803d,color:#ffffff
  classDef error fill:#ef4444,stroke:#991b1b,color:#ffffff
  classDef user fill:#ffffff,stroke:#4b5563,color:#111827
  class U user
  class PM,QR idle
  class MA done
  class RA working
  linkStyle 2 stroke:#2563eb,stroke-width:5px
```
map `eq9K0EQI` のBot稼働状況 ・ 直近の変更（新しい順）:
- 14:28:10 Risk Analyst: 作業中（T4遅延の波及を分析中）
- 14:28:10 Map Architect: 完了（7タスク・7依存）
- 14:28:10 Map Architect: 作業中（T1〜T7を構造化中）
- 14:28:10 TaMap PM: 待機（Map Architectの結果待ち）
- 14:28:10 TaMap PM: 作業中（依頼を受付）

---

## set_bot_status（PM統合中・QRエラー）

```mermaid
flowchart LR
  U(["ユーザー"])
  PM["📋 TaMap PM<br>(•ω•)✧ 作業中<br>「まかせてください！」<br>結果を統合中<br>14:28:10 JST"]
  MA["🗺️ Map Architect<br>(^ω^) 完了<br>7タスク・7依存<br>14:28:10 JST"]
  RA["⚠️ Risk Analyst<br>(^ω^) 完了<br>14:28:10 JST"]
  QR["✅ Quality Reviewer<br>(#gt;ω#lt;;) エラー<br>「読みきれなかった…ごめんね」<br>T9参照を確認できず<br>14:28:10 JST"]
  U -- 依頼 --> PM
  PM -- 分解 --> MA
  MA -- 構造 --> RA
  RA -- リスク --> QR
  QR -- 検証結果 --> PM
  classDef idle fill:#9ca3af,stroke:#4b5563,color:#111827
  classDef working fill:#3b82f6,stroke:#1d4ed8,color:#ffffff
  classDef done fill:#22c55e,stroke:#15803d,color:#ffffff
  classDef error fill:#ef4444,stroke:#991b1b,color:#ffffff
  classDef user fill:#ffffff,stroke:#4b5563,color:#111827
  class U user
  class PM working
  class MA,RA done
  class QR error
  linkStyle 4 stroke:#2563eb,stroke-width:5px
```
map `eq9K0EQI` のBot稼働状況 ・ 直近の変更（新しい順）:
- 14:28:10 TaMap PM: 作業中（結果を統合中）
- 14:28:10 Risk Analyst: 完了
- 14:28:10 Quality Reviewer: エラー（T9参照を確認できず）
- 14:28:10 Risk Analyst: 作業中（T4遅延の波及を分析中）
- 14:28:10 Map Architect: 完了（7タスク・7依存）

---

## get_status

```mermaid
flowchart LR
  U(["ユーザー"])
  PM["📋 TaMap PM<br>(•ω•)✧ 作業中<br>「まかせてください！」<br>結果を統合中<br>14:28:10 JST"]
  MA["🗺️ Map Architect<br>(^ω^) 完了<br>7タスク・7依存<br>14:28:10 JST"]
  RA["⚠️ Risk Analyst<br>(^ω^) 完了<br>14:28:10 JST"]
  QR["✅ Quality Reviewer<br>(#gt;ω#lt;;) エラー<br>「読みきれなかった…ごめんね」<br>T9参照を確認できず<br>14:28:10 JST"]
  U -- 依頼 --> PM
  PM -- 分解 --> MA
  MA -- 構造 --> RA
  RA -- リスク --> QR
  QR -- 検証結果 --> PM
  classDef idle fill:#9ca3af,stroke:#4b5563,color:#111827
  classDef working fill:#3b82f6,stroke:#1d4ed8,color:#ffffff
  classDef done fill:#22c55e,stroke:#15803d,color:#ffffff
  classDef error fill:#ef4444,stroke:#991b1b,color:#ffffff
  classDef user fill:#ffffff,stroke:#4b5563,color:#111827
  class U user
  class PM working
  class MA,RA done
  class QR error
  linkStyle 4 stroke:#2563eb,stroke-width:5px
```
map `eq9K0EQI` のBot稼働状況 ・ 直近の変更（新しい順）:
- 14:28:10 TaMap PM: 作業中（結果を統合中）
- 14:28:10 Risk Analyst: 完了
- 14:28:10 Quality Reviewer: エラー（T9参照を確認できず）
- 14:28:10 Risk Analyst: 作業中（T4遅延の波及を分析中）
- 14:28:10 Map Architect: 完了（7タスク・7依存）

---

## update_map（T3を完了に・差分の1行）

変更点：T3 進行中→完了 ／ ボトルネック：変化なし（T4） ／ 影響先：変化なし（T6・T7）

```mermaid
graph LR
  n0["T1 要件整理<br>完了"]
  n1["T2 UI設計<br>完了"]
  n2["T3 DB設計<br>完了"]
  n3["T4 API実装<br>ブロック中<br>▲ボトルネック"]
  n4["T5 画面実装<br>進行中"]
  n5["T6 統合テスト<br>未着手<br>◆合流点"]
  n6["T7 リリース<br>未着手"]
  n0 ==> n1
  n0 --> n2
  n2 --> n3
  n1 ==> n4
  n3 --> n5
  n4 ==> n5
  n5 ==> n6
  classDef done fill:#22c55e,stroke:#15803d,color:#ffffff
  classDef prog fill:#3b82f6,stroke:#1d4ed8,color:#ffffff
  classDef todo fill:#9ca3af,stroke:#4b5563,color:#111827
  classDef blocked fill:#f97316,stroke:#c2410c,color:#ffffff
  classDef impact fill:#facc15,stroke:#a16207,color:#111827
  classDef err fill:#ef4444,stroke:#991b1b,color:#ffffff
  class n0,n1,n2 done
  class n3 blocked
  class n4 prog
  class n5,n6 todo
  style n3 stroke:#7c2d12,stroke-width:4px,stroke-dasharray:6 3
```
revision 3 ・ map_id `eq9K0EQI` ・ 更新 14:28:10 JST ・ 検証OK

---

## render_flow_gif

▶ 流れのGIF: `/tmp/tamap-e2e-9reh9y4n/out/eq9K0EQI_flow.gif`（約23秒・Bot履歴9件）

---

## render_team_card

▶ チーム紹介のGIF: `/tmp/tamap-e2e-9reh9y4n/out/tamap_team.gif`

---

## create_map（不整合サンプル）

```mermaid
graph LR
  n0["T1 要件整理<br>完了"]
  n1["T2 UI設計<br>完了<br>▲ボトルネック<br>✖重複ID ×2"]
  n2["T3 DB設計<br>進行中<br>▲ボトルネック"]
  n3["T4 API実装<br>未着手"]
  n4["T5 画面実装<br>進行中<br>✖存在しない参照: T9<br>△依存先未完了: T2"]
  n5["T6 統合テスト<br>未着手<br>◆合流点<br>✖循環"]
  n6["T7 リリース<br>未着手<br>✖循環"]
  n7["T9<br>✖存在しないタスク"]
  n0 --> n1
  n0 --> n2
  n2 --> n3
  n1 --> n4
  n7 -. 未定義 .-> n4
  n3 --> n5
  n4 --> n5
  n6 -. 循環 .-> n5
  n5 -. 循環 .-> n6
  classDef done fill:#22c55e,stroke:#15803d,color:#ffffff
  classDef prog fill:#3b82f6,stroke:#1d4ed8,color:#ffffff
  classDef todo fill:#9ca3af,stroke:#4b5563,color:#111827
  classDef blocked fill:#f97316,stroke:#c2410c,color:#ffffff
  classDef impact fill:#facc15,stroke:#a16207,color:#111827
  classDef err fill:#ef4444,stroke:#991b1b,color:#ffffff
  class n0 done
  class n1,n4,n5,n6,n7 err
  class n2 prog
  class n3 todo
  style n2 stroke:#7c2d12,stroke-width:4px,stroke-dasharray:6 3
  linkStyle 4,7,8 stroke:#ef4444,stroke-width:3px,stroke-dasharray:5 4
```
revision 1 ・ map_id `hrl18AyT` ・ 更新 14:28:14 JST ・ 検証エラー3件

---

## create_map（記号入りタイトルのエスケープ確認）

```mermaid
graph LR
  n0["A #quot;引用#quot; #lt;tag#gt; #amp; |pipe| [角] {波} #h; #96;bt#96; --#gt;<br>未着手"]
  n1["B end<br>ブロック中<br>▲ボトルネック"]
  n0 ==> n1
  classDef done fill:#22c55e,stroke:#15803d,color:#ffffff
  classDef prog fill:#3b82f6,stroke:#1d4ed8,color:#ffffff
  classDef todo fill:#9ca3af,stroke:#4b5563,color:#111827
  classDef blocked fill:#f97316,stroke:#c2410c,color:#ffffff
  classDef impact fill:#facc15,stroke:#a16207,color:#111827
  classDef err fill:#ef4444,stroke:#991b1b,color:#ffffff
  class n0 todo
  class n1 blocked
  style n1 stroke:#7c2d12,stroke-width:4px,stroke-dasharray:6 3
```
revision 1 ・ map_id `d9civqJW` ・ 更新 14:28:14 JST ・ 検証OK

---

## list_maps

- `hrl18AyT` デモ用：不整合入りサンプル（Quality Reviewer検出デモ）（revision 1、更新 14:28:14 JST）
- `d9civqJW` Q"uote <b> & |x| [y] `z` end（revision 1、更新 14:28:14 JST）
- `eq9K0EQI` タスク管理アプリ開発（README入力例）（revision 3、更新 14:28:10 JST）

---
