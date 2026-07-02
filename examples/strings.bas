' strings.bas — 文字列処理の例: 単語ごとに反転して並べ替え

DIM WORDS$(9)

S$ = "the quick brown fox jumps over the lazy dog"
PRINT "input : "; S$

' --- 空白で分割 ---
N% = 0
START% = 1
FOR I% = 1 TO LEN(S$) + 1
  IF I% > LEN(S$) THEN
    C$ = " "
  ELSE
    C$ = MID$(S$, I%, 1)
  END IF
  IF C$ = " " THEN
    IF I% > START% THEN
      WORDS$(N%) = MID$(S$, START%, I% - START%)
      N% = N% + 1
    END IF
    START% = I% + 1
  END IF
NEXT I%

' --- バブルソート (SWAP と文字列比較) ---
FOR I% = 0 TO N% - 2
  FOR J% = 0 TO N% - 2 - I%
    IF WORDS$(J%) > WORDS$(J% + 1) THEN
      SWAP WORDS$(J%), WORDS$(J% + 1)
    END IF
  NEXT J%
NEXT I%

' --- 出力 ---
PRINT "sorted: ";
FOR I% = 0 TO N% - 1
  PRINT WORDS$(I%);
  IF I% < N% - 1 THEN PRINT " ";
NEXT I%
PRINT
PRINT "upper : "; UCASE$(WORDS$(0)); "..."; UCASE$(WORDS$(N% - 1))
