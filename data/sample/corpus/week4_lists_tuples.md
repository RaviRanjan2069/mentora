---
title: Week 4 - Lists and tuples
week: 4
---
# Lists

A list is an ordered, mutable sequence written with square brackets, for example `[3, 1, 2]`. Mutable means you can change a list in place after creating it.

`append(x)` adds one item to the end of a list. `insert(i, x)` puts x at index i and shifts the later items right. `pop()` removes and returns the last item, and `pop(0)` removes the first one. `remove(x)` deletes the first item equal to x.

Indexing and slicing work as for strings: `lst[0]` is the first item, `lst[-1]` is the last, and `lst[1:3]` gives the items at index 1 and 2. A slice always creates a new list.

Assignment does not copy a list. After `b = a`, both names refer to the same list, so `b.append(5)` also changes `a`. Use `b = a[:]` or `b = list(a)` to make a separate copy.

`lst.sort()` sorts the list in place and returns None. `sorted(lst)` returns a new sorted list and leaves the original unchanged.

A list comprehension builds a list in one expression: `[v * 2 for v in lst if v % 2 == 0]` doubles only the even values.

`len(lst)`, `sum(lst)`, `max(lst)` and `min(lst)` give the length, total, largest and smallest item. `lst.index(x)` gives the position of the first x.

# Tuples

A tuple is an ordered, immutable sequence written with parentheses, for example `(3, 1, 2)`. Immutable means that `t[0] = 5` raises a TypeError.

A one-item tuple needs a trailing comma: `(5,)` is a tuple, but `(5)` is just the integer 5 in parentheses.

Tuples support indexing, slicing, `len`, `count` and `index`. `t + (4,)` and `t * 2` create new tuples; the original is unchanged.

Unpacking assigns the items to names: `a, b = (1, 2)`. A starred name collects the rest as a list: `first, *rest = (1, 2, 3)` gives `first = 1` and `rest = [2, 3]`.
