# Docs Agent Guide

このファイルは、`docs/` 配下のドキュメントと `docs/wiki/` を更新するエージェント向けの手順である。

## Scope

対象:

- `docs/**/*.md`
- `docs/wiki/_build.sh`
- `docs/wiki/_template.html`
- `docs/wiki/_link_map.sed`
- `docs/wiki/index.html`
- `docs/wiki/*.html`

原則として、Wiki の内容は Markdown を source of truth とし、HTML は `docs/wiki/_build.sh` で生成する。

## Adding A New Report To Wiki

新しいレポート Markdown を Wiki に出す場合は、以下をすべて行う。

1. Markdown を `docs/reports/` など適切な場所に作成する。
2. `docs/wiki/_build.sh` に `build` entry を追加する。
3. `docs/wiki/_link_map.sed` に Markdown から HTML への変換ルールを追加する。
4. `docs/wiki/index.html` の sidebar にリンクを追加する。
5. `docs/wiki/index.html` の該当カテゴリに card を追加する。
6. `docs/wiki/_template.html` の sidebar に同じリンクを追加する。
7. `docs/wiki/_build.sh` を実行して HTML を再生成する。
8. 生成された HTML と、既存の代表ページの sidebar にリンクが存在することを確認する。

重要: `index.html` だけを更新してはいけない。各生成ページは `_template.html` の sidebar を使うため、`_template.html` を更新しないと、トップページ以外へ遷移した時にリンクが消える。

## Build Entry Pattern

`docs/wiki/_build.sh` には以下の形式で追加する。

```bash
build "docs/reports/example_report_20260520.md" "report-example.html" \
  "Example Report" \
  '<a href="index.html">Wiki</a> / レポート / Example Report' \
  "../reports/example_report_20260520.md"
```

出力 HTML 名は既存と同じく、短く安定した kebab-case にする。

## Link Map Pattern

`docs/wiki/_link_map.sed` には、少なくとも次の 2 種類を追加する。

```sed
s|\.\./reports/example_report_20260520\.md|report-example.html|g
s|docs/reports/example_report_20260520\.md|report-example.html|g
```

Markdown 内から相対リンクする場合と、repo root からのパスを書く場合の両方を吸収するためである。

## Sidebar Consistency

sidebar のリンクは、以下の 2 ファイルで必ず揃える。

- `docs/wiki/index.html`
- `docs/wiki/_template.html`

追加例:

```html
<li><a href="report-example.html" data-id="report-example">Example Report</a></li>
```

`data-id` は HTML ファイル名から `.html` を除いた値にする。

## Index Card

Wiki トップの該当カテゴリには card を追加する。

```html
<div class="card">
  <span class="tag">2026-05-20</span>
  <h3><a href="report-example.html">Example Report</a></h3>
  <p>このレポートが何を比較・整理したものかを 1 文で書く。</p>
</div>
```

## Build Command

Wiki を再生成する。

```bash
docs/wiki/_build.sh
```

`pandoc` が必要である。失敗した場合は、エラーになった Markdown、template、link map のどれが原因かを確認する。

## Verification

最低限、以下を確認する。

```bash
test -f docs/wiki/report-example.html
rg -n "report-example.html|Example Report" docs/wiki/index.html docs/wiki/_template.html docs/wiki/report-example.html
rg -l "report-example.html" docs/wiki/*.html | sort
```

最後の `rg -l` で、生成済みの各 Wiki ページに sidebar link が入っていることを確認する。

代表ページだけをスポット確認する場合:

```bash
for f in docs/wiki/index.html docs/wiki/overview.html docs/wiki/report-analysis.html docs/wiki/report-example.html; do
  printf '%s ' "$f"
  rg -c "report-example.html" "$f"
done
```

## Editing Existing Reports

既存 Markdown を編集した場合:

1. Source Markdown を編集する。
2. `docs/wiki/_build.sh` を実行する。
3. 対応する HTML が更新されていることを `rg` で確認する。

HTML だけを直接編集してはいけない。ただし `docs/wiki/index.html` は手書きの入口ページなので、トップページの構造を変える場合は直接編集してよい。

## Notes For Future Agents

- Wiki 生成物は flat HTML であり、ページ間リンクは `_link_map.sed` で変換する。
- 新しい report を追加したら、`docs/wiki/_build.sh`、`docs/wiki/_template.html`、`docs/wiki/index.html`、`docs/wiki/_link_map.sed` の 4 点を同時に確認する。
- 生成済み HTML は差分が大きくなることがある。関係ない HTML churn を避けるため、必要な時だけ build する。
- ユーザーの未コミット変更を戻さない。
