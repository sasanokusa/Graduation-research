# 卒業研究 予算概算レポート (2026-05-29)

作成日: 2026-05-29
目的: 卒業研究の予算獲得（稟議・申請）に用いる、残期間（2026-05 〜 2027-02 提出）の総コスト概算と、日本の公立学校機関で通しやすい支払い方法の整理。
基礎資料: [Phase 1 比較実験コスト](../reports/phase1_compare_cost_report_20260414.md), [局所実験コスト](../reports/local_experiment_cost_report_20260419.md), [GPT-5.4 self-critique 局所実験](../reports/self_critique_gpt54_local_experiment_20260509.md), [Planner Escalation コスト比較](../reports/planner_escalation_cost_comparison_20260520.md), [次のステップ計画](../roadmap/next_steps_20260521.md)

## 0. 要約 (TL;DR)

- 本研究で発生する変動費は実質 **LLM API 従量課金のみ**。実験はローカルの Docker / `.venv` で完結しており、クラウド GPU・VM・ストレージ・有償ソフトのコストは発生していない。
- 実測コストアンカー（過去レポート）から積み上げた結果、**余裕を持った上限で約 $150（約 ¥25,000）**。現実的には ¥10,000 前後で収まる見込み。
- **推奨申請額: ¥30,000〜50,000**（上限申請 + 余り返却の運用が安全。途中で枯渇すると実験が止まるため）。
- **推奨支払い方法: 国内クラウド代理店経由の「日本円・請求書払い（適格請求書あり）」**。プリペイドカード経由は「ギリギリ通るかもしれない」ライン（換金性の懸念あり）。海外クレジットカード直決済・現金・汎用ギフトコードは公費では通りにくい。

## 1. 前提条件と算定方針

- 対象期間: 2026-05-29 〜 2027-02 提出。
- 対象コスト: LLM API 利用料（役務）のみ。compute はローカル実行のためゼロ計上。
- 為替: 1 USD = **¥160** で保守換算（2026-05-29 実勢 約 ¥159.4、わずかに円安側に丸めて余裕を確保）。
- 単価: 各社 API の標準オンデマンド定価を使用。**OpenAI の無料デイリートークン枠は計上しない**（=実支払いはこれより安くなる方向。安全側の見積もり）。
- 税・手数料: 代理店経由では消費税 10% と為替手数料が乗るため、JPY 換算後に切り上げて吸収する。
- iteration 方針: 既定 `repeat 3`、本研究では 95% CI を厚くするため `repeat 5` まで上げうるので、上限見積もりは **repeat 5・全シナリオ** で計算する。

## 2. 実測コストアンカー

過去の実 API 実験レポートから、定価換算（OpenAI 無料枠は無視）の実測値:

| 実測ソース | 構成 | 1セット (8シナリオ×repeat1) | 1 run 平均 |
| --- | --- | ---: | ---: |
| [局所実験 20260419](../reports/local_experiment_cost_report_20260419.md) | multi-agent (Gemini planner) | $0.45 | $0.057 |
| [self-critique gpt-5.4 20260509](../reports/self_critique_gpt54_local_experiment_20260509.md) | single-agent gpt-5.4 | $0.21 | $0.026 |
| [Planner Escalation 20260520](../reports/planner_escalation_cost_comparison_20260520.md) | gpt-5.5 planner 単発 run | – | $0.05–0.08 |

参考単価 (1M tokens, 定価):

| Model | 入力 | 出力 |
| --- | ---: | ---: |
| `gpt-5.5` | $5.00 | $30.00 |
| `gpt-5.4` | $2.50 | $15.00 |
| `gpt-5.4-mini` | $0.75 | $4.50 |
| `gpt-4.1-mini` | $0.40 | $1.60 |
| `claude-sonnet-4-6` | $3.00 | $15.00 |
| `gemini-3-flash-preview` | $0.50 | $3.00 |

## 3. 条件別の単価見積もり

Experiment 2 は planner を `gpt-5.4`（旧レポートの安い Gemini planner より高単価）にするため、実測アンカーから引き直す。1 run のトークン量は Planner Escalation レポートの実測（scenario n, 2 turn: planner in 7.7k/out 1.1k, reviewer・judge 各 in 4k/out 0.4k）を基準に、簡単シナリオ（v/w/x = 1 turn）と難シナリオ（m/n/o/r/u = 3–5 turn）を混ぜた blended 値で算出。

| 条件 | 構成 | 1 run 平均（blended） | 8シナリオ×repeat1 |
| --- | --- | ---: | ---: |
| 2-A one-shot | gpt-5.4 単体 | $0.026 | $0.21 |
| 2-B self-critique | gpt-5.4 単体 | $0.026 | $0.21 |
| 2-C reviewer-only | planner+reviewer 共に gpt-5.4 | $0.075 | $0.60 |
| 2-D reviewer+judge | planner/reviewer/judge 共に gpt-5.4 | $0.094 | $0.75 |
| 2-E role-split | planner gpt-5.4 / reviewer Claude / judge gpt-5.4-mini / triage Gemini | $0.081 | $0.65 |
| **5 条件合計** | | | **$2.42 / repeat1 サイクル** |

- Experiment 2（5 条件 × 8 シナリオ）: repeat3 ≈ **$7**、repeat5 ≈ **$12**（iteration policy の「repeat3 で $6–18」と整合）。
- Experiment 3（Planner Escalation, `gpt-5.5` 多用で高単価）: 3 条件 × 8 シナリオ、blended 約 $0.10/run。repeat3 ≈ **$7**、repeat5 ≈ **$12**。

## 4. 残実験の物量と総額（余裕込み）

再走行（parser 修正・コード変更・Docker 失敗による pilot 切り分け）は過去レポートで頻発しているため、フル再実験 1 回分のバッファを明示的に積む。

| 項目 | 内訳 | 概算 (USD) |
| --- | --- | ---: |
| Experiment 2 本比較 | 5 条件 × 8 シナリオ × **repeat 5** | $15 |
| Experiment 3 Planner Escalation | 3 条件 × 8 シナリオ × repeat 5（`gpt-5.5`） | $15 |
| pilot / preflight smoke | 各バッチ前の予備走行 | $10 |
| フル再実験バッファ | コード変更・parser 修正・Docker 失敗での 1 回フル回し直し | $30 |
| Y1/Z1 シナリオ追加 | 追加 2 シナリオ × 複数条件 × repeat | $15 |
| ケーススタディ / turn-by-turn | 代表 1–2 シナリオの詳細走行 | $5 |
| 卒論本文化フェーズの再現走行 | 図表確定・査読対応 | $10 |
| 開発・デバッグ用 API 呼び出し | 実装修正に伴う動作確認 | $15 |
| 小計 | | **$115** |
| 予備費 30% | 価格改定・為替・無料枠廃止リスク | $35 |
| **合計** | | **約 $150** |

## 5. 段階別総額 (USD / JPY)

1 USD = ¥160、税・手数料込みで切り上げ。

| シナリオ | USD | JPY |
| --- | ---: | ---: |
| 最小（計画どおり repeat 3 のみ） | $25–30 | 約 ¥5,000 |
| 現実的（通常の再走行込み） | $60–80 | 約 ¥10,000–13,000 |
| **余裕を持った上限** | **$150** | **約 ¥25,000** |

## 6. 推奨申請額

- **推奨: ¥30,000〜50,000 を上限として申請し、余りは返却**。
- 理由: 実額は ¥1万前後に収まる見込みだが、研究費は「実験の途中で枯渇して中断する」方が致命的。為替の円安振れ・OpenAI 無料枠廃止・モデル価格改定にも耐えられる余裕を確保する。
- ¥5万でも卒研の API 費としては十分に小さく、稟議上も「LLM API 従量課金（役務）」の一本で説明しやすい。

## 7. 支払い方法（公立機関で通る順）

公立学校機関の物品・役務調達では、**現金化が容易なもの・海外クレジットカード直決済は弾かれやすい**。以下、通りやすい順。最終的には所属機関の会計規程に依存するため、**会計・事務窓口および指導教員への事前確認を必須**とする。

### ◎ 第1候補: 国内クラウド代理店経由の「日本円・請求書払い（適格請求書あり）」

最も確実に通るルートで、プリペイドのグレーゾーンを完全に回避できる。3 社のモデルは代理店経由のクラウド基盤から同じファミリーへアクセスできる。

| モデルファミリー | 経由する基盤 | 国内代理店の例 |
| --- | --- | --- |
| Claude (reviewer) | Amazon Bedrock | クラスメソッド / SB C&S / NTT 系など |
| GPT 系 (planner / judge) | Azure OpenAI Service | Microsoft 国内 CSP パートナー、JIG-SAW Prime など |
| Gemini (planner / triage) | Google Cloud Vertex AI | クラウドエース / 吉積情報など GCP 代理店 |

メリット: ①日本円建て ②適格請求書（インボイス番号付き）③後払い請求書 ④物品・役務調達の通常フローに乗る。
補足: Azure OpenAI は OpenAI 直販と異なり**請求書払いに対応**。JIG-SAW Prime のような請求代行を使うと Azure 利用料を円建て請求書で支払え、割引が付く例もある。
注意点（技術）: 実験コードは現在 OpenAI / Anthropic / Google の**ネイティブ SDK** を直接呼んでいる（`.env.example` 参照）。Bedrock / Azure / Vertex へはエンドポイント・認証の切替が必要。モデル ID（`claude-sonnet-4-6` / `gpt-5.x` / `gemini-3-flash-preview`）はほぼ対応物があるため移行コストは中程度。

### ○ 第2候補: 直販 + 適格請求書による立替精算

- OpenAI は **2025-01 に適格請求書発行事業者登録を完了**（登録番号 T4700150127989）。発行される請求書は仕入税額控除の要件を満たし、2025-01-01 以降の課金には消費税 10% が加算される。
- ただし**支払い手段はクレジットカードのみ**のため、個人（または研究室）が立替払いし、適格請求書を添えて精算する形になる。換金性がなく証憑も明確なので、立替を認める機関では数千円規模なら最も手間が軽い。
- Anthropic 直販の日本向け適格請求書対応は機関側で要確認。確実性を取るなら第1候補（代理店請求書）に寄せる。

### △ 第3候補: プリペイドカード経由（「ギリギリ通るかもしれない」ライン）

Visa/Mastercard プリペイド（Vプリカ・バンドルカード等）を**物品として購入** → OpenAI/Anthropic に登録 → クレジット購入。「海外クレカ決済」を「国内物品購入」に変換できるのが狙い。

- リスク: プリペイドは**換金性あり**として公費購入を規程で禁じている機関が多い。通すなら ①用途を「API 役務購入」と明記 ②使い切り額だけチャージし残高を残さない ③カードと API 利用明細の両方を証憑として保存。

### ✕ 通りにくい

- 海外クレジットカード直接決済 / 現金 / 汎用ギフトコード（換金性・調達フロー上の問題）。

## 8. 申請時の説明テンプレ（そのまま使える要旨）

> 本研究「LLM マルチエージェント協調を用いた自律型インフラ応急修復システム」では、エージェント構成の違いが復旧成功率・安全制約・コストに与える影響を比較するため、商用 LLM の API を従量課金で利用する。実験計算機はローカル環境で完結し、追加のハードウェア・クラウド計算資源は要しない。必要経費は API 利用料（役務）のみで、残期間（〜2027-02）の総額は余裕を見て **¥30,000〜50,000** を見込む。支払いは国内クラウド代理店を通じた日本円・請求書払い（適格請求書）を予定する。

## 9. 確認事項（事務・指導教員へ）

- 「国内クラウド代理店経由のクラウド従量課金（Azure OpenAI / Amazon Bedrock / Vertex AI）を**請求書払い**できるか」を会計・事務窓口に先に確認する。
- 立替払いの上限額・適格請求書要件（インボイス番号必須か）を確認する。
- プリペイドカード購入が公費で認められるか（多くの機関で換金性により制限）を確認する。
- 規程は機関ごとに異なるため、本レポートの方法論は一般的指針として扱い、最終判断は所属機関の規程に従う。

## 価格・為替ソース

- OpenAI モデル価格: https://developers.openai.com/api/docs/models/
- Anthropic Claude 価格: https://platform.claude.com/docs/en/about-claude/pricing
- Google Gemini 価格: https://ai.google.dev/gemini-api/docs/pricing
- OpenAI 適格請求書 / 日本の消費税: [OpenAI Help (JCT)](https://help.openai.com/ja-jp/articles/10242647-the-japanese-consumption-tax-on-your-openai-invoices)
- USD/JPY 実勢 (2026-05-29, 約 ¥159.4): [Bank of Japan FX daily](https://www.boj.or.jp/en/statistics/market/forex/fxdaily/fxlist/index.htm), [Trading Economics JPY](https://tradingeconomics.com/japan/currency)
- 国内代理店の日本円・請求書払い例 (Azure): [JIG-SAW Prime](https://ops.jig-saw.com/service/cloud/payment/azure), [SB C&S Azure OpenAI 解説](https://licensecounter.jp/azure/blog/azure-basic-knowledge/azure-openai-service.html)

## 関連ドキュメント

- [2026-05-21 次のステップ計画](../roadmap/next_steps_20260521.md) — 残り実験 (Experiment 2 / 3, Y1/Z1) の規模と条件。本概算の数量根拠。
- [2026-05-08 現在地](../current_status_20260508.md) — 進捗と残タスク。
- コストレポート: [Phase 1](../reports/phase1_compare_cost_report_20260414.md), [局所実験](../reports/local_experiment_cost_report_20260419.md), [self-critique GPT-5.4](../reports/self_critique_gpt54_local_experiment_20260509.md), [Planner Escalation](../reports/planner_escalation_cost_comparison_20260520.md)
