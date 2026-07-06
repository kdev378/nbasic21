# 付録 A 早見表

忘れたときにサッと引くためのページです。正確で完全な定義は
[言語仕様書 (docs/SPEC.md)](../SPEC.md) にあります。

## A.1 文 (命令) 早見表

| 書き方 | 意味 | 章 |
|---|---|---|
| `PRINT 式; 式, 式` | 表示 (`;` 続けて / `,` 桁をそろえて) | 2 |
| `変数 = 式` | 代入 | 3 |
| `INPUT "プロンプト"; 変数` | キーボード入力 | 3 |
| `IF 条件 THEN 〜 ELSEIF 〜 ELSE 〜 END IF` | 条件分岐 | 4 |
| `SELECT CASE 式 / CASE 値 / CASE ELSE / END SELECT` | 多方向分岐 | 4 |
| `FOR I%=a TO b [STEP c] 〜 NEXT I%` | 回数くり返し | 5 |
| `WHILE 条件 〜 WEND` | 条件くり返し | 5 |
| `DO 〜 LOOP [WHILE/UNTIL 条件]` | 後判定くり返し | 5 |
| `EXIT FOR / WHILE / DO / SUB / FUNCTION` | 途中で抜ける | 5, 8 |
| `DIM A%(10)` / `DIM X AS INTEGER` | 配列・変数の宣言 | 6 |
| `READ 変数` / `DATA 値, 値…` / `RESTORE` | 埋め込みデータ | 6 |
| `SWAP a, b` | 中身の交換 | 10 |
| `SUB 名前 (引数) 〜 END SUB` | 手続きの定義 | 8 |
| `FUNCTION 名前 (引数) 〜 END FUNCTION` | 関数の定義 | 8 |
| `CONST 名前 = 値` | 名前つき定数 | 11 |
| `GOSUB ラベル` / `RETURN` | 行き先を覚えて飛ぶ | 8, 15 |
| `GOTO ラベル` | 飛ぶ | (古典互換) |
| `OPEN "f" FOR INPUT/OUTPUT/APPEND AS #n` | ファイルを開く | 12 |
| `CLOSE #n` / `CLOSE` | 閉じる (省略で全部) | 12 |
| `PRINT #n, 〜` / `INPUT #n, 〜` / `LINE INPUT #n, s$` | ファイル読み書き | 12 |
| `LINE INPUT s$` | 1 行丸ごと入力 | 13 |
| `CLS` / `LOCATE 行, 桁` / `COLOR 文字, 背景` | 画面制御 | 14 |
| `SLEEP 秒` | 待つ (小数可) | 14 |
| `RANDOMIZE` | 乱数の種を変える | 11 |
| `END [終了コード]` | プログラム終了 | 13 |

## A.2 演算子 (優先順位の高い順)

| 演算子 | 意味 |
|---|---|
| `^` | べき乗 |
| `-` (単項) | 符号反転 |
| `*` `/` | かけ算・わり算 |
| `\` | 整数わり算 (商) |
| `MOD` | 余り |
| `+` `-` | たし算・ひき算 (文字列の `+` は連結) |
| `&` | 文字列連結 (数値は自動で文字列化) |
| `=` `<>` `<` `<=` `>` `>=` | 比較 (真 = -1, 偽 = 0) |
| `NOT` → `AND` → `OR` → `XOR` | 論理演算 |

## A.3 組込関数早見表

**数値** (10 章までに登場):

| 関数 | 意味 | 例 → 結果 |
|---|---|---|
| `ABS(x)` | 絶対値 | `ABS(-5)` → 5 |
| `INT(x)` | 切り捨て (小さい方へ) | `INT(3.7)` → 3、`INT(-2.5)` → -3 |
| `FIX(x)` | 切り捨て (0 方向) | `FIX(-2.9)` → -2 |
| `CINT(x)` | 四捨五入 (偶数丸め) | `CINT(3.5)` → 4 |
| `SGN(x)` | 符号 | `SGN(-9)` → -1 |
| `SQR(x)` | 平方根 | `SQR(9)` → 3 |
| `SIN COS TAN ATN` | 三角関数 (ラジアン) | |
| `LOG(x)` / `EXP(x)` | 自然対数 / e の x 乗 | |
| `RND` | 0 以上 1 未満の乱数 | `INT(RND*6)+1` でサイコロ |
| `TIMER` | 深夜 0 時からの秒数 | 時間計測に |

**文字列** (第 7 章):

| 関数 | 意味 | 例 → 結果 |
|---|---|---|
| `LEN(s$)` | 長さ | `LEN("ABC")` → 3 |
| `LEFT$(s$,n)` / `RIGHT$(s$,n)` | 左/右から n 文字 | `LEFT$("HELLO",2)` → "HE" |
| `MID$(s$,i,n)` | i 文字目から n 文字 | `MID$("HELLO",2,3)` → "ELL" |
| `INSTR(s$,t$)` | t$ の位置 (無ければ 0) | `INSTR("HELLO","L")` → 3 |
| `UCASE$(s$)` / `LCASE$(s$)` | 大文字/小文字化 | |
| `CHR$(n)` / `ASC(s$)` | 番号→文字 / 文字→番号 | `CHR$(65)` → "A" |
| `STR$(x)` / `VAL(s$)` | 数→文字列 / 文字列→数 | `VAL("42")` → 42 |
| `SPACE$(n)` | 空白 n 個 | 行の消去に |

**CLI / TUI** (第 13〜14 章):

| 関数 | 意味 |
|---|---|
| `COMMAND$(n)` | n 番目のコマンドライン引数 (無ければ "") |
| `EOF(n)` | ファイル n が終端なら真。`EOF(0)` は標準入力 |
| `INKEY$` | 押されたキー 1 つ (押されてなければ "") |

## A.4 定番イディオム集

```basic
' (これは断片です — 型として覚えるコード片)

' 1〜N のサイコロ
D% = INT(RND * 6) + 1

' 累積 (合計)
TOTAL% = 0
FOR I% = 0 TO N% - 1
  TOTAL% = TOTAL% + A%(I%)
NEXT I%

' 暫定チャンピオン (最大値)
MAX% = A%(0)
FOR I% = 1 TO N% - 1
  IF A%(I%) > MAX% THEN MAX% = A%(I%)
NEXT I%

' ファイルを最後まで読む
OPEN "f.txt" FOR INPUT AS #1
WHILE NOT EOF(1)
  LINE INPUT #1, L$
WEND
CLOSE #1

' 標準入力を最後まで読む (フィルタ)
WHILE NOT EOF(0)
  LINE INPUT L$
WEND

' ゲームループ
DO
  K$ = INKEY$
  IF K$ = "q" THEN EXIT DO
  ' 更新して描く
  SLEEP 0.03
LOOP
```

---

[← 第 16 章](16-todo-app.md) | [目次](README.md) | [付録 B: エラー辞典 →](appendix-b-errors.md)
