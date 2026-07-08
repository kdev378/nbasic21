# 第 13 章 コマンドラインツールを作る

`nbc` や `gcc` のように、ターミナルから使う道具を **CLI ツール**
(Command Line Interface) といいます。実はあなたのプログラムは
既に立派な CLI ツールです — この章では、他のツールと**連携できる**
行儀のよいツールに仕上げる 3 つの作法を学びます。

## 13.1 引数 — 起動時に注文を受け取る

`nbc run hello.bas` の `hello.bas` のように、コマンドの後ろに
書き足す情報を**コマンドライン引数**といいます。
`COMMAND$(n)` で受け取れます:

```basic
' aisatsu.bas — 引数で挨拶を変える
NAME$ = COMMAND$(1)            ' 1 つ目の引数
IF NAME$ = "" THEN
  PRINT "使い方: aisatsu 名前 [回数]"
  END 1                        ' 使い方が違うときはエラー終了 (後述)
END IF
TIMES% = VAL(COMMAND$(2))      ' 2 つ目の引数 (数値に変換)
IF TIMES% < 1 THEN TIMES% = 1  ' 省略されたら 1 回
FOR I% = 1 TO TIMES%
  PRINT "こんにちは、"; NAME$; "さん!"
NEXT I%
```

ビルドして、引数をつけて実行してみましょう:

```text
$ tools/nbc build work/aisatsu.bas
$ work/aisatsu TARO 3
こんにちは、TAROさん!
こんにちは、TAROさん!
こんにちは、TAROさん!
$ work/aisatsu
使い方: aisatsu 名前 [回数]
```

要点:

- `COMMAND$(1)` が 1 つ目、`COMMAND$(2)` が 2 つ目…。
  **無かった引数は空文字列 `""`** になるので、それで省略を検出します。
- 引数は必ず文字列で届きます。数として使うなら `VAL()`。
- 引数が足りないときに**使い方 (Usage) を表示する**のは、
  世界中の CLI ツールの共通マナーです。

## 13.2 終了コード — 成功か失敗かを報告する

さっき `END 1` と書きました。END の後ろの数字は**終了コード**と
いい、「成功なら 0、失敗なら 0 以外」で終わるのが世界共通の
約束です。人間には見えませんが、シェルや他のプログラムが見ています:

```text
$ work/aisatsu TARO && echo 成功したときだけ表示
```

`&&` は「前のコマンドが終了コード 0 だったら次を実行」という
シェルの機能です。あなたのツールが正しく 0 / 非 0 を返せば、
こうした自動化の部品として組み込めるようになります。

## 13.3 標準入力 — パイプで受け取る

CLI ツールの真骨頂は**パイプ** (`|`) です。あるコマンドの出力を、
別のコマンドの入力に流し込む仕組み:

```text
$ ls | work/mytool      (ls の結果を mytool が処理する)
```

パイプから流れてくるデータは、キーボード入力と同じ「標準入力」に
届きます。「終わりまで読む」には第 12 章の EOF ループの
標準入力版 `EOF(0)` を使います。この形も丸暗記推奨です:

```basic
' (これは断片です — 標準入力を最後まで処理する定型)
WHILE NOT EOF(0)
  LINE INPUT L$
  ' …… L$ を処理する ……
WEND
```

## 13.4 作ってみる①: 行数カウント (wc もどき)

Unix の定番ツール `wc` の簡易版。流れてきたテキストの
行数・単語数・文字数を数えます:

```basic
' kazoeru.bas — 行数・単語数・文字数を数える
LINES% = 0
WORDS% = 0
CHARS% = 0
WHILE NOT EOF(0)
  LINE INPUT L$
  LINES% = LINES% + 1
  CHARS% = CHARS% + LEN(L$) + 1        ' +1 は改行の分

  ' 単語数: 第 7 章の単語分割と同じ発想で「単語の始まり」を数える
  INWORD% = 0
  FOR I% = 1 TO LEN(L$)
    IF MID$(L$, I%, 1) = " " THEN
      INWORD% = 0
    ELSEIF INWORD% = 0 THEN
      INWORD% = 1
      WORDS% = WORDS% + 1
    END IF
  NEXT I%
WEND
PRINT LINES%; WORDS%; CHARS%
```

```text
$ tools/nbc build work/kazoeru.bas
$ work/kazoeru < memo.txt
 3  3  25
$ ls | work/kazoeru
 12  12  134
```

`< memo.txt` は「キーボードの代わりにこのファイルを流し込む」
というシェルの機能 (リダイレクト) です。プログラム側は何も
変えていないのに、キーボードでもファイルでもパイプでも動く —
標準入力という抽象化の美しさです。

## 13.5 作ってみる②: 行フィルタ (grep もどき)

「指定した言葉を含む行だけを通す」フィルタ。これも Unix の
超定番 `grep` の簡易版です:

```basic
' sagasu.bas — 指定した言葉を含む行だけ表示する
PATTERN$ = COMMAND$(1)
IF PATTERN$ = "" THEN
  PRINT "使い方: sagasu 探す言葉 < ファイル"
  END 1
END IF

N% = 0                          ' 何行目かを数えながら
HITS% = 0
WHILE NOT EOF(0)
  LINE INPUT L$
  N% = N% + 1
  IF INSTR(L$, PATTERN$) > 0 THEN     ' 含んでいたら (第 7 章)
    PRINT N%; ": "; L$
    HITS% = HITS% + 1
  END IF
WEND

IF HITS% = 0 THEN END 1         ' 見つからなかったら失敗扱い
```

```text
$ work/sagasu 買う < memo.txt
 1 : 牛乳を買う
 2 : たまごを買う
```

本物の grep も「見つからなかったら終了コード 1」で終わります。
細部まで作法をなぞってあるので、このツールはそのまま `&&` や
パイプの部品になれます。

## 13.6 作ってみる③: 家計簿の集計ツール

仕上げに、引数 + ファイル + 集計を組み合わせた「実用品」を。
`kakeibo.csv` に「日付,項目,金額」形式でためたデータを集計します:

```basic
' shukei.bas — 家計簿 CSV の集計
' 使い方: shukei ファイル名 [絞り込み語]
FILE$ = COMMAND$(1)
FILTER$ = COMMAND$(2)
IF FILE$ = "" THEN
  PRINT "使い方: shukei ファイル.csv [絞り込み語]"
  END 1
END IF

OPEN FILE$ FOR INPUT AS #1
TOTAL% = 0
N% = 0
WHILE NOT EOF(1)
  INPUT #1, DAY$, ITEM$, PRICE%
  IF FILTER$ = "" OR INSTR(ITEM$, FILTER$) > 0 THEN
    PRINT DAY$, ITEM$, PRICE%
    TOTAL% = TOTAL% + PRICE%
    N% = N% + 1
  END IF
WEND
CLOSE #1
PRINT "----------"
PRINT N%; "件 合計"; TOTAL%; "円"
```

データ (kakeibo.csv):

```text
0401,LUNCH,800
0402,BOOK,1500
0402,LUNCH,650
0403,COFFEE,400
```

```text
$ work/shukei kakeibo.csv LUNCH
0401          LUNCH          800 
0402          LUNCH          650 
----------
 2 件 合計 1450 円
```

引数 2 つ目を省略すれば全件集計。たった 25 行ですが、
「引数で振る舞いが変わり」「ファイルを読み」「使い方を案内し」
「終了コードを返す」— CLI ツールの作法をすべて備えています。

## 他の言語では

```text
NBASIC-21 :  COMMAND$(1)      EOF(0)+LINE INPUT      END 1
Python    :  sys.argv[1]      for line in sys.stdin  sys.exit(1)
C         :  argv[1]          while(fgets(...))      return 1;
```

引数・標準入出力・終了コードの 3 点セットは OS が提供する仕組み
なので、言語が変わっても**まったく同じ概念**です。ここで覚えた
作法は、シェルスクリプトを書くときにもそのまま活きます。

## 練習問題

1. 摂氏→華氏変換 (第 3 章) を、`INPUT` ではなく引数で受け取る
   ように改造してください: `henkan 25` → `77`。
2. 流れてきた行を**逆順に**出力するフィルタを書いてください
   (ヒント: いったん配列にため込み、あとから逆に出す)。
3. sagasu.bas に「大文字小文字を無視する」機能を足してください
   (ヒント: 両方 `UCASE$` してから比べる)。
4. shukei.bas に「最高額の 1 件」を表示する機能を足してください。

[答えはこちら](answers.md#第-13-章)

---

[← 第 12 章](12-files.md) | [目次](README.md) | [第 14 章 画面を自由に描く →](14-tui.md)
