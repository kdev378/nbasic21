' 画面制御 (ANSI エスケープシーケンス) と INKEY$ のテスト。
' 出力にはエスケープ列がそのまま含まれ、期待出力と比較される。
' INKEY$ は標準入力が端末でないとき「次のバイト」を返す仕様なので、
' パイプで流し込めばテストできる (EOF では "")。
CLS
LOCATE 3, 10
COLOR 14, 1
PRINT "YELLOW ON BLUE";
COLOR 7
LOCATE 5
PRINT "row5"
SLEEP 0.01
K$ = INKEY$
PRINT "key1="; K$; ASC(K$)
WHILE INKEY$ <> ""
WEND
PRINT "drained"
