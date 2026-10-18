---
title: Week 5 - Dictionaries and sets
week: 5
---
# Dictionaries

A dictionary maps keys to values, for example `{"apple": 3, "pear": 5}`. Keys are unique; assigning to an existing key replaces its value, and assigning to a new key adds an entry.

`d[key]` returns the value for a key and raises a KeyError if the key is missing. `d.get(key, default)` returns the default instead of raising an error; without a default it returns None.

`d.keys()`, `d.values()` and `d.items()` give the keys, the values, and (key, value) pairs. `for k, v in d.items():` loops over both at once. `key in d` checks the keys, not the values.

Dictionaries keep insertion order. `len(d)` is the number of keys.

A common pattern counts things: `counts[ch] = counts.get(ch, 0) + 1` adds one to the count for ch, starting from 0 the first time.

# Sets

A set is an unordered collection of unique items, for example `{1, 2, 3}`. Duplicates are removed automatically, so `len(set([1, 1, 2]))` is 2. An empty set is written `set()`, because `{}` is an empty dictionary.

`add(x)` inserts an item. `remove(x)` deletes it and raises a KeyError if it is missing; `discard(x)` deletes it without an error.

Set operators: `a | b` is the union (items in either), `a & b` is the intersection (items in both), `a - b` is the difference (items in a but not in b), and `a ^ b` is the symmetric difference (items in exactly one of them).

Membership tests such as `x in s` are fast for sets, which makes sets useful for removing duplicates and checking whether something has been seen.
