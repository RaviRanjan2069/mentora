---
title: Week 2 - Conditionals and boolean logic
week: 2
---
# Conditionals

A conditional statement runs a block of code only when a condition is true. Python uses the keywords `if`, `elif` and `else`.

The condition after `if` is evaluated first. If it is false, each `elif` condition is checked in order, and the `else` block runs only when none of the conditions were true. At most one branch of an if/elif/else chain runs.

The body of each branch is marked by indentation. Python uses indentation, not braces, to group statements, so every line in the same block must be indented by the same amount.

# Boolean logic

Comparison operators such as `==`, `!=`, `<`, `>`, `<=` and `>=` produce a bool. Note that `==` tests equality while `=` is assignment.

The logical operators are `and`, `or` and `not`. The expression `a and b` is true only when both a and b are true. The expression `a or b` is true when at least one of them is true.

Python evaluates `and` and `or` with short-circuit evaluation: it stops as soon as the result is known. In `x != 0 and 10 / x > 1`, the division is never evaluated when x is 0.
