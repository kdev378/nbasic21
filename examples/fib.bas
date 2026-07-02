' fib.bas — 再帰 FUNCTION の例
' FUNCTION は前方参照できるので、定義より前に呼び出せる

FOR I% = 0 TO 15
  PRINT Fib%(I%);
NEXT I%
PRINT

FUNCTION Fib% (N% AS INTEGER)
  IF N% < 2 THEN
    Fib% = N%                       ' 古典式: 関数名への代入
  ELSE
    RETURN Fib%(N% - 1) + Fib%(N% - 2)   ' 現代式: RETURN 式
  END IF
END FUNCTION
