# Sudoku Solving Strategies

A survey of common Sudoku solving techniques, roughly ordered by difficulty.
Each strategy includes a short name, a brief description, and a difficulty
rating on a scale from 1 (trivial) to 10 (extremely hard). Not every
difficulty level needs a representative strategy, and several strategies can
share the same rating.

## 1. Full House — Difficulty 1

If a row, column, or box has exactly one empty cell, its value is forced: it
must be the one digit 1-9 missing from that unit. No candidate tracking is
needed at all.

## 2. Naked Single — Difficulty 2

For an empty cell, list the candidates by removing every digit already
present in its row, column, and box. If only one candidate remains, that
digit must go in the cell.

## 3. Hidden Single — Difficulty 3

Within a single unit (row, column, or box), if a digit can only legally be
placed in one of the remaining empty cells — even though that cell may still
have other candidates — the digit must be placed there.

## 4. Naked Pair — Difficulty 4

If two cells in the same unit both have exactly the same two candidates,
those two digits must occupy those two cells (in some order). The pair can
therefore be eliminated as a candidate from every other cell in that unit.

## 5. Pointing Pair/Triple (Box-Line Reduction) — Difficulty 4

If, within a box, all candidates for a given digit are confined to a single
row or column, that digit cannot appear anywhere else in that row or column
outside the box — the candidate can be eliminated from the rest of the line.

## 6. Hidden Pair — Difficulty 5

If two digits, within a single unit, only appear as candidates in the same
two cells, those two cells must hold those two digits. Any other candidates
in those two cells can be eliminated, even though the cells may list more
than two candidates before the deduction.

## 7. Naked/Hidden Triple — Difficulty 6

The generalization of naked and hidden pairs to three cells and three digits:
if three cells in a unit collectively contain only three candidate digits
between them (naked), or three digits are confined to only three cells in a
unit (hidden), the usual eliminations apply. Not every cell needs to list all
three candidates for the pattern to hold.

## 8. 45 Rule (Sum Elimination) — Difficulty 6

Every row, column, and box sums to 45 (1+2+...+9). When a region can be
split into overlapping groups whose sums are known or constrained (for
example, comparing a box against the rows or columns that intersect it, or
working with given cage sums in Killer Sudoku), subtracting known sums from
45 can reveal the sum of the remaining cells, which in turn restricts or
eliminates candidates. This is primarily useful for sum-constrained variants
but occasionally applies to standard puzzles with enough given digits.

## 9. X-Wing — Difficulty 7

If a digit's candidates in two different rows are each confined to exactly
the same two columns, those two columns must hold that digit in one of
those two rows. The digit can be eliminated as a candidate from the rest of
those two columns (and symmetrically for two columns confined to the same
two rows).

## 10. XY-Wing — Difficulty 8

Take a "pivot" cell with exactly two candidates (X, Y), and two "pincer"
cells, each seeing the pivot and each having two candidates: one shares X
with the pivot, the other shares Y, and both pincers share a third common
candidate Z. Whichever of X or Y the pivot turns out to be, one pincer will
be forced to Z — so Z can be eliminated from any cell seen by both pincers.
