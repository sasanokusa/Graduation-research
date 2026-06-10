# 関連研究サーベイメモ (2026-06-10)

作成日: 2026-06-10
目的: 卒論「関連研究」章と中間発表「位置づけ」スライドの土台。本研究の座標を 4 軸で三角測量する。

裏取り水準について:

- 各エントリの URL は 2026-06-10 時点で Web 検索により実在を確認した一次ソース (arXiv abstract ページ等) である。
- 要約は abstract / 公式ブログ / 検索結果スニペットに基づく。**卒論で引用する前に必ず本文を読むこと。**
- 「タイトルのみ確認」と付記したものは、存在と題目のみ確認済みで内容未読。

## 本研究の位置づけ (1 文版)

> 安全制約 (構造化アクション + Verifier + Rollback) を一級の実験変数とした統制可能な障害注入環境上で、エージェント制御構造 (one-shot / self-critique / reviewer / judge / role-split) と観測可能性が応急復旧の成功率・安全性・コストに与える影響を、誤仮説固着メトリクスを含めて比較した研究。

軸 1 (ドメイン) × 軸 2 (制御構造比較) × 軸 3 (安全実行) × 軸 4 (コスト) の交点を統制実験で押さえた研究は、本サーベイの範囲では見つかっていない。各軸の隣人は以下の通り。

## 軸 1: LLM × インシデント対応 / AIOps ベンチマーク

### AIOpsLab (Microsoft Research, FAST'25 / arXiv 2025)

- URL: https://arxiv.org/abs/2501.06706
- 補助: https://www.microsoft.com/en-us/research/blog/aiopslab-building-ai-agents-for-autonomous-clouds/
- 内容: マイクロサービス環境のデプロイ、障害注入、ワークロード生成、テレメトリ出力を統合し、検知・RCA・mitigation までのタスクで AI エージェントを評価するフレームワーク。ReAct / AutoGen / TaskWeaver を統合。
- 本研究との関係: 最も直球の隣人。**差分**: AIOpsLab は評価基盤の提供が主眼で、エージェント制御構造の統制比較や安全制約の実験変数化はしていない。本研究は Verifier / restore 禁止 / blind prompt を固定した条件間比較を行う。

### ITBench / ITBench-AA (IBM Research, 2025)

- URL: https://github.com/itbench-hub/ITBench
- 補助: https://research.ibm.com/blog/it-agent-benchmark / https://artificialanalysis.ai/evaluations/itbench-aa / https://huggingface.co/blog/ibm-research/itbench-aa
- 内容: SRE / FinOps / コンプライアンスの IT 自動化ベンチマーク。SRE 系は Kubernetes 実障害テンプレート由来の 59 タスク。ITBench-AA リーダーボードでは **frontier モデル全てが過半数のインシデントに失敗 (スコア 50% 未満)**。
- 本研究との関係: 「frontier モデルでも未解決」という分野状況の根拠として重要。本研究の `m`/`o`/`x` 全滅は分野水準と整合する。**差分**: ITBench は診断 (RCA) 中心で、安全制約付きの修復実行と rollback までは統制していない。

### Recommending Root-Cause and Mitigation Steps for Cloud Incidents using LLMs (Ahmed et al., ICSE 2023)

- URL: https://arxiv.org/abs/2301.03797
- 内容: Microsoft の実インシデント 4 万件超で、インシデントレポートから root cause / mitigation 推奨文を生成する初の大規模評価。
- 本研究との関係: ドメインの出発点として引用。**差分**: テキスト推奨であり、環境への実行・検証・ロールバックを伴わない。

### Stalled, Biased, and Confused (FORGE'26, arXiv 2026)

- URL: https://arxiv.org/abs/2601.22208
- 補助: https://github.com/boerste/rca-llm-reasoning
- 内容: multi-hop 障害伝播の RCA における LLM 推論失敗の統制実験。6 モデル × ReAct / Plan-and-Execute / 非エージェント baseline、48,000 シナリオ。推論失敗を procedural / RCA固有 / 一般の 3 カテゴリに分類。"Biased" は誤った初期仮説への固着を含む。
- 本研究との関係: **誤仮説固着を扱う最重要先行研究。** 本研究の hypothesis_metrics (固着長、批判後変化率) と直接対話できる。**差分**: 同論文は診断のみで修復実行なし、また「固着をどの制御構造が破れるか」(reviewer / judge / role-split の効果) は扱っていない。

### RIVA: Leveraging LLM Agents for Reliable Configuration Drift Detection (arXiv 2026) — タイトルのみ確認

- URL: https://arxiv.org/abs/2603.02345
- 本研究との関係: config drift 検出はシナリオ `x` (bilateral_dependency_drift) と重なる可能性。要精読。

### An Autonomous AI SRE Agent for Elasticsearch (arXiv 2026) — タイトルのみ確認

- URL: https://arxiv.org/abs/2604.03933
- 本研究との関係: 単一ドメイン特化の SRE エージェント実装例 (2026 年前半)。要精読。

## 軸 2: エージェント制御構造 (self-critique / multi-agent / role-split)

### Self-Refine (Madaan et al., NeurIPS 2023)

- URL: https://arxiv.org/abs/2303.17651
- 内容: 同一 LLM が生成 → 自己フィードバック → 改善を反復する枠組み。7 タスクで GPT-3.5/4 直接生成を上回る。
- 本研究との関係: 2-B self-critique 条件の概念的出典。

### Reflexion (Shinn et al., NeurIPS 2023)

- URL: https://arxiv.org/abs/2303.11366
- 内容: タスクフィードバックを言語的内省としてエピソード記憶に保持し、次試行の意思決定を改善する。
- 本研究との関係: self-critique 系のもう一つの古典。**差分**: 本研究は自己反省 (内部化された批判) と reviewer / judge (外部化された批判) を同一環境で比較する点が新しい。

### Multiagent Debate (Du et al., 2023)

- URL: https://arxiv.org/abs/2305.14325
- 内容: 複数 LLM インスタンスが回答と推論を複数ラウンド討論し、事実性と推論を改善。
- 本研究との関係: 「複数エージェントの相互批判が単体推論を上回る」一般領域の根拠。本研究はこれをインフラ復旧という実行を伴うドメインで検証する形。

### MetaGPT (Hong et al., 2023 / ICLR 2024)

- URL: https://arxiv.org/abs/2308.00352
- 内容: SOP をプロンプト列に符号化し、役割分担 (assembly line) で中間成果物を検証させる multi-agent 開発フレームワーク。
- 本研究との関係: role-split (2-E) の概念的出典その 1。

### ChatDev (Qian et al., ACL 2024)

- URL: https://arxiv.org/abs/2307.07924 / https://aclanthology.org/2024.acl-long.810/
- 内容: 設計・実装・テスト・文書化の役割エージェントが chat chain で協調するソフトウェア開発フレームワーク。
- 本研究との関係: role-split の概念的出典その 2。**差分**: コーディングドメインでは成果物検証がコンパイル/テストで閉じるが、本研究は実環境のヘルスチェックと安全制約で閉じる。

### MAST: Why Do Multi-Agent LLM Systems Fail? (Cemri et al., UC Berkeley, 2025)

- URL: https://arxiv.org/abs/2503.13657
- 補助 (ITBench との接続): https://huggingface.co/blog/ibm-research/itbenchandmast
- 内容: 7 つの MAS フレームワーク × 200+ タスクから 14 失敗モード・3 カテゴリ (specification / inter-agent misalignment / task verification) の失敗分類体系を構築。「multi-agent の性能向上は single-agent 比で僅少なことが多い」という指摘を含む。
- 本研究との関係: **本研究の failure bucket 分類 (planner_reasoning / validation / postcheck / env) と対応付けると考察章が強くなる。** また「multi-agent が常に勝つわけではない」(2-C/2-D が 2-B に勝てない) という本研究の結果は MAST の指摘と整合する。

## 軸 3: 安全な実行 (構造化アクション / Verifier / サンドボックス)

### ToolEmu (Ruan et al., ICLR 2024 Spotlight)

- URL: https://arxiv.org/abs/2309.15817
- 補助: https://github.com/ryoungj/toolemu
- 内容: LM でツール実行をエミュレートし、LM エージェントのリスクを自動特定。最安全のエージェントでも 23.9% の失敗率。
- 本研究との関係: エージェント実行リスクの定量化という問題意識を共有。**差分**: 本研究はエミュレーションではなく実コンテナ環境で、Verifier による事前検証 + rollback で安全を担保する。

### R-Judge (Yuan et al., 2024) — 概要のみ確認

- URL: https://arxiv.org/abs/2401.10019
- 内容: LLM エージェントの安全リスク認識をベンチマーク化。
- 本研究との関係: judge エージェント (安全判定役) の評価という観点で接続。

### InferAct (2024) — 概要のみ確認

- URL: https://arxiv.org/abs/2407.11843
- 内容: 危険アクションの事前評価と human feedback による安全化。
- 本研究との関係: Verifier の precheck に相当する発想の隣人。

## 軸 4: コスト最適化 (cascade / escalation)

### FrugalGPT (Chen, Zaharia, Zou, 2023)

- URL: https://arxiv.org/abs/2305.05176
- 内容: LLM cascade (安いモデルから順に試し、必要時だけ高いモデルへ) 等で GPT-4 同等性能を最大 98% 安く達成。
- 本研究との関係: **Experiment 3 planner escalation の直接の先行研究。** ただし FrugalGPT は単発クエリの cascade であり、本研究の「multi-turn 復旧ループ内で reviewer / judge の判断を trigger とする escalation」は設定が異なる。Exp 3 の negative result (escalation しても観測・action 粒度の契約が合わないと成功率が落ちる) は、cascade 文献への実行環境からの反例・条件提示として書ける。

## 関連研究章の構成案

1. LLM によるインシデント対応は推奨文生成 (Ahmed+ 2023) から実行エージェント評価 (AIOpsLab, ITBench) へ進んだが、frontier モデルでも SRE インシデントの過半が未解決 (ITBench-AA)
2. 制御構造の研究は self-critique (Self-Refine, Reflexion) と multi-agent (Debate, MetaGPT, ChatDev) が一般タスクで効果を示す一方、MAST は multi-agent の優位が自明でないことを示した
3. 安全面ではエージェント実行リスクの定量化 (ToolEmu) が進むが、安全制約を**実験変数として固定した上での制御構造比較**は行われていない
4. コスト面では cascade (FrugalGPT) があるが、multi-turn 復旧ループでの escalation 検証はない
5. → 本研究はこの交点: 安全制約固定・統制環境で、制御構造 × 観測可能性 × コストを誤仮説固着メトリクス付きで比較する

## 未調査・次の確認事項

- 国内 (情報処理学会 / 電子情報通信学会) の LLM 運用自動化系の研究会発表 — 中間発表の質疑対策として一度 CiNii / J-STAGE を見る
- 2026 年前半の新着 (RIVA, Elasticsearch SRE agent) の精読と、arXiv での "LLM incident remediation" 月次チェック
- AIOpsLab / ITBench の評価指標 (何を success と定義しているか) と本研究の adjusted success の対応表を作る
