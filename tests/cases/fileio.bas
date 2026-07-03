' ファイル入出力の総合テスト
' OPEN (OUTPUT/APPEND/INPUT) / PRINT # / INPUT # / LINE INPUT # /
' EOF / CLOSE と、キーボードの LINE INPUT + EOF(0) を検査する。
' (テストランナーは一時ディレクトリを作業ディレクトリにして実行する)

OPEN "fileio_demo.tmp" FOR OUTPUT AS #1
PRINT #1, "alpha,", 42; 3.5
PRINT #1, "beta line"
PRINT #1, "quoted:"; """hi, there"""
CLOSE #1

OPEN "fileio_demo.tmp" FOR APPEND AS #2
PRINT #2, "gamma appended"
CLOSE                       ' 引数なし = 全部閉じる

OPEN "fileio_demo.tmp" FOR INPUT AS #1
INPUT #1, A$, B%, C#        ' 文字列はカンマ区切り、数値は空白でも区切る
PRINT "read: "; A$; "/"; B%; C#
LINE INPUT #1, L$
PRINT "line: "; L$
INPUT #1, Q1$, Q2$          ' 引用符付き項目はカンマを含められる
PRINT "q: "; Q1$; "/"; Q2$
N% = 0
WHILE NOT EOF(1)
  LINE INPUT #1, L$
  N% = N% + 1
WEND
PRINT "rest:"; N%; "last: "; L$
CLOSE #1

' --- 標準入力を EOF まで読む (LINE INPUT と EOF(0)) ---
TOTAL% = 0
LINES% = 0
WHILE NOT EOF(0)
  LINE INPUT S$
  TOTAL% = TOTAL% + LEN(S$)
  LINES% = LINES% + 1
WEND
PRINT "stdin:"; LINES%; "lines,"; TOTAL%; "bytes"
