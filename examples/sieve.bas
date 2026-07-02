' sieve.bas — エラトステネスのふるい (配列と WHILE の例)

CONST LIMIT% = 100
DIM FLAGS%(LIMIT%)

FOR I% = 2 TO LIMIT%
  FLAGS%(I%) = 1                    ' 1 = 素数候補
NEXT I%

P% = 2
WHILE P% * P% <= LIMIT%
  IF FLAGS%(P%) THEN
    ' P% の倍数をふるい落とす
    FOR K% = P% * P% TO LIMIT% STEP P%
      FLAGS%(K%) = 0
    NEXT K%
  END IF
  P% = P% + 1
WEND

COUNT% = 0
FOR I% = 2 TO LIMIT%
  IF FLAGS%(I%) THEN
    PRINT I%;
    COUNT% = COUNT% + 1
  END IF
NEXT I%
PRINT
PRINT "primes:"; COUNT%
