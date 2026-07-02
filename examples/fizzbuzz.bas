' fizzbuzz.bas — 現代スタイルの FizzBuzz
' SELECT CASE と文字列連結演算子 & を使う

FOR N% = 1 TO 20
  SELECT CASE N% MOD 15
    CASE 0
      PRINT "FizzBuzz"
    CASE 3, 6, 9, 12
      PRINT "Fizz"
    CASE 5, 10
      PRINT "Buzz"
    CASE ELSE
      PRINT "" & N%
  END SELECT
NEXT N%
