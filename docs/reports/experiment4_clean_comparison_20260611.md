# Experiment 4 クリーン本比較レポート (2026-06-11)

作成日: 2026-06-11

## 要約

Experiment 4 は、Experiment 2 で発見した 2 つのデータ品質問題を修正した上で、5 条件 (one-shot / self-critique / reviewer-only / reviewer+judge / role-split) を同一条件 `m n o r u v w x × repeat 3` で取り直したクリーン本比較である。

修正点:

1. **credential 観測経路の追加** (2026-06-10): db 認証失敗時に `db/mysql.env` の client credential を観測として露出 (root は除く)。Experiment 2 で `m/o/r` 成功が全件 credential 推測だった問題への対処。
2. **secret guess gate** (2026-06-10): credential 系 key の `new_text` に観測根拠を要求する verifier precheck。

品質ゲート:

- reviewer invocation 失敗: **0 / 134 calls** (ネットワーク交絡なし)
- credential 推測成功: **0 件** (gate + 観測露出が機能)
- secret gate 誤爆: 0 件

### 成功率 (raw = corrected; 推測成功なし)

| 条件 | total | m | n | o | r | u | v | w | x | 実測 cost |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 4-A one-shot | 1/24 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 1/3 | 0/3 | 0/3 | `$0.25` |
| 4-B self-critique | 23/24 | 3/3 | 3/3 | 3/3 | 3/3 | 2/3 | 3/3 | 3/3 | 3/3 | `$0.69` |
| 4-C reviewer-only | 18/24 | 2/3 | 3/3 | 3/3 | 3/3 | 0/3 | 2/3 | 2/3 | 3/3 | `$1.32` |
| 4-D reviewer+judge | 20/24 | 3/3 | 3/3 | 3/3 | 3/3 | 0/3 | 3/3 | 2/3 | 3/3 | `$1.41` |
| 4-E role-split | 24/24 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | `$2.04` |

これらは Experiment 2 のような credential 推測補正を必要としない (推測成功 0)。`m o r` の成功はすべて、新たに露出した db client credential を根拠とした evidence-backed な修復である。

## 実験条件

共通: `m n o r u v w x`、`--repeat 3`、`--worker llm`、`--prompt-mode blind`、`--scenario-mode forced`、`RESTORE_FROM_BASE_MODE=forbid`、triage は rule。multi-agent 系は `MULTI_AGENT_MAX_TURNS=5`、`MULTI_AGENT_MAX_ADDITIONAL_OBSERVATIONS=3`。

モデル: planner=`gpt-5.4`、reviewer=`claude-sonnet-4-6` (4-E) または `gpt-5.4` (4-C/4-D)、judge=`gpt-5.4-mini` (4-E) または `gpt-5.4` (4-D)。

observation dirs:

| 条件 | dir |
|---|---|
| 4-A | `observations/20260610T122155Z_exp4_controlled_oneshot_r3` (+ `..._resume_v`, `..._resume_wx`) |
| 4-B | `observations/20260610T132934Z_exp4_controlled_selfcritique_r3` |
| 4-C | `observations/20260610T142214Z_exp4_controlled_reviewer_only_r3` |
| 4-D | `observations/20260610T151253Z_exp4_controlled_multi_r3` |
| 4-E | `observations/20260610T160512Z_exp4_controlled_role_split_r3` |

注: 4-A は当初チェーンが画面ロック起因で `v_02` 付近で中断し、`v/w/x` を resume ラベルで取り直して 24 run を揃えた。同一コード状態・同一条件のため統合して扱う。

## 主要な発見

### 1. credential 観測修正が m/o/r を解放した

Experiment 2 では `m/o/r` の成功はすべて credential 推測であり、補正後成功率は全条件 0/9 だった (`exp2_credential_audit_20260610.md`)。db client credential を観測として露出した結果、role-split は `m/o/r` を 9/9、self-critique は 9/9、reviewer+judge は 9/9 すべて evidence-backed で解いた。

これはシナリオ `x` の topology 露出修正 (2026-05-22) に続く 2 例目の「観測可能性が支配要因」の実証であり、今回は単純故障ではなく多段マスク (`m`/`r`) と stale evidence (`o`) を含むシナリオで効いた点が強い。

### 2. role-split が初めて全完投 (24/24)

クリーン条件かつ credential 解放後、role-split は 8 シナリオ × 3 = 24 を全成功した。Experiment 2 (補正後 12/24) からの上積みは、(a) credential 露出による `m/o/r`、(b) reviewer 接続のクリーン化による安定動作の両方による。

特に `u` (topology fault が query bug をマスク) は **role-split のみ 3/3** で、reviewer-only / reviewer+judge は 0/3 だった。role-split の `u` 成功 run はいずれも平均 3-4 turn を要し、「DB host を直す → 残った SQL typo を再観測して直す」という多段の再計画を踏んでいる。Claude reviewer + GPT judge の組み合わせが、強い reviewer による段階的な scope 誘導を実現していることを示す。

### 3. one-shot が 1/24 に激減した (観測増加の副作用)

one-shot は Experiment 2 の raw 6/24 から 1/24 に下がった。これは性能劣化ではなく、**観測修正の副作用が回復能力のない構成に集中した**結果である。

`v/w` の失敗 (Experiment 2 では one-shot が 6/6 成功) はすべて precheck の `replace_text requires exactly one occurrence, found 0` であり、原因は 2026-05-22 に追加した topology contract snippet 露出にある。論理的に関連する複数キーをまとめて見せるため、planner はそれを multi-line `old_text` として `replace_text` に使い、実ファイル上で連続しないため exact-match しない (5/27 レポートで `x` の 3-B について特定した粒度問題と同一)。

multi-turn 系 (self-critique 以上) はこの precheck 失敗を次ターンで観測し、単一行 replacement に切り替えて回復する。one-shot は回復ターンがないため即失敗する。

研究上の含意: **観測情報を増やすことは万能ではなく、提示粒度と action contract が噛み合わないと、再観測・再計画できない構成をむしろ脆くする。** これは「観測可能性」と「実行可能性」のギャップ (5/27 レポート) を、制御構造の有無という軸で裏付ける独立の証拠である。one-shot を観測修正なしの Experiment 2 baseline と直接比較するのは不適切で、本比較では「multi-turn 構成の回復価値」を示す対照として扱う。

### 4. 安全指標

| 条件 | avg turns | judge_retry | judge_stop | reviewer invocation 失敗 |
|---|---:|---:|---:|---:|
| 4-B self-critique | 2.25 | - | - | 0/31 |
| 4-C reviewer-only | 2.17 | - | - | 0/34 |
| 4-D reviewer+judge | 2.17 | 28 | 4 | 0/32 |
| 4-E role-split | 2.54 | 37 | 0 | 0/37 |

role-split は turn 数と judge retry が最多で、難シナリオで「まだ根拠が足りない」と判定して粘る挙動を維持している。judge_stop が 0 なのは、credential 解放により早期 stop の必要がなくなったためと考えられる。

## コスト

| 条件 | 実測 cost (24 run) | cost / success |
|---|---:|---:|
| 4-A one-shot | `$0.25` | `$0.25` (1 success) |
| 4-B self-critique | `$0.69` | `$0.030` |
| 4-C reviewer-only | `$1.32` | `$0.073` |
| 4-D reviewer+judge | `$1.41` | `$0.071` |
| 4-E role-split | `$2.04` | `$0.085` |

費用対効果では self-critique が突出している (23/24 を `$0.69`)。role-split は最高成功率 (24/24) だが cost/success は self-critique の約 2.8 倍。卒論では引き続き「最高成功率 baseline = role-split」「費用対効果 baseline = self-critique」の二軸で議論できる。

ただし self-critique と role-split の差は `u` の 2/3 vs 3/3 のみであり、n=24 では統計的に有意ではない。主張は成功率の順位ではなく、(a) credential / topology の観測可能性が支配要因であること、(b) `u` のような多段マスクで強い reviewer の段階的 scope 誘導が効くこと、(c) 観測増加が one-shot を脆くする実行可能性ギャップ、に置く。

## Experiment 2 との対応

| | Experiment 2 (2026-05-21) | Experiment 4 (2026-06-11) |
|---|---|---|
| triage | rule (env 指定は不発) | rule |
| credential 観測 | なし → m/o/r 成功は全て推測 | db client credential 露出 → evidence-backed |
| secret gate | なし | あり (誤爆 0) |
| reviewer 接続 | クリーン (0 失敗) | クリーン (0 失敗) |
| `x` 観測 | 修正前 → 全条件 0/3 | 修正後 → ほぼ全条件 3/3 |
| role-split | raw 15/24, 補正後 12/24 | 24/24 (推測なし) |
| one-shot | raw 6/24 | 1/24 (観測増加の副作用) |

Experiment 2 は「問題を発見した pilot」、Experiment 4 は「修正後のクリーン本比較」と位置づけられる。卒論では Experiment 2 → 問題発見 (推測・観測欠落) → 設計修正 (観測露出・secret gate) → Experiment 4 という発見・対処・検証の流れで構成できる。

## 残課題

- **Experiment 3 (planner escalation) の再測定**: 2026-05-22 のデータは Anthropic 接続汚染 (3-B reviewer 86% 失敗) のため無効。クリーンな条件で取り直す。
- **action 粒度の修正は将来実験 (Exp 5) に分離**: topology snippet を実ファイル連続ブロックで出す、または planner に単一行 replacement を促す修正。これを入れれば one-shot の v/w も回復し、観測増加の副作用を消せるかを別途検証する。
- 中間発表用に 5 条件 → 3 条件 (one-shot / reviewer+judge / role-split) への畳み込み提示を検討。
