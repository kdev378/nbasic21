# 練習問題の答え

答えは「一例」です。動けばあなたの書き方が正解。
見比べて「へえ、こうも書けるのか」と思ってもらえれば十分です。

## 第 2 章

**2-1.** (年齢が 20 歳の場合の例)

```basic
PRINT 20 * 12
```

**2-2.** 予想→確認の問題。結果は ` 2.5`、` 2`、` 2`。
`/` は小数まで割り、`\` は商だけ、`MOD` は余り (10 = 4×2 + 2)。

**2-3.**

```basic
PRINT 100 * 3 + 150 * 2
```

## 第 3 章

**3-1.**

```basic
INPUT "たての長さ"; H
INPUT "よこの長さ"; W
PRINT "面積:"; H * W
PRINT "周の長さ:"; (H + W) * 2
```

**3-2.**

```basic
INPUT "摂氏温度"; C
PRINT "華氏では"; C * 1.8 + 32; "度"
```

**3-3.** ` 3  5` と表示されます。1 行ずつ箱の中身を追うと:
A%=5, B%=3 → A%=8 → B%=8-3=5 → A%=8-5=3。
つまり **2 つの変数の中身が入れ替わっています**。一時変数なしで
交換する古典的なパズルでした (ふだんは SWAP 命令でどうぞ)。

## 第 4 章

**4-1.**

```basic
INPUT "数をどうぞ"; N
IF N > 0 THEN
  PRINT "正の数"
ELSEIF N < 0 THEN
  PRINT "負の数"
ELSE
  PRINT "ゼロ"
END IF
```

**4-2.**

```basic
INPUT "身長 (m)"; H
INPUT "体重 (kg)"; W
BMI = W / (H * H)
PRINT "BMI:"; BMI
IF BMI < 18.5 THEN
  PRINT "やせ型"
ELSEIF BMI < 25 THEN
  PRINT "ふつう"
ELSE
  PRINT "がっちり"
END IF
```

**4-3.** 条件の組み立てがすべてです:

```basic
INPUT "西暦"; Y%
IF (Y% MOD 4 = 0 AND Y% MOD 100 <> 0) OR Y% MOD 400 = 0 THEN
  PRINT Y%; "年はうるう年"
ELSE
  PRINT Y%; "年は平年"
END IF
```

## 第 5 章

**5-1.**

```basic
FOR I% = 1 TO 10
  PRINT I% * I%;
NEXT I%
PRINT
```

**5-2.** かけ算の累積は**初期値 1** がポイント (0 だと全部 0 に):

```basic
INPUT "N"; N%
F# = 1
FOR I% = 1 TO N%
  F# = F# * I%
NEXT I%
PRINT N%; "! ="; F#
```

**5-3.**

```basic
FOR I% = 1 TO 5
  FOR J% = 1 TO I%
    PRINT "*";
  NEXT J%
  PRINT
NEXT I%
```

**5-4.** (骨組みだけ。数当て本体は第 5 章のまま)

```basic
' (これは断片です — 変更点のみ)
' DO の前に:  CHANCE% = 7
' はずれたときに:
'   CHANCE% = CHANCE% - 1
'   IF CHANCE% = 0 THEN PRINT "ゲームオーバー" : EXIT DO
'   PRINT "残り"; CHANCE%; "回"
```

## 第 6 章

**6-1.**

```basic
DIM S%(6)
TOTAL% = 0
MAX% = 0
FOR I% = 0 TO 6
  READ S%(I%)
  TOTAL% = TOTAL% + S%(I%)
  IF S%(I%) > MAX% THEN MAX% = S%(I%)
NEXT I%
DATA 6800, 9200, 4500, 12000, 7300, 8100, 10500
PRINT "合計:"; TOTAL%; " 平均:"; TOTAL% / 7; " 最大:"; MAX%
```

**6-2.**

```basic
DIM A%(9)
FOR I% = 0 TO 9
  READ A%(I%)
NEXT I%
DATA 1, 2, 3, 4, 5, 6, 7, 8, 9, 10
FOR I% = 9 TO 0 STEP -1
  PRINT A%(I%);
NEXT I%
PRINT
```

**6-3.**

```basic
DIM A%(19)
RANDOMIZE
COUNT% = 0
MIN% = 101
FOR I% = 0 TO 19
  A%(I%) = INT(RND * 100) + 1
  IF A%(I%) >= 50 THEN COUNT% = COUNT% + 1
  IF A%(I%) < MIN% THEN MIN% = A%(I%)
NEXT I%
PRINT "50 以上:"; COUNT%; "個  最小値:"; MIN%
```

**6-4.** 先頭を避難させてから、左詰めして、最後に戻します:

```basic
DIM A%(4)
FOR I% = 0 TO 4
  READ A%(I%)
NEXT I%
DATA 1, 2, 3, 4, 5
T% = A%(0)
FOR I% = 0 TO 3
  A%(I%) = A%(I% + 1)
NEXT I%
A%(4) = T%
FOR I% = 0 TO 4
  PRINT A%(I%);
NEXT I%
PRINT
```

## 第 7 章

**7-1.**

```basic
INPUT "フルネーム (名 姓)"; S$
P% = INSTR(S$, " ")
IF P% = 0 THEN
  PRINT "スペースが見つかりません"
ELSE
  PRINT "名: "; LEFT$(S$, P% - 1)
  PRINT "姓: "; MID$(S$, P% + 1)
END IF
```

**7-2.**

```basic
INPUT "言葉をどうぞ"; S$
R$ = ""
FOR I% = 1 TO LEN(S$)
  R$ = MID$(S$, I%, 1) + R$
NEXT I%
IF S$ = R$ THEN
  PRINT "回文です!"
ELSE
  PRINT "回文ではありません"
END IF
```

**7-3.**

```basic
INPUT "英文をどうぞ"; S$
S$ = UCASE$(S$)
COUNT% = 0
FOR I% = 1 TO LEN(S$)
  C$ = MID$(S$, I%, 1)
  IF C$ = "A" OR C$ = "E" OR C$ = "I" OR C$ = "O" OR C$ = "U" THEN
    COUNT% = COUNT% + 1
  END IF
NEXT I%
PRINT "母音は"; COUNT%; "個"
```

**7-4.** 外側に「ずらし量のループ」をかぶせるだけ:

```basic
INPUT "暗号文"; S$
FOR K% = 1 TO 25
  R$ = ""
  FOR I% = 1 TO LEN(S$)
    C% = ASC(MID$(S$, I%, 1))
    IF C% >= ASC("A") AND C% <= ASC("Z") THEN
      C% = (C% - ASC("A") + K%) MOD 26 + ASC("A")
    END IF
    R$ = R$ + CHR$(C%)
  NEXT I%
  PRINT K%; ": "; R$
NEXT K%
```

`WKLV LV D VHFUHW` は 23 をかけたとき (= 3 ずらしの暗号)
`THIS IS A SECRET` になります。

## 第 8 章

**8-1.**

```basic
FOR Y% = 1996 TO 2004
  IF IsLeap%(Y%) THEN
    PRINT Y%; "うるう年"
  ELSE
    PRINT Y%; "平年"
  END IF
NEXT Y%

FUNCTION IsLeap% (Y%)
  IsLeap% = (Y% MOD 4 = 0 AND Y% MOD 100 <> 0) OR Y% MOD 400 = 0
END FUNCTION
```

比較の結果 (真 = -1) をそのまま返しているのに注目。

**8-2.** 「3 つの最小は、(2 つの最小) と残り 1 つの最小」:

```basic
PRINT Min3%(7, 2, 9)

FUNCTION Min2% (A%, B%)
  IF A% < B% THEN RETURN A%
  RETURN B%
END FUNCTION

FUNCTION Min3% (A%, B%, C%)
  Min3% = Min2%(Min2%(A%, B%), C%)
END FUNCTION
```

**8-3.**

```basic
PRINT Repeat$("AB", 3)

FUNCTION Repeat$ (S$, N%)
  R$ = ""
  FOR I% = 1 TO N%
    R$ = R$ + S$
  NEXT I%
  Repeat$ = R$
END FUNCTION
```

**8-4.**

```basic
FOR I% = 1 TO 10
  PRINT Fib%(I%);
NEXT I%
PRINT

FUNCTION Fib% (N%)
  IF N% <= 2 THEN
    Fib% = 1
  ELSE
    Fib% = Fib%(N% - 1) + Fib%(N% - 2)
  END IF
END FUNCTION
```

## 第 9 章

**9-1.** EXIT FOR を消して、個数を数えます:

```basic
DIM A%(9)
FOR I% = 0 TO 9
  READ A%(I%)
NEXT I%
DATA 3, 8, 3, 24, 3, 46, 13, 8, 3, 90
INPUT "探す数"; X%
COUNT% = 0
FOR I% = 0 TO 9
  IF A%(I%) = X% THEN COUNT% = COUNT% + 1
NEXT I%
PRINT COUNT%; "個ありました"
```

**9-2.** 数値が文字列になるだけで、手順は同一です。

**9-3.** 「無い」と言われたり、あるのに見つけられなかったりします。
二分探索は「真ん中より左は全部小さい」という**前提**で半分を
捨てるので、並んでいないとその前提が崩れ、正しい半分を
捨ててしまうことがあるからです。

**9-4.** 2 を 10 回かけると 1024 > 1000 なので**最悪 10 回**。

## 第 10 章

**10-1.** 比較の `>` を `<` にするだけです。

**10-2.**

```basic
DIM A%(7)
FOR I% = 0 TO 7
  READ A%(I%)
NEXT I%
DATA 64, 25, 12, 90, 8, 76, 33, 51
FOR PASS% = 0 TO 6
  MOVED% = 0
  FOR I% = 0 TO 6 - PASS%
    IF A%(I%) > A%(I% + 1) THEN
      SWAP A%(I%), A%(I% + 1)
      MOVED% = -1
    END IF
  NEXT I%
  IF MOVED% = 0 THEN EXIT FOR      ' 1 周ノー交換 = 完成
NEXT PASS%
FOR I% = 0 TO 7
  PRINT A%(I%);
NEXT I%
PRINT
```

**10-3.**

```basic
DIM A%(19)
RANDOMIZE
FOR I% = 0 TO 19
  A%(I%) = INT(RND * 100) + 1
NEXT I%
' ソート
FOR P% = 0 TO 18
  FOR I% = 0 TO 18 - P%
    IF A%(I%) > A%(I% + 1) THEN SWAP A%(I%), A%(I% + 1)
  NEXT I%
NEXT P%
FOR I% = 0 TO 19
  PRINT A%(I%);
NEXT I%
PRINT
' 二分探索
INPUT "探す数"; X%
LO% = 0
HI% = 19
FOUND% = -1
WHILE LO% <= HI%
  M% = (LO% + HI%) \ 2
  IF A%(M%) = X% THEN
    FOUND% = M%
    EXIT WHILE
  ELSEIF A%(M%) < X% THEN
    LO% = M% + 1
  ELSE
    HI% = M% - 1
  END IF
WEND
IF FOUND% >= 0 THEN
  PRINT FOUND%; "番にあります"
ELSE
  PRINT "ありません"
END IF
```

**10-4.** 点数を入れ替えるとき、名前も一緒に入れ替えるのが
すべてです:

```basic
DIM N$(4), S%(4)
FOR I% = 0 TO 4
  READ N$(I%), S%(I%)
NEXT I%
DATA ALICE, 80, BOB, 65, CAROL, 92, DAVE, 71, EMMA, 58
FOR P% = 0 TO 3
  FOR I% = 0 TO 3 - P%
    IF S%(I%) < S%(I% + 1) THEN     ' 高い順なので <
      SWAP S%(I%), S%(I% + 1)
      SWAP N$(I%), N$(I% + 1)       ' ← ここが肝
    END IF
  NEXT I%
NEXT P%
FOR I% = 0 TO 4
  PRINT I% + 1; "位: "; N$(I%); S%(I%)
NEXT I%
```

## 第 11 章

**11-1.**

```basic
INPUT "A"; A%
INPUT "B"; B%
PRINT "最大公約数:"; Gcd%(A%, B%)
PRINT "最小公倍数:"; Lcm%(A%, B%)

FUNCTION Gcd% (A%, B%)
  WHILE B% <> 0
    R% = A% MOD B%
    A% = B%
    B% = R%
  WEND
  Gcd% = A%
END FUNCTION

FUNCTION Lcm% (A%, B%)
  Lcm% = A% * B% \ Gcd%(A%, B%)
END FUNCTION
```

**11-2.** ふるいの N% を 1000 に変えて、表示の代わりに
`COUNT% = COUNT% + 1`。答えは 168。

**11-3.**

```basic
RANDOMIZE
HIT% = 0
FOR I% = 1 TO 100000
  D1% = INT(RND * 6) + 1
  D2% = INT(RND * 6) + 1
  IF D1% + D2% = 7 THEN HIT% = HIT% + 1
NEXT I%
PRINT "和が 7 の確率 ≒"; HIT% / 100000
```

**11-4.** 10 倍を **2 倍**にするだけ。基数が変わっただけで
アルゴリズムは同じ、というのがこの問題の答えです:

```basic
S$ = "101101"
N% = 0
FOR I% = 1 TO LEN(S$)
  N% = N% * 2 + (ASC(MID$(S$, I%, 1)) - ASC("0"))
NEXT I%
PRINT N%       ' 45
```

## 第 12 章

**12-1.**

```basic
' 保存する側
OPEN "kotoba.txt" FOR OUTPUT AS #1
FOR I% = 1 TO 5
  INPUT "好きな言葉"; S$
  PRINT #1, S$
NEXT I%
CLOSE #1
```

```basic
' 読む側
OPEN "kotoba.txt" FOR INPUT AS #1
N% = 0
WHILE NOT EOF(1)
  LINE INPUT #1, L$
  N% = N% + 1
  PRINT N%; ": "; L$
WEND
CLOSE #1
```

**12-2.**

```basic
RANDOMIZE
OPEN "ten.txt" FOR OUTPUT AS #1
FOR I% = 1 TO 30
  PRINT #1, INT(RND * 100) + 1
NEXT I%
CLOSE #1
```

**12-3.** 暫定チャンピオンの「名前つき」版:

```basic
OPEN "seiseki.csv" FOR INPUT AS #1
BEST$ = ""
BESTSCORE% = -1
WHILE NOT EOF(1)
  INPUT #1, NAME$, SCORE%
  IF SCORE% > BESTSCORE% THEN
    BESTSCORE% = SCORE%
    BEST$ = NAME$
  END IF
WEND
CLOSE #1
PRINT "最高点は "; BEST$; " の"; BESTSCORE%; "点"
```

**12-4.** 読み→数え→閉じ→追記、の順がポイント:

```basic
OPEN "log.txt" FOR APPEND AS #1   ' 無ければ空で作る (第 16 章の技)
CLOSE #1
OPEN "log.txt" FOR INPUT AS #1
N% = 0
WHILE NOT EOF(1)
  LINE INPUT #1, L$
  N% = N% + 1
WEND
CLOSE #1
OPEN "log.txt" FOR APPEND AS #1
PRINT #1, "run"
CLOSE #1
PRINT "これで"; N% + 1; "回目の実行です"
```

## 第 13 章

**13-1.**

```basic
C = VAL(COMMAND$(1))
IF COMMAND$(1) = "" THEN
  PRINT "使い方: henkan 摂氏温度"
  END 1
END IF
PRINT C * 1.8 + 32
```

**13-2.**

```basic
DIM L$(999)
N% = 0
WHILE NOT EOF(0) AND N% <= 999
  LINE INPUT L$(N%)
  N% = N% + 1
WEND
FOR I% = N% - 1 TO 0 STEP -1
  PRINT L$(I%)
NEXT I%
```

**13-3.** 比較の直前で両方を大文字にします:

```basic
' (これは断片です — 変更する 1 行)
IF INSTR(UCASE$(L$), UCASE$(PATTERN$)) > 0 THEN
```

**13-4.** WHILE の中に暫定チャンピオンを同居させます
(BESTITEM$ と BEST% を用意し、PRICE% > BEST% なら更新して、
最後に表示)。12-3 とまったく同じ型です。

## 第 14 章

**14-1.**

```basic
RANDOMIZE
CLS
FOR I% = 1 TO 20
  LOCATE INT(RND * 20) + 1, INT(RND * 60) + 1
  COLOR INT(RND * 15) + 1
  PRINT "なまえ";
NEXT I%
COLOR 7
LOCATE 23, 1
```

**14-2.** 「向き」を変数にして、端で符号を反転:

```basic
CLS
X% = 1
DX% = 1
FOR T% = 1 TO 200
  LOCATE 10, X%
  PRINT " ";
  X% = X% + DX%
  IF X% >= 70 OR X% <= 1 THEN DX% = -DX%   ' 跳ね返り!
  LOCATE 10, X%
  PRINT "O";
  SLEEP 0.02
NEXT T%
LOCATE 20, 1
```

**14-3.** Y% 変数と w/s の 2 行を足し、描画を
`LOCATE Y%, X%` にします。消すときは「前回の位置」を覚えて
おいてそこだけ消すと、ちらつきません。

**14-4.**

```basic
' (これは断片です — 計測部分の置き換え)
' COUNT% = 0
' DO
'   K$ = INKEY$
'   COUNT% = COUNT% + 1
' LOOP UNTIL K$ <> ""
' PRINT "スコア:"; COUNT%; "(小さいほど速い)"
```

## 第 15 章

改造 1 (スピードアップ) の例: 変数 `WAIT = 0.08` を導入して
`SLEEP WAIT` に変え、エサを食べたときに
`IF WAIT > 0.02 THEN WAIT = WAIT - 0.005` を足します。

改造 3 (ハイスコア) の例: ゲームオーバーの後に:

```basic
' (これは断片です — snake.bas の末尾に追加)
' OPEN "highscore.txt" FOR APPEND AS #1
' CLOSE #1
' OPEN "highscore.txt" FOR INPUT AS #1
' BEST% = 0
' WHILE NOT EOF(1)
'   INPUT #1, S%
'   IF S% > BEST% THEN BEST% = S%
' WEND
' CLOSE #1
' OPEN "highscore.txt" FOR APPEND AS #2
' PRINT #2, SCORE%
' CLOSE #2
' IF SCORE% > BEST% THEN
'   PRINT "ハイスコア更新!"
' ELSE
'   PRINT "過去最高:"; BEST%
' END IF
```

---

[← 付録 B](appendix-b-errors.md) | [目次](README.md)
