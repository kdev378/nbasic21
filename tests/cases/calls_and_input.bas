' 引数 6 個 (5 番目以降はスタック渡し)、double 混在
FUNCTION Mix# (A%, B#, C$, D%, E#, F%)
  Mix# = A% + B# * 2 + LEN(C$) + D% + E# + F%
END FUNCTION
PRINT Mix#(1, 2.5, "abc", 10, 0.25, 100)
INPUT "NAME AND AGE"; N$, AGE%
PRINT "HELLO "; N$; AGE% * 2
INPUT V#
PRINT V# / 2
ON = 5   ' ON は予約語ではない
PRINT ON
