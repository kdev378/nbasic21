' guess.bas — 数当てゲーム (INPUT / RND / DO ループの例)
'
' RANDOMIZE を呼ばないので RND の系列は毎回同じ = テストできる。
' 対話的に遊ぶときは次の行のコメントを外すこと:
' RANDOMIZE

SECRET% = INT(RND * 100) + 1
TRIES% = 0

PRINT "I am thinking of a number between 1 and 100."
DO
  INPUT "Your guess"; G%
  TRIES% = TRIES% + 1
  SELECT CASE G%
    CASE IS < SECRET%
      PRINT "Too low!"
    CASE IS > SECRET%
      PRINT "Too high!"
    CASE ELSE
      PRINT "You got it in"; TRIES%; "tries!"
      EXIT DO
  END SELECT
LOOP
