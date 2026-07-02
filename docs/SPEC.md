# NBASIC-21 言語仕様書

バージョン 1.0

NBASIC-21 は、行番号付きの古典 BASIC (Microsoft BASIC / QBasic 系統) の
互換性を保ちながら、構造化プログラミングのための現代的な機能を加えた
コンパイル型言語である。本書はコンパイラ (このリポジトリ) が受理する
言語を規定する。

- 「古典互換」: 行番号、`GOTO`/`GOSUB`、`PRINT` の桁ゾーン、
  型サフィックス、`DATA`/`READ`、暗黙の変数宣言、真理値 -1。
- 「現代的機能」: ブロック `IF`、`SELECT CASE`、`DO`/`LOOP`、
  `SUB`/`FUNCTION` (再帰可)、ローカル変数、`CONST`、`EXIT` 文、
  名前ラベル、`AS` による型宣言。

規定の細部で迷ったときは QBasic 1.1 の動作を参考にしているが、
完全互換は目標ではない (§12 の非対応機能を参照)。

---

## 1. プログラムの構造

### 1.1 行と文

- プログラムはテキスト行の並びである。文字コードは UTF-8
  (文字列リテラルとコメント以外は ASCII のみ)。
- 1 行には 0 個以上の文を書ける。同一行内の文は `:` で区切る。

      PRINT "A" : PRINT "B"

- 行の継続 (行またぎの文) は存在しない。ブロック構文
  (`IF ... END IF` など) だけが複数行にまたがる。

### 1.2 メインプログラムと手続き

`SUB`/`FUNCTION` 定義の外にある文がメインプログラムであり、記述順に
実行される。`SUB`/`FUNCTION` 定義はプログラムのどこに書いてもよく
(先頭レベルのみ、入れ子は不可)、定義位置より前から呼び出せる。
実行がメインプログラムの末尾または `END` に達するとプログラムは
終了する (実行が手続き定義の中へ「落ちる」ことはない)。

QBasic 互換の `DECLARE SUB ...` / `DECLARE FUNCTION ...` 行は
読み飛ばされる (書いても書かなくてもよい)。

---

## 2. 字句規則

### 2.1 大文字・小文字

キーワードと識別子は大文字・小文字を区別しない。`Print`、`PRINT`、
`print` はすべて同じである。本書ではキーワードを大文字で書く。

### 2.2 識別子

    識別子 = 英字または "_" , { 英数字または "_" } , [ 型サフィックス ]
    型サフィックス = "%" | "#" | "!" | "$"

型サフィックスは識別子の一部である。したがって `N` と `N%` と `N$` は
**別の変数**である。

### 2.3 数値リテラル

    整数     : 123     0     42
    16 進数  : &HFF    &h1a       (整数)
    小数     : 3.14    .5    1.   (DOUBLE)
    指数     : 1E3     2.5e-4     (DOUBLE)
    サフィックス : 1#   1!         (DOUBLE を明示)

小数点・指数部・`#`/`!` サフィックスのいずれかを含むリテラルは
DOUBLE、それ以外は INTEGER である。負のリテラルは存在しない
(`-5` は単項マイナス演算子 + リテラル 5)。

### 2.4 文字列リテラル

`"` で囲む。行をまたげない。エスケープシーケンスは無く、`"` 自体を
含めるには `""` と 2 個重ねる (古典 BASIC の規則):

    PRINT "彼は ""OK"" と言った"

### 2.5 コメント

    REM ここは行末までコメント
    ' アポストロフィでも行末までコメント
    PRINT "X"   ' 文の後ろにも書ける

### 2.6 予約語

    PRINT INPUT LET IF THEN ELSE ELSEIF END
    FOR TO STEP NEXT WHILE WEND DO LOOP UNTIL
    GOTO GOSUB RETURN DIM AS CONST REDIM
    SUB FUNCTION DECLARE CALL SELECT CASE IS
    DATA READ RESTORE REM STOP EXIT SWAP RANDOMIZE
    AND OR XOR NOT MOD INTEGER DOUBLE STRING

予約語は変数名・手続き名に使えない。組込関数名 (§10) は予約語では
ないが、同名の SUB/FUNCTION を定義するとコンパイルエラーになる。

---

## 3. 型と変数

### 3.1 型

| 型 | 内容 | 表現 |
|---|---|---|
| `INTEGER` | 64bit 符号付き整数 | -2^63 〜 2^63-1。あふれはラップアラウンド |
| `DOUBLE` | IEEE754 倍精度浮動小数点 | 約 15〜16 桁の精度 |
| `STRING` | バイト列 (イミュータブル) | 長さは 64bit。内容は任意のバイト |

古典 BASIC の単精度 (`!`) は倍精度に統合されている。`!` サフィックスは
受理されるが意味は `#` と同じ。

### 3.2 型サフィックスによる型決定

| サフィックス | 型 |
|---|---|
| `%` | INTEGER |
| `#` | DOUBLE |
| `!` | DOUBLE (古典の単精度。倍精度として扱う) |
| `$` | STRING |
| なし | DOUBLE (既定) |

サフィックスなしの変数の既定型が DOUBLE なのは古典 BASIC の伝統
(数値変数の既定は浮動小数点) に合わせたもの。整数演算をしたいときは
`%` を付けるか `DIM ... AS INTEGER` を使う。

### 3.3 変数の宣言と初期値

変数は宣言なしで使用できる。初めて現れた時点で、そのスコープに
サフィックス (無ければ既定 DOUBLE) の型で自動的に作られる。

すべての変数は使用前にゼロ初期化される: 数値は `0`、文字列は `""`。

明示宣言には `DIM` を使う:

    DIM COUNT AS INTEGER
    DIM NAME$              ' サフィックスでも型を決められる
    DIM X AS DOUBLE, Y AS DOUBLE

サフィックスと `AS` 句の型が矛盾するとコンパイルエラー
(`DIM N% AS STRING` は不可)。同じスコープでの再宣言もエラー。

### 3.4 数値の暗黙変換

- INTEGER → DOUBLE : 常に暗黙に行われる (値は保存される)。
- DOUBLE → INTEGER : 代入・引数渡し・整数系演算子の被演算子で暗黙に
  行われる。丸めは**最近接・偶数丸め** (banker's rounding):
  `2.5` → `2`、`3.5` → `4`、`-2.5` → `-2`。
- STRING と数値の間に暗黙変換は無い。`STR$`/`VAL` (または `&` 演算子)
  で明示的に変換する。

### 3.5 名前付き定数 (CONST)

    CONST PI = 3.14159265358979
    CONST MAXN% = 100, GREETING$ = "HELLO"

- 右辺はコンパイル時に評価できる定数式 (リテラル・既出の CONST・
  算術演算子・単項マイナス) でなければならない。
- CONST はメインプログラム (先頭レベル) にのみ書ける。全手続きから
  見える。代入するとコンパイルエラー。
- 型はサフィックスがあればその型、無ければ値の自然な型。

### 3.6 配列

    DIM A(10)                ' DOUBLE の 1 次元配列。添字 0..10 (11 要素)
    DIM B%(N)                ' 上限は実行時の式でよい
    DIM G$(5, 3)             ' 2 次元。添字 (0..5, 0..3)

- 添字は 0 起点で、**宣言した上限を含む** (古典 BASIC と同じ)。
  `OPTION BASE` は無い。
- 次元は 1 または 2。
- `DIM` は実行文である: 実行がその文に到達した時点で確保される。
  確保前のアクセスは実行時エラー "Array used before DIM"。
- 要素はゼロ初期化される (数値 0 / 文字列 "")。
- 範囲外の添字は実行時エラー "Subscript out of range"。
- 配列とスカラーは別の名前空間を持つ: `A` と `A(...)` は共存できる。
- 配列を手続きの引数として渡すことはできない (§12)。
- 先頭レベルで DIM した配列は大域 (全手続きから見える)。手続き内で
  DIM した配列はその手続きのローカル。

---

## 4. ラベルと制御の移動

### 4.1 行番号ラベル

物理行の先頭に置かれた整数は行番号ラベルになる。

    100 PRINT "HELLO"
    110 GOTO 100

行番号は「その位置に付けた名前」であり、昇順である必要はなく、
すべての行に付ける必要もない。同じスコープで同じ行番号を 2 回使うと
コンパイルエラーになる。

### 4.2 名前ラベルとラベルの認識規則

物理行の先頭に置かれた `識別子 :` は名前ラベルになる。

    RETRY:
      INPUT X

ラベルとして認識されるのは**物理行の先頭のみ**である。行の途中の
`識別子 :` は「引数なし SUB 呼び出し + 文区切り `:`」と解釈される。
行番号の直後に名前ラベルは書けない (`100 RETRY: ...` の `RETRY` は
SUB 呼び出しと解釈される)。

行番号・名前ラベルは `GOTO` / `GOSUB` / `RESTORE` / 単一行 IF の
ターゲットに使える。

### 4.3 GOTO / GOSUB / RETURN

    GOTO ターゲット
    GOSUB ターゲット
    RETURN

- ターゲットは**同一スコープ内** (メインプログラムまたは同じ手続きの
  中) の行番号または名前ラベル。スコープを越えるジャンプはコンパイル
  エラーになる。
- `GOSUB` は復帰位置をランタイムのスタックに積んでからジャンプする。
  `RETURN` (式なし) は最後の `GOSUB` の直後に戻る。スタックが空の
  `RETURN` は実行時エラー "RETURN without GOSUB"。
- `GOSUB` は再帰してよい (スタックは自動で伸びる)。
- ブロック構造 (FOR など) の内外をまたぐ `GOTO` はコンパイルは通るが、
  ループの一時状態を初期化せずに本体へ跳び込むと結果は未規定。
  古典プログラムの「ループからの脱出 GOTO」は問題なく動く。
- `FUNCTION` 内での `RETURN 式` は GOSUB 復帰ではなく関数からの
  復帰である (§7.3)。

---

## 5. 式と演算子

### 5.1 評価順序

式は**左から右**に評価される。`F(X) + G(X)` では必ず F が先に呼ばれる。
論理演算子 `AND`/`OR` に短絡評価は**無い** (古典 BASIC と同じ、両辺とも
常に評価される)。

### 5.2 演算子の意味

| 演算子 | 意味 | 被演算子 | 結果型 |
|---|---|---|---|
| `^` | べき乗 | 数値 (DOUBLE に変換) | DOUBLE |
| `-` (単項) | 符号反転 | 数値 | 被演算子と同じ |
| `*` | 乗算 | 数値 | 両方 INTEGER なら INTEGER、他は DOUBLE |
| `/` | 除算 | 数値 (DOUBLE に変換) | 常に DOUBLE |
| `\` | 整数除算 | 数値 (INTEGER に丸め) | INTEGER。商はゼロ方向切り捨て |
| `MOD` | 剰余 | 数値 (INTEGER に丸め) | INTEGER。符号は被除数に従う |
| `+` `-` | 加減算 | 数値 | 両方 INTEGER なら INTEGER、他は DOUBLE |
| `+` | 連結 | 両方 STRING | STRING |
| `&` | 連結 | STRING または数値 | STRING。数値は先頭空白なしで文字列化 |
| `=` `<>` `<` `<=` `>` `>=` | 比較 | 数値どうし / 文字列どうし | INTEGER (真 -1 / 偽 0) |
| `NOT` | ビット否定 | 数値 (INTEGER に丸め) | INTEGER |
| `AND` `OR` `XOR` | ビット積/和/排他的和 | 数値 (INTEGER に丸め) | INTEGER |

補足:

- `\` と `MOD` は被演算子を最近接丸めで整数化してから計算する。
  `7 \ 2 = 3`、`-7 \ 2 = -3`、`7 MOD 3 = 1`、`-7 MOD 3 = -1`。
  除数 0 は実行時エラー "Division by zero"。
- `/` は整数どうしでも実数除算: `10 / 4 = 2.5`。
- `^` の結果は常に DOUBLE。`0 ^ 負数` は "Division by zero"、
  `負数 ^ 非整数` は "Illegal function call"。
- INTEGER の加減乗算があふれた場合は 64bit でラップアラウンドする
  (エラーにはならない)。
- 文字列比較はバイト列の辞書式順序。共通接頭辞が等しければ短い方が
  小さい。
- `&` は数値を `STR$` と違って先頭空白なしで文字列化する:
  `"X=" & 5` は `"X=5"`。

### 5.3 真理値

比較の結果は INTEGER の `-1` (真) / `0` (偽)。条件文 (`IF` など) は
数値式を取り、**0 以外を真**とみなす。`NOT`/`AND`/`OR`/`XOR` はビット
演算なので、この規約と組み合わせると論理演算としても正しく働く
(`NOT -1 = 0`、`-1 AND -1 = -1`)。ただし `NOT 5 = -6` のように
0/-1 以外の値に使うとビット演算の結果になる点は古典 BASIC と同じ。

### 5.4 優先順位 (高い順)

| 順位 | 演算子 | 結合 |
|---|---|---|
| 1 | `^` | 左 |
| 2 | 単項 `-` | — |
| 3 | `*` `/` | 左 |
| 4 | `\` | 左 |
| 5 | `MOD` | 左 |
| 6 | `+` `-` (二項) | 左 |
| 7 | `&` | 左 |
| 8 | `=` `<>` `<` `<=` `>` `>=` | 左 |
| 9 | `NOT` | — |
| 10 | `AND` | 左 |
| 11 | `OR` | 左 |
| 12 | `XOR` | 左 |

古典 BASIC と同じく `^` は単項マイナスより強い: `-2 ^ 2 = -(2^2) = -4`。
`2 ^ -3` のように右辺の単項マイナスは直接書ける。
`^` は左結合: `2 ^ 3 ^ 2 = (2^3)^2 = 64`。

---

## 6. 文

### 6.1 代入

    [LET] 変数 = 式
    [LET] 配列名(添字 [, 添字]) = 式

`LET` は省略可能。数値どうしは暗黙変換される (§3.4)。

### 6.2 IF

**単一行形式**:

    IF 条件 THEN 文 [: 文 ...] [ELSE 文 [: 文 ...]]
    IF 条件 THEN 行番号            ' GOTO の省略形 (古典互換)
    IF 条件 THEN 行番号 ELSE 行番号

**ブロック形式** (`THEN` の直後で改行するとブロック形式になる):

    IF 条件 THEN
        文...
    ELSEIF 条件 THEN
        文...
    ELSE
        文...
    END IF

`ELSEIF` は何個でも、`ELSE` は最後に 1 個だけ書ける。

### 6.3 WHILE / DO

    WHILE 条件
        文...
    WEND

    DO [WHILE 条件 | UNTIL 条件]
        文...
    LOOP [WHILE 条件 | UNTIL 条件]

- `DO`/`LOOP` の条件は前置 (0 回実行がありうる) か後置 (最低 1 回
  実行) のどちらか一方にのみ書ける。両方書くとコンパイルエラー。
- 条件を書かなければ無限ループ (`EXIT DO` で抜ける)。

### 6.4 SELECT CASE

    SELECT CASE 式
        CASE 値 [, 値 ...]        ' 一致
        CASE 下限 TO 上限          ' 範囲 (両端を含む)
        CASE IS 比較演算子 式      ' 比較
            文...
        CASE ELSE
            文...
    END SELECT

- 対象式は最初に一度だけ評価される。
- 節は上から順に照合され、最初に一致した節の本体だけが実行される
  (フォールスルーは無い)。
- 1 つの `CASE` に複数の条件をカンマで並べられる (いずれかに一致)。
- 対象式が STRING の場合、`CASE` の値も STRING でなければならない。

### 6.5 FOR / NEXT

    FOR 変数 = 開始 TO 終了 [STEP 増分]
        文...
    NEXT [変数]

- ループ変数は数値のスカラー変数。`NEXT` の変数名は省略可能だが、
  書いた場合は一致しないとコンパイルエラー。
- 開始・終了・増分はループ突入時に一度だけ評価される。本体内で
  終了値・増分の式の元の変数を書き換えてもループ回数は変わらない
  (ループ変数自体への代入は有効)。
- 継続条件は増分の符号で決まる: 増分 ≥ 0 なら `変数 <= 終了`、
  増分 < 0 なら `変数 >= 終了`。条件を最初から満たさなければ本体は
  一度も実行されない。
- ループ終了後、変数には「最後に条件を満たさなくなった値」が残る
  (`FOR I=1 TO 3` の後 `I` は 4)。

### 6.6 EXIT

    EXIT FOR / EXIT WHILE / EXIT DO      ' 最も内側の対応するループを脱出
    EXIT SUB / EXIT FUNCTION             ' 手続きから即座に戻る

対応する構造の外に書くとコンパイルエラー。

### 6.7 GOTO / GOSUB / RETURN

§4.3 を参照。

### 6.8 END / STOP

プログラムを即座に終了する (終了コード 0)。手続きの中からでもよい。
`STOP` は `END` の別名。

### 6.9 SWAP

    SWAP a, b

同じ型の 2 つの変数 (または配列要素) の値を交換する。

### 6.10 RANDOMIZE

    RANDOMIZE          ' 現在時刻で乱数系列を初期化
    RANDOMIZE 式       ' 指定した種で初期化 (数値)

`RANDOMIZE` を実行しない場合、`RND` の系列は毎回同じ (古典互換・
テスト可能性のため)。

---

## 7. 手続き (SUB / FUNCTION)

### 7.1 定義

    SUB 名前 [(仮引数 [, 仮引数 ...])]
        文...
    END SUB

    FUNCTION 名前 [(仮引数 [, 仮引数 ...])] [AS 型]
        文...
    END FUNCTION

    仮引数 = 識別子 [AS 型]

- 仮引数と FUNCTION の戻り値の型は、`AS` 句 > 型サフィックス > 既定
  (DOUBLE) の順で決まる。
- 定義は先頭レベルのみ。定義位置より前から呼び出せる (前方参照可)。
- 再帰呼び出しは直接・間接とも可能。

### 7.2 引数渡し

すべての引数は**値渡し**である (古典 BASIC の参照渡しとは異なる。
仮引数への代入は呼び出し側に影響しない)。数値は暗黙変換されて渡る。
引数の個数・型が合わなければコンパイルエラー。

### 7.3 FUNCTION の戻り値

2 つの方法がある:

    FUNCTION Fib% (N%)
        Fib% = 42            ' (1) 古典式: 関数名への代入
        RETURN 42            ' (2) 現代式: RETURN 式 (即座に戻る)
    END FUNCTION

- 関数名への代入は戻り値を設定するだけで、実行は続く。
- `RETURN 式` は戻り値を設定して即座に関数から戻る。
- どちらも実行されずに `END FUNCTION` に達した場合の戻り値は
  ゼロ値 (0 / "")。
- 関数本体の中で関数名を裸で参照すると「現在の戻り値変数」を読む。
  関数名に `(引数)` を付けると再帰呼び出しになる。

### 7.4 呼び出し

    CALL 名前(引数, ...)      ' CALL 形式
    名前 引数, 引数            ' 括弧なし形式 (古典互換)
    名前(引数, ...)           ' 括弧付き・文として
    名前                      ' 引数なし
    X = 名前(引数, ...)       ' FUNCTION は式の中で

FUNCTION を文として呼ぶと戻り値は捨てられる。

### 7.5 制限

- 組込関数 (§10) と同名の手続きは定義できない。
- `DATA` 文は手続き内に書けない (§9.1)。
- `CONST` は手続き内に書けない (§3.5)。

---

## 8. スコープ規則

1. **メインプログラムの変数** — メインで暗黙に作られた変数はメイン
   専用であり、手続きからは見えない。
2. **明示 DIM された先頭レベルの変数・配列と CONST** — 大域。
   すべての手続きから読み書きできる。
3. **手続きの変数** — 仮引数と、手続き内で暗黙に作られた変数・
   `DIM` された変数/配列はすべてその手続きのローカル。名前が大域
   (規則 2) と一致し、かつローカルに宣言していない場合は大域を
   参照する。手続き内で大域と同名の `DIM` をすればローカルになる。

名前解決の優先順位 (上が優先):

    FUNCTION 自身の名前 (戻り値変数、§7.3)
      → 仮引数・ローカル変数
      → CONST
      → 明示 DIM された大域変数
      → (どれでもなければ) ローカルとして自動生成

ラベルのスコープ: ラベルはそれを含むスコープ (メインまたは 1 個の
手続き) に属し、`GOTO`/`GOSUB` は同一スコープ内のラベルにしか
跳べない (§4.3)。

スカラーと配列は別名前空間なので、上の解決は「スカラーの名前」と
「配列の名前」それぞれについて独立に行われる。

---

## 9. 入出力と DATA

### 9.1 DATA / READ / RESTORE

    DATA 項目 [, 項目 ...]
    READ 変数 [, 変数 ...]
    RESTORE [ターゲット]

- `DATA` はメインプログラムにのみ書ける実行されない文で、項目は
  プログラム全体で 1 本の列に (ソース出現順で) 連結される。
- 項目は引用符付き文字列か、引用符なしの生テキスト (前後の空白を
  除去したもの)。引用符なしの項目にはカンマを含められない。
- `READ` は次の項目を順に取り出す。数値変数へ読むときは項目を数値と
  して解釈し (解釈できなければ 0)、文字列変数へはそのまま読む。
  項目が尽きたら実行時エラー "Out of DATA"。
- `RESTORE` は読み取り位置を先頭 (ターゲット省略時) または「指定
  ラベル以降で最初の DATA 項目」に戻す。

### 9.2 INPUT

    INPUT 変数 [, 変数 ...]
    INPUT "プロンプト" ; 変数 [, 変数 ...]
    INPUT "プロンプト" , 変数 [, 変数 ...]

- プロンプト (あれば) に続けて `? ` を表示し、1 行読み込む。
- 複数の変数には、その行のカンマ区切りの値が順に割り当てられる。
  値が足りなければ空とみなす。
- 数値変数への入力が数値として解釈できない場合は 0 になる
  (古典 BASIC の "?Redo from start" 再入力は行わない)。
- EOF に達した場合は実行時エラー "Out of input (EOF)"。

### 9.3 PRINT

    PRINT [式 [区切り 式 ...]] [区切り]

- 区切りは `;` (続けて出力) または `,` (次の 14 桁ゾーンの先頭へ)。
- 文の末尾に区切りが**無ければ**改行を出力する。末尾に `;` や `,` が
  あれば改行しない (次の PRINT が続きに出力する)。
- 数値の書式 (古典 BASIC 互換):
  - 非負数は符号の位置として先頭に空白 1 個を出力する。
  - すべての数値の直後に空白 1 個を出力する。
  - DOUBLE は最大 15 有効桁で最短表現 (整数値なら小数点なし)。
  - 例: `PRINT 1; -2; 3.5` → ` 1 -2  3.5 `
- 引数なしの `PRINT` は空行を出力する。

---

## 10. 組込関数

数値引数は必要に応じて暗黙変換される (§3.4)。

### 10.1 数値関数

| 関数 | 結果 | 意味 |
|---|---|---|
| `ABS(x)` | x と同型 | 絶対値 |
| `SGN(x)` | INTEGER | 符号 (-1 / 0 / 1) |
| `INT(x)` | INTEGER | 床関数 (負の無限大方向へ丸め)。`INT(-2.5) = -3` |
| `FIX(x)` | INTEGER | ゼロ方向切り捨て。`FIX(-2.9) = -2` |
| `CINT(x)` | INTEGER | 最近接丸め (偶数丸め)。`CINT(2.5) = 2` |

### 10.2 数学関数 (結果はすべて DOUBLE)

| 関数 | 意味 | エラー |
|---|---|---|
| `SQR(x)` | 平方根 | x < 0 は Illegal function call |
| `SIN(x)` `COS(x)` `TAN(x)` | 三角関数 (ラジアン) | |
| `ATN(x)` | 逆正接 | |
| `LOG(x)` | 自然対数 | x ≤ 0 は Illegal function call |
| `EXP(x)` | e^x | |

### 10.3 文字列関数

位置はすべて **1 起点**。

| 関数 | 結果 | 意味 |
|---|---|---|
| `LEN(s$)` | INTEGER | バイト数 |
| `ASC(s$)` | INTEGER | 先頭バイトの値。`ASC("")` はエラー |
| `CHR$(n)` | STRING | バイト値 n (0..255) の 1 文字。範囲外はエラー |
| `STR$(x)` | STRING | 数値の文字列化。非負数は先頭に空白 1 個 |
| `VAL(s$)` | DOUBLE | 先頭の数値表現を解釈。無ければ 0 |
| `LEFT$(s$, n)` | STRING | 先頭 n バイト (n > 長さなら全体) |
| `RIGHT$(s$, n)` | STRING | 末尾 n バイト |
| `MID$(s$, i [, n])` | STRING | i バイト目から n バイト (n 省略で末尾まで)。i < 1 はエラー |
| `INSTR([i,] s$, t$)` | INTEGER | i 位置以降で t$ が最初に現れる位置。無ければ 0。`t$=""` は i |
| `UCASE$(s$)` / `LCASE$(s$)` | STRING | ASCII の大文字化 / 小文字化 |
| `SPACE$(n)` | STRING | 空白 n 個 |

### 10.4 乱数・時刻

| 関数 | 結果 | 意味 |
|---|---|---|
| `RND` / `RND(x)` | DOUBLE | [0, 1) の一様乱数。引数は互換のため受理して無視 |
| `TIMER` | DOUBLE | ローカル時刻での深夜 0 時からの経過秒 (整数秒精度) |

`RND` と `TIMER` は引数なしで裸の識別子として書ける
(同名の変数を先に作っていた場合は変数が優先される)。

---

## 11. 実行時エラー

実行時エラーが起きるとプログラムは

    ?RUNTIME ERROR: <メッセージ>

を標準エラーに表示し、終了コード 1 で終了する。エラーの捕捉
(`ON ERROR`) は無い。

| メッセージ | 原因 |
|---|---|
| Division by zero | `\`・`MOD` の除数 0、`0 ^ 負数` |
| Illegal function call | `SQR(負数)`、`LOG(0 以下)`、`CHR$(範囲外)`、`ASC("")`、`MID$` の位置 < 1 など |
| Subscript out of range | 配列の添字が範囲外、`DIM` の上限が負 |
| Array used before DIM | `DIM` 実行前の配列アクセス |
| RETURN without GOSUB | GOSUB スタックが空の `RETURN` |
| Out of DATA | `READ` する項目が残っていない |
| Out of input (EOF) | `INPUT` で入力が尽きた |
| Out of memory | メモリ確保失敗 |

## 12. 制限・非対応の機能

このコンパイラで対応しない主な古典/現代機能 (使用するとコンパイル
エラーになるか、構文エラーになる):

- `REDIM`、配列の再確保 (`REDIM` は明示的に「未対応」エラーを出す)
- 配列・文字列の手続き引数渡し、参照渡し (`BYREF`)
- `ON x GOTO/GOSUB`、`ON ERROR`
- ファイル入出力 (`OPEN`/`CLOSE`/`PRINT #` ...)、`LINE INPUT`
- `PRINT USING`、`TAB()`、`SPC()`、`WIDTH`
- 代入文としての `MID$` (`MID$(S$,2,3) = "abc"`)
- `DEF FN`、`DEFINT` などの型宣言文、`OPTION BASE`
- 画面制御 (`CLS`、`LOCATE`、`COLOR`)、グラフィック、サウンド
- ユーザー定義型 (`TYPE`)、`SHARED`/`STATIC` 宣言

メモリ管理は「終了時一括解放」方式であり、ループ内で作られた文字列や
`DIM` し直された配列のメモリは実行中は解放されない (docs/ARCHITECTURE.md
§5)。長時間走り続けるプログラムには向かない。

---

## 付録 A. 文法 (EBNF)

字句は §2 で定義済みとし、`NL` は行末、`number` `string` `ident` は
それぞれのリテラル/識別子とする。

```ebnf
program      = { toplevel } ;
toplevel     = proc-def | line ;
line         = [ label ] { statement ( ":" | NL ) } ;
label        = number            (* 物理行の先頭 *)
             | ident ":"         (* 物理行の先頭 *) ;

proc-def     = ( "SUB" ident [ params ] NL body "END" "SUB"
             | "FUNCTION" ident [ params ] [ "AS" type ] NL
                  body "END" "FUNCTION" ) ;
params       = "(" [ param { "," param } ] ")" ;
param        = ident [ "AS" type ] ;
type         = "INTEGER" | "DOUBLE" | "STRING" ;
body         = { statement ( ":" | NL ) | label } ;

statement    = assign | print | input | if | while | do | for | select
             | goto | gosub | return | end | dim | const | exitstmt
             | data | read | restore | randomize | swap | callstmt ;

assign       = [ "LET" ] lvalue "=" expr ;
lvalue       = ident [ "(" expr [ "," expr ] ")" ] ;
print        = "PRINT" [ expr { ( ";" | "," ) expr } [ ";" | "," ] ] ;
input        = "INPUT" [ string ( ";" | "," ) ] lvalue { "," lvalue } ;

if           = "IF" expr "THEN"
                 ( inline-body [ "ELSE" inline-body ]        (* 単一行 *)
                 | NL body { "ELSEIF" expr "THEN" body }
                      [ "ELSE" body ] "END" "IF" ) ;
inline-body  = number | statement { ":" statement } ;

while        = "WHILE" expr NL body "WEND" ;
do           = "DO" [ ( "WHILE" | "UNTIL" ) expr ] NL body
               "LOOP" [ ( "WHILE" | "UNTIL" ) expr ] ;
for          = "FOR" ident "=" expr "TO" expr [ "STEP" expr ] NL
               body "NEXT" [ ident ] ;
select       = "SELECT" "CASE" expr NL
               { "CASE" ( "ELSE" | case-test { "," case-test } ) NL body }
               "END" "SELECT" ;
case-test    = "IS" relop expr | expr [ "TO" expr ] ;

goto         = "GOTO" target ;
gosub        = "GOSUB" target ;
target       = number | ident ;
return       = "RETURN" [ expr ] ;
end          = "END" | "STOP" ;
exitstmt     = "EXIT" ( "FOR" | "WHILE" | "DO" | "SUB" | "FUNCTION" ) ;

dim          = "DIM" dim-item { "," dim-item } ;
dim-item     = ident [ "(" expr [ "," expr ] ")" ] [ "AS" type ] ;
const        = "CONST" ident "=" expr { "," ident "=" expr } ;
data         = "DATA" [ data-item { "," data-item } ] ;
read         = "READ" lvalue { "," lvalue } ;
restore      = "RESTORE" [ target ] ;
randomize    = "RANDOMIZE" [ expr ] ;
swap         = "SWAP" lvalue "," lvalue ;
callstmt     = "CALL" ident [ "(" [ args ] ")" ]
             | ident [ "(" args ")" | args ] ;
args         = expr { "," expr } ;

expr         = xor-expr ;
xor-expr     = or-expr  { "XOR" or-expr } ;
or-expr      = and-expr { "OR" and-expr } ;
and-expr     = not-expr { "AND" not-expr } ;
not-expr     = "NOT" not-expr | rel-expr ;
rel-expr     = cat-expr { relop cat-expr } ;
relop        = "=" | "<>" | "<" | "<=" | ">" | ">=" ;
cat-expr     = add-expr { "&" add-expr } ;
add-expr     = mod-expr { ( "+" | "-" ) mod-expr } ;
mod-expr     = idiv-expr { "MOD" idiv-expr } ;
idiv-expr    = mul-expr { "\" mul-expr } ;
mul-expr     = unary { ( "*" | "/" ) unary } ;
unary        = ( "-" | "+" ) unary | power ;
power        = primary { "^" [ "-" ] primary } ;
primary      = number | string | ident [ "(" [ args ] ")" ]
             | "(" expr ")" ;
```
