---
title: Week 7 - Recursion
week: 7
---
# Recursion

A recursive function is a function that calls itself. Every recursive function needs a base case that returns without a recursive call, and a recursive case that moves closer to the base case.

The factorial `n! = n * (n - 1)!` with `0! = 1! = 1` is a classic example: `f(4)` is `4 * f(3)`, which is `4 * 3 * f(2)`, and so on, giving 24.

To trace a recursive function, write down each call with its argument, follow the calls down to the base case, then combine the returned values on the way back up.

Counting calls: a function like `down(n)` that calls `down(n - 1)` until n is 0 is called n + 1 times in total, because the call with n = 0 also counts.

Without a reachable base case, the calls never stop and Python raises a RecursionError when the call stack gets too deep.

Some recursive functions call themselves more than once, like `fib(n) = fib(n - 1) + fib(n - 2)`. They are short to write but can repeat a lot of work, which makes them slow for large n.
