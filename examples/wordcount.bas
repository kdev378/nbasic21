' wordcount.bas — wc 風の CLI ツール
'
' 標準入力を EOF まで読み、行数・単語数・バイト数を数える:
'     ./wordcount < 文書.txt
'
' LINE INPUT (1 行を丸ごと読む) と EOF(0) (標準入力の終端検査) の
' 組み合わせが「パイプで使える CLI ツール」の基本形。

LINES% = 0
WORDS% = 0
BYTES% = 0

WHILE NOT EOF(0)
  LINE INPUT L$
  LINES% = LINES% + 1
  BYTES% = BYTES% + LEN(L$) + 1     ' +1 は改行の分

  ' 単語数: 空白でない文字の連なりを数える
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

PRINT LINES%; WORDS%; BYTES%
