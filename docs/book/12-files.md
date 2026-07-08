# 第 12 章 ファイルに残す

いままでのプログラムは、終わった瞬間にすべてを忘れました (第 3 章
で予告した通りです)。**ファイル**に書き込めば、データはプログラムが
終わっても、パソコンを再起動しても残ります。ここから、あなたの
プログラムは「実用品」になります。

## 12.1 書き込む — OPEN と PRINT #

ファイル操作は「開く → 読み書き → 閉じる」の 3 拍子です。
冷蔵庫と同じで、開けたら必ず閉めます。

```basic
' kakikomi.bas — ファイルに書く
OPEN "memo.txt" FOR OUTPUT AS #1
PRINT #1, "牛乳を買う"
PRINT #1, "たまごを買う"
PRINT #1, "本を返す"
CLOSE #1
PRINT "memo.txt に保存しました"
```

実行すると、プログラムと同じフォルダに `memo.txt` ができます。
メモ帳や VS Code で開いて確認してみてください。

1 行ずつ解説します:

- `OPEN "ファイル名" FOR OUTPUT AS #1` — memo.txt を**書き込み用**に
  開き、以後 **1 番** と呼ぶ、という宣言。番号は 1〜15 が使えて、
  複数のファイルを同時に開くときの区別に使います。
- `PRINT #1, ...` — ふつうの PRINT と同じ書き方で、画面ではなく
  1 番のファイルに書く。
- `CLOSE #1` — 1 番を閉じる。**閉じ忘れると最後の書き込みが
  消えることがあります**。

モードは 3 種類:

| モード | 意味 | ファイルが既にあったら |
|---|---|---|
| `FOR OUTPUT` | 新規書き込み | **中身を消して**書き直す |
| `FOR APPEND` | 追記 | 末尾に付け足す |
| `FOR INPUT` | 読み取り | (無かったら実行時エラー) |

`OUTPUT` は上書きです。日記のようなデータに毎回 OUTPUT を使うと
昨日までの分が消えます。付け足しは `APPEND`:

```basic
' tsuiki.bas — 実行するたびに 1 行増える
OPEN "log.txt" FOR APPEND AS #1
PRINT #1, "実行しました: "; TIMER; "秒 (深夜 0 時から)"
CLOSE #1
```

## 12.2 読み取る — LINE INPUT # と EOF

書いたものを読み返します。ファイルを読むときの定番の形が
これです。**丸暗記する価値があります**:

```basic
' yomikomi.bas — ファイルを 1 行ずつ読む
OPEN "memo.txt" FOR INPUT AS #1
N% = 0
WHILE NOT EOF(1)             ' 1 番のファイルが終わっていないあいだ
  LINE INPUT #1, L$          ' 1 行読んで L$ に入れる
  N% = N% + 1
  PRINT N%; ": "; L$
WEND
CLOSE #1
```

```text
 1 : 牛乳を買う
 2 : たまごを買う
 3 : 本を返す
```

- `LINE INPUT #1, L$` — 1 行を丸ごと読み取る。
- `EOF(1)` — 1 番のファイルが終端 (End Of File) に達していたら真。
- `WHILE NOT EOF(1)` — つまり「終わるまで読み続けろ」。

ファイルが何行あるか知らなくても、この形なら最後まで読めます。

## 12.3 データを区切って保存する — CSV

「名前と点数」のような**組のデータ**は、カンマで区切って
1 行に保存するのが定番です (CSV 形式といい、Excel でも開けます):

```basic
' seiseki-save.bas — 成績を CSV で保存
OPEN "seiseki.csv" FOR OUTPUT AS #1
PRINT #1, "ALICE,"; 80
PRINT #1, "BOB,"; 65
PRINT #1, "CAROL,"; 92
CLOSE #1
```

読むときは `INPUT #` を使うと、**カンマで区切られた項目を順に**
受け取れます:

```basic
' seiseki-load.bas — CSV を読んで集計
OPEN "seiseki.csv" FOR INPUT AS #1
TOTAL% = 0
N% = 0
WHILE NOT EOF(1)
  INPUT #1, NAME$, SCORE%    ' 1 行から「名前, 点数」を受け取る
  PRINT NAME$; "さん:"; SCORE%; "点"
  TOTAL% = TOTAL% + SCORE%
  N% = N% + 1
WEND
CLOSE #1
PRINT "平均:"; TOTAL% / N%
```

```text
ALICEさん: 80 点
BOBさん: 65 点
CAROLさん: 92 点
平均: 79 
```

`LINE INPUT #` (1 行丸ごと) と `INPUT #` (項目ごと) の使い分け:
中身を加工したいだけなら INPUT #、行の形のまま扱いたいなら
LINE INPUT #、が目安です。

## 12.4 配列とファイルの往復

第 6 章の配列とつなげると、「読み込む → 処理する → 書き戻す」
という実用プログラムの黄金パターンが完成します:

```basic
' tenko.bas — 点数ファイルを読み、ソートして書き戻す
DIM V%(99)

' ---- 読み込み (何件あるか分からないので数えながら) ----
OPEN "ten.txt" FOR INPUT AS #1
N% = 0
WHILE NOT EOF(1) AND N% <= 99
  INPUT #1, V%(N%)
  N% = N% + 1
WEND
CLOSE #1

' ---- ソート (第 10 章のバブルソート) ----
FOR P% = 0 TO N% - 2
  FOR I% = 0 TO N% - 2 - P%
    IF V%(I%) > V%(I% + 1) THEN SWAP V%(I%), V%(I% + 1)
  NEXT I%
NEXT P%

' ---- 書き戻し ----
OPEN "ten-sorted.txt" FOR OUTPUT AS #2
FOR I% = 0 TO N% - 1
  PRINT #2, V%(I%)
NEXT I%
CLOSE #2
PRINT N%; "件を並べ替えて ten-sorted.txt に保存しました"
```

試すには、メモ帳で `ten.txt` を作って数を 1 行に 1 つずつ
書いておきます (または `PRINT #` で作るプログラムを先に走らせても)。

「読み込みで N% を数えておいて、以後のループはすべて N% 件まで」
という形に注目してください。配列は大きめに確保しておき、
実際の件数は変数で管理する — 定番の作法です。

## 12.5 エラーと後始末

ファイル操作にはプログラム外の事情によるエラーがつきものです:

| エラー表示 | 原因 |
|---|---|
| `File not found` | FOR INPUT で開こうとしたファイルが無い |
| `File already open` | 同じ番号で二重に OPEN した (CLOSE 忘れ) |
| `Input past end of file` | 終端を越えて読んだ (EOF チェック忘れ) |

`CLOSE` は番号を省略すると開いているファイルを全部閉じます。
プログラム終了時には自動で閉じられますが、「開けたら閉める」を
指で覚えておくと、後で他の言語に移ったときにも身を助けます。

## 他の言語では

```text
NBASIC-21 :  OPEN "a.txt" FOR INPUT AS #1 / LINE INPUT #1, L$ / CLOSE #1
Python    :  f = open("a.txt") / line = f.readline() / f.close()
C         :  FILE *f = fopen("a.txt","r"); fgets(...); fclose(f);
```

「開く→読み書き→閉じる」の 3 拍子、EOF まで回すループ、CSV —
すべてそのまま他言語の日常です。

## 練習問題

1. 好きな言葉を 5 行、`INPUT` で受け取ってファイルに保存する
   プログラムと、それを読み出して行番号つきで表示するプログラムを
   書いてください。
2. 12.4 の tenko.bas 用のテストデータ (1〜100 の乱数 30 個) を
   `ten.txt` に書き出すプログラムを書いてください。
3. seiseki.csv を読んで、**最高点の人の名前**を表示してください
   (第 6 章の暫定チャンピオン方式を、名前つきで)。
4. `log.txt` に追記された行数を数えて「これで N 回目の実行です」と
   表示するプログラムを書いてください (読んで数えてから、追記する)。

[答えはこちら](answers.md#第-12-章)

---

[← 第 11 章](11-classic-algorithms.md) | [目次](README.md) | [第 13 章 コマンドラインツールを作る →](13-cli.md)
