# Experiment 2 ベースライン比較レポート (2026-05-21)

## 要約

Experiment 2 では、障害注入環境に対する LLM エージェントの復旧性能を、同一シナリオ集合 `m n o r u v w x`、同一 `repeat=3`、同一 blind prompt、同一 forced scenario mode、同一 restore 禁止条件で比較した。

5 条件のうち、最も良い raw success / adjusted success を示したのは role-split 条件である。

| 条件 | raw success | adjusted success | 主な特徴 |
|---|---:|---:|---|
| 2-A one-shot | 6/24 = 25.00% | 12/24 = 50.00% | 低コストだが追加推論なし。`n` / `r` は環境起動待ち補正で成功相当 |
| 2-B self-critique | 12/24 = 50.00% | 12/24 = 50.00% | 単独 baseline として安定。`n` / `v` / `w` に強い |
| 2-C reviewer-only | 9/24 = 37.50% | 9/24 = 37.50% | reviewer 追加だけでは今回は伸びず、空プランが増えた |
| 2-D reviewer + judge | 11/24 = 45.83% | 11/24 = 45.83% | judge が安全側判断を増やすが、成功率は self-critique 未満 |
| 2-E role-split | 15/24 = 62.50% | 15/24 = 62.50% | 最高性能。`r` と `u` が大きく改善 |

この結果は、研究上かなり良い baseline として扱える。one-shot / self-critique / reviewer-only / reviewer+judge / role-split の 5 条件が同じ条件で揃い、特に role-split が単なるコスト増ではなく成功率を押し上げることを示したためである。

一方で、`m` と `x` は全またはほぼ全条件で失敗が残った。これは Experiment 3 で planner escalation や観測設計を試す価値がある、きれいな未解決領域でもある。

## 実験目的

本実験の目的は、単一エージェントから multi-agent / role-split 構成へ制御構造を増やしたとき、以下がどのように変化するかを比較することである。

- 復旧成功率
- 環境要因を補正した adjusted success
- 空プラン・危険 action block・judge retry / stop
- 追加観測の利用と observability bottleneck
- token 使用量、API cost、cost per successful recovery
- 仮説更新・批判後の変化・誤仮説固着

卒業研究の観点では、単に「LLM が直せるか」を見るだけでは不十分である。重要なのは、誤仮説に固着したときに観測やレビューで修正できるか、安全制約が危険な修正を止められるか、そしてその制御構造がコストに見合うかである。

## 実験条件

共通条件:

- scenarios: `m n o r u v w x`
- repeat: `3`
- worker: `llm`
- prompt mode: `blind`
- scenario mode: `forced`
- restore policy: `RESTORE_FROM_BASE_MODE=forbid`
- controlled experiment のため `.env` は編集せず、すべて一時環境変数で指定した

実行前 preflight:

```bash
git status --short
docker compose version
docker info >/dev/null
./check.sh
```

`./check.sh` は `115 passed, 6 deselected` で成功した。実験完了後の `git status --short` は空であり、実験中にコード変更は挟んでいない。

## 実行ディレクトリ

| ID | 条件 | summary.csv |
|---|---|---|
| 2-A | one-shot | `observations/20260521T072741Z_iter_controlled_oneshot_gpt54_r3/summary.csv` |
| 2-B | self-critique | `observations/20260521T081734Z_iter_controlled_selfcritique_gpt54_r3/summary.csv` |
| 2-C | reviewer-only | `observations/20260521T090534Z_iter_controlled_reviewer_only_gpt54_r3/summary.csv` |
| 2-D | reviewer + judge | `observations/20260521T094857Z_iter_controlled_multi_gpt54_r3/summary.csv` |
| 2-E | role-split | `observations/20260521T103948Z_iter_role_split_claude_reviewer_gpt54mini_judge_r3/summary.csv` |

## 実行コマンド

代表として role-split 条件の command を示す。他の 4 条件も AGENTS.md の Experiment 2 に記載された command をそのまま使用した。

```bash
env \
  PLANNER_PROVIDER=openai \
  PLANNER_MODEL=gpt-5.4 \
  REVIEWER_PROVIDER=anthropic \
  REVIEWER_MODEL=claude-sonnet-4-6 \
  JUDGE_PROVIDER=openai \
  JUDGE_MODEL=gpt-5.4-mini \
  TRIAGE_PROVIDER=google \
  TRIAGE_MODEL=gemini-3-flash-preview \
  RESTORE_FROM_BASE_MODE=forbid \
  MULTI_AGENT_JUDGE_MODE=enabled \
  MULTI_AGENT_MAX_TURNS=5 \
  MULTI_AGENT_MAX_ADDITIONAL_OBSERVATIONS=3 \
  ./observe_runs.sh m n o r u v w x \
  --agent-entrypoint multi_agent.py \
  --worker llm \
  --prompt-mode blind \
  --scenario-mode forced \
  --repeat 3 \
  --python ./.venv/bin/python \
  --label iter_role_split_claude_reviewer_gpt54mini_judge_r3
```

## シナリオ別結果

| scenario | 2-A one-shot | 2-B self-critique | 2-C reviewer-only | 2-D reviewer+judge | 2-E role-split |
|---|---:|---:|---:|---:|---:|
| m | 0/3 | 1/3 | 0/3 | 0/3 | 0/3 |
| n | 0/3 | 3/3 | 3/3 | 3/3 | 3/3 |
| o | 0/3 | 2/3 | 0/3 | 1/3 | 1/3 |
| r | 0/3 | 0/3 | 0/3 | 0/3 | 2/3 |
| u | 0/3 | 0/3 | 0/3 | 1/3 | 3/3 |
| v | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 |
| w | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 |
| x | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 |

`v` と `w` は全条件で安定して成功した。`n` は one-shot 以外では 3/3 で、自己反省または reviewer / judge のいずれかが入ると解ける安定シナリオになっている。

最も差が出たのは `r` と `u` である。role-split は `r=2/3`、`u=3/3` まで改善した。これは Claude reviewer と GPT-5.4-mini judge の組み合わせが、誤った初期仮説を押し戻し、追加観測後の修正 scope をより強く制御した可能性を示す。

`x` は全条件で 0/3 であり、現行 baseline の明確な未解決領域である。Experiment 1 の GPT-5.5 smoke では `restore_from_base` による表面上の成功があったが、controlled 条件では restore 禁止のため、ここを成功させるには別の推論または観測改善が必要である。

## 失敗分類

集計スクリプトの failure breakdown は以下の傾向を示した。

| 条件 | 主な failure bucket |
|---|---|
| 2-A one-shot | `postcheck_failure`, `env_pip_startup_failure`, `planner_reasoning_failure` |
| 2-B self-critique | `planner_reasoning_failure`, 一部 `postcheck_failure` |
| 2-C reviewer-only | 失敗はすべて `planner_reasoning_failure` |
| 2-D reviewer+judge | 主に `planner_reasoning_failure`、一部 unsafe block |
| 2-E role-split | 主に `planner_reasoning_failure`、`r` に `validation_failure` が 1 件 |

one-shot は `n` と `r` で `env_pip_startup_failure` が 3 件ずつ発生し、adjusted success では 50% まで補正された。これは修正 action 自体は妥当でも、app recreate 後の依存取得・起動待ちで postcheck が失敗する型である。

multi-agent 系の失敗は、環境失敗より planner reasoning failure に寄っている。つまり、今回の比較では transport / Docker の不安定性よりも、観測された evidence をどう解釈して安全な修正に落とすかが主要なボトルネックである。

## 安全性と judge の挙動

| 条件 | unsafe_action_blocked | safe_empty_plan | judge_stop | judge_retry | observability_bottleneck |
|---|---:|---:|---:|---:|---:|
| 2-A one-shot | 0 | 8 | 0 | 0 | 0 |
| 2-B self-critique | 0 | 11 | 0 | 0 | 2 |
| 2-C reviewer-only | 0 | 15 | 0 | 0 | 4 |
| 2-D reviewer+judge | 2 | 13 | 13 | 22 | 10 |
| 2-E role-split | 2 | 8 | 2 | 49 | 11 |

role-split は judge retry が 49 と非常に多く、turn 数も平均 3.04 と最大だった。これは単純な早期停止型ではなく、review / judge によって「まだ根拠が足りない」「修正 scope を絞るべき」と判定される回数が増えたことを示す。

この挙動はコスト増につながるが、同時に `r` と `u` の成功率改善にもつながっている。研究上は、role-split は「高コストだが、難しいシナリオで誤修正を避けながら粘る baseline」と位置づけられる。

一方で observability bottleneck も role-split で 11 と最大である。高性能な reviewer / judge を入れても、必要な exact line、full file、十分な snippet が見えていなければ、最終的な修正へ進めない。この点は Experiment 3 だけでなく、追加観測 API や worker visible context の設計課題でもある。

## 仮説遷移

result JSON 内の `hypothesis_metrics` を集計すると、制御構造を増やすほど追加観測と critique が増えた。

| 条件 | avg turns | avg critiques | avg hypothesis set updates | avg reobservations | avg reobservation effects |
|---|---:|---:|---:|---:|---:|
| 2-A one-shot | 1.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| 2-B self-critique | 1.96 | 1.46 | 0.96 | 0.96 | 0.96 |
| 2-C reviewer-only | 1.83 | 1.46 | 0.79 | 0.83 | 0.79 |
| 2-D reviewer+judge | 1.92 | 1.46 | 0.75 | 0.92 | 0.75 |
| 2-E role-split | 3.04 | 2.12 | 1.38 | 1.54 | 1.04 |

role-split は平均 turn 数と critique 数が最も多く、追加観測も最も多い。これは、単にモデルを強くしただけでなく、役割ごとの判断が run を長く保ち、誤仮説から回復する機会を増やしていることを示す。

ただし top-1 hypothesis change は role-split でも平均 0.17 に留まった。仮説集合は更新されているが、最上位仮説を大きく切り替えるほどの変化は少ない。これは「初期仮説を維持したまま scope を補正する」動きが多いことを示す可能性がある。

## コスト

直前の概算では、Experiment 2 全体を約 `$9.78`、安全側には `$12-15` と見積もった。実測 token から計算した概算 API cost は合計約 `$6.78` で、事前見積もりより低かった。

価格前提:

- OpenAI `gpt-5.4`: input `$2.50` / 1M tokens, output `$15.00` / 1M tokens
- OpenAI `gpt-5.4-mini`: input `$0.75` / 1M tokens, output `$4.50` / 1M tokens
- Anthropic `claude-sonnet-4-6`: input `$3.00` / 1M tokens, output `$15.00` / 1M tokens
- Google `gemini-3-flash-preview`: input `$0.50` / 1M tokens, output `$3.00` / 1M tokens

| 条件 | 実測概算 cost | 事前概算 | 差分 | raw success | cost / raw success |
|---|---:|---:|---:|---:|---:|
| 2-A one-shot | `$0.2341` | `$0.24` | -2.5% | 6 | `$0.0390` |
| 2-B self-critique | `$0.5446` | `$0.68` | -19.9% | 12 | `$0.0454` |
| 2-C reviewer-only | `$1.1092` | `$1.62` | -31.5% | 9 | `$0.1232` |
| 2-D reviewer+judge | `$1.8526` | `$3.94` | -53.0% | 11 | `$0.1684` |
| 2-E role-split | `$3.0357` | `$3.30` | -8.0% | 15 | `$0.2024` |

provider 別の実測概算:

| provider / model | cost |
|---|---:|
| OpenAI total | `$5.0315` |
| Anthropic total | `$1.7447` |
| Google total | `$0.0000` |
| Total | `$6.7762` |

role-split 内訳:

| component | provider / model | input tokens | output tokens | cost |
|---|---|---:|---:|---:|
| planner | OpenAI `gpt-5.4` | 323,811 | 9,645 | `$0.9542` |
| reviewer | Anthropic `claude-sonnet-4-6` | 415,488 | 33,216 | `$1.7447` |
| judge | OpenAI `gpt-5.4-mini` | 398,560 | 8,418 | `$0.3368` |

今回、事前概算より実測が下振れした主因は、pilot run の reviewer+judge がやや重かった一方、本実験では実際の output tokens と retry 分布がそこまで膨らまなかったためである。特に 2-D は事前概算 `$3.94` に対して実測 `$1.85` と大きく下振れした。

一方で、最も高価なのは明確に role-split である。Anthropic reviewer が role-split cost の約 57.5% を占めた。性能は最良だが、cost per raw success は one-shot / self-critique より高い。したがって、研究上は「最高成功率 baseline」と「費用対効果 baseline」を分けて議論する必要がある。

## ボトルネック

今回の主要ボトルネックは 4 つある。

1. `x` の failover contract mismatch

   `x` は全条件で 0/3 だった。restore 禁止条件で成功できていないため、hidden baseline に頼らない exact repair を導く観測・推論が不足している。Experiment 3 で planner escalation を試す最重要候補である。

2. `m` の誤仮説固着

   `m` は self-critique の 1/3 を除き失敗した。多くの run で database credential / app env misconfiguration に寄り、真の修正 scope へ到達できていない。role-split でも改善しなかったため、単に reviewer を強くするだけでは足りない可能性がある。

3. observability bottleneck

   reviewer+judge で 10、role-split で 11 と高い。これは「考える能力」よりも「必要な根拠が見えていない」ことが stop / retry を誘発している部分である。追加観測の上限 3 回、snippet の切り出し、full file 取得の条件が効いている可能性がある。

4. reviewer / judge retry cost

   role-split は judge retry が 49 で、平均 turn 数も 3.04 だった。成功率改善の代償として、レビューと判定が長く走る。このため、常時 role-split を使うより、失敗しやすいシナリオや retry 時だけ強い planner / reviewer を使う方が cost per successful recovery を改善できる可能性が高い。

## 研究上の意義

今回の結果は、卒業研究の主張にとってかなり良い材料である。

第一に、単純な one-shot baseline は 25% に留まったが、self-critique は 50%、role-split は 62.5% まで改善した。これは、障害復旧タスクでは「1 回の推論能力」だけでなく、追加観測、批判、判定、役割分担が性能に影響することを示している。

第二に、role-split は `r` と `u` のような中難度シナリオで明確に効いた。これは、レビューや judge の価値が全シナリオで均一に現れるのではなく、誤仮説に陥りやすい領域で特に出ることを示唆する。

第三に、安全制約の存在が結果の解釈を健全にしている。`restore_from_base` を禁止したため、hidden baseline answer による短絡成功は混ざっていない。`unsafe_action_blocked` や `safe_empty_plan` が記録されているため、成功率だけでなく「危険な成功を避けたか」も議論できる。

第四に、コスト比較が研究テーマとして成立している。最高成功率の role-split は最も高価であり、費用対効果では self-critique が強い。したがって、次の段階では「常に高い構成を使う」のではなく、「必要なときだけ escalation する」方針を評価する意義がある。

## Experiment 3 への期待

Experiment 3 では、Experiment 2 で最有力だった role-split 構成を基準に、planner policy だけを変えるのが自然である。

期待する比較:

| 条件 | 構成 | planner policy | 期待 |
|---|---|---|---|
| 3-A | role-split | standard `gpt-5.4` planner | Experiment 2 role-split の再現 baseline |
| 3-B | role-split | cheap planner + `on_retry -> gpt-5.5` | 成功率維持または微増、cost 削減 |
| 3-C | role-split | always `gpt-5.5` planner | 上限性能確認。ただし高コスト |

最初は `n o r x × repeat 3` の smoke がよい。理由は、`n` は安定成功、`o` は中間、`r` は role-split で改善、`x` は全条件失敗という性質が分かれており、少ないコストで policy 差が見えやすいためである。

Experiment 3 で期待する結果:

- `r` と `u` の成功率を維持しつつ、role-split の planner cost を下げる
- `x` で少なくとも 1/3 の restore なし成功を得る
- escalation 使用回数を 1 run あたり最大 1 に抑え、cost per successful recovery を role-split baseline より下げる
- `planner_escalation_used` と `planner_escalation_history` を使い、成功率と escalation 依存を分離して報告する

特に重要なのは、Experiment 3 が「より強いモデルを使えば成功するか」ではなく、「安い構成から始め、reviewer / judge が必要と判断したときだけ高い planner を使うと、同じ安全制約のまま費用対効果が改善するか」を検証する点である。

## 結論

Experiment 2 は、ベースライン比較として十分に良い結果になった。

role-split は raw / adjusted success ともに 62.5% で最良であり、one-shot から明確に改善した。一方、self-critique は低コストで 50% を達成しており、費用対効果 baseline として強い。reviewer-only と reviewer+judge は今回の条件では単純な上積みにならず、むしろ空プランや retry による停止が目立った。

次の焦点は、role-split の強さを保ちながら、どの run で高コスト推論を使うべきかを制御することである。Experiment 3 の planner escalation は、この研究を「成功率比較」から「安全性・観測・コストを含む運用可能なエージェント設計」へ進めるための自然な次ステップである。
