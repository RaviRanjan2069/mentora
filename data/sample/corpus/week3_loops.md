---
title: Week 3 - Loops and strings
week: 3
---
# While loops

A while loop repeats its body as long as its condition is true. The condition is checked before every iteration, so the body may run zero times.

If nothing inside the body ever makes the condition false, the loop never ends. This is called an infinite loop. Make sure each iteration moves the loop variable towards the stopping condition.

The `break` statement leaves the loop immediately. The `continue` statement skips the rest of the current iteration and jumps to the next condition check.

# For loops and ranges

A for loop runs its body once for each item in a sequence. `for letter in "abc"` runs three times, once for each character.

The `range` function produces a sequence of integers. `range(5)` gives 0, 1, 2, 3 and 4: it starts at 0 and stops before 5. `range(2, 10, 3)` gives 2, 5 and 8, because the third argument is the step.

Use a for loop when you know how many times to repeat, and a while loop when you repeat until a condition changes.

# Strings

A string is an immutable sequence of characters. Immutable means that you cannot change a string in place; operations such as `upper()` return a new string.

You can index a string with square brackets. Indexing starts at 0, so `"python"[0]` is "p", and negative indices count from the end, so `"python"[-1]` is "n".

Slicing extracts part of a string: `"python"[1:4]` gives "yth". The slice includes the start index and excludes the stop index.
