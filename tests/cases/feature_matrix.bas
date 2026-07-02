' 総合ストレステスト
CONST PI# = 3.141592653589793
DIM SHAREDVAL AS INTEGER
DIM A%(10)
DIM G$(2, 2)

SHAREDVAL = 42

FOR I% = 0 TO 10
  A%(I%) = I% * I%
NEXT I%
PRINT "A(7)="; A%(7)

G$(1, 2) = "hello"
PRINT UCASE$(G$(1, 2)); LEN(G$(1, 2))

' 手続き
DECLARE FUNCTION Fib% (N%)
PRINT "FIB(10)="; Fib%(10)
CALL Greet("World", 2)
Greet "again", 1

' 文字列
S$ = "The quick brown fox"
PRINT MID$(S$, 5, 5); "/"; LEFT$(S$, 3); "/"; RIGHT$(S$, 3)
PRINT INSTR(S$, "quick"); INSTR(10, S$, "o")
PRINT STR$(42); "|"; STR$(-3.5); "|"; VAL(" 12.5abc")
PRINT "A" + "B" & 12 & 3.5

' 制御構造
X = 7
IF X > 10 THEN
  PRINT "big"
ELSEIF X > 5 THEN
  PRINT "medium"
ELSE
  PRINT "small"
END IF

SELECT CASE X
  CASE 1, 2, 3
    PRINT "1-3"
  CASE 4 TO 6
    PRINT "4-6"
  CASE IS >= 7
    PRINT ">=7"
  CASE ELSE
    PRINT "other"
END SELECT

N% = 0
WHILE N% < 3
  N% = N% + 1
WEND
PRINT "N="; N%

DO
  N% = N% + 10
LOOP UNTIL N% > 30
PRINT "N="; N%

FOR K = 10 TO 0 STEP -2.5
  PRINT K;
NEXT
PRINT

' EXIT
FOR J% = 1 TO 100
  IF J% = 4 THEN EXIT FOR
NEXT J%
PRINT "J="; J%

' GOSUB/RETURN と GOTO
GOSUB 900
GOSUB SubTwo
GOTO Skip
PRINT "never printed"
Skip:
PRINT "skipped ok"

' DATA/READ/RESTORE
READ P$, Q, R%
PRINT P$; Q; R%
RESTORE MyData
READ P$
PRINT "again "; P$

' 演算子
PRINT 7 \ 2; -7 \ 2; 7 MOD 3; -7 MOD 3
PRINT 2 ^ 10; -2 ^ 2
PRINT (3 > 2) * -10; NOT 0; 6 AND 3; 6 OR 3; 6 XOR 3
PRINT 10 / 4; 1E2
PRINT &HFF; ABS(-5); ABS(-5.5); SGN(-9); INT(-2.5); CINT(2.5); FIX(-2.9)
PRINT SQR(2); CHR$(65); ASC("B")
SWAP X, Y
PRINT "X="; X; "Y="; Y
END

900 PRINT "in gosub 900"
RETURN

SubTwo:
PRINT "in named gosub"
RETURN

MyData:
DATA Hello World, 3.25, 9

SUB Greet (WHO$, TIMES%)
  FOR I% = 1 TO TIMES%
    PRINT "Hello, "; WHO$; "!"
  NEXT I%
END SUB

FUNCTION Fib% (N%)
  IF N% < 2 THEN
    Fib% = N%
  ELSE
    Fib% = Fib%(N% - 1) + Fib%(N% - 2)
  END IF
END FUNCTION
