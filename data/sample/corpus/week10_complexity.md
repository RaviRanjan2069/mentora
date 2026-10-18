---
title: Week 10 - Basic algorithmic complexity
week: 10
---
# Basic algorithmic complexity

Time complexity describes how the number of steps grows with the input size n. Big-O notation keeps only the fastest-growing term and drops constants.

O(1) is constant time: the work does not depend on n, for example a loop that always runs 100 times or a single formula.

O(n) is linear: one loop over the input. Two loops one after the other are still O(n), because n + n is 2n and constants are dropped.

O(n^2) is quadratic: a loop inside a loop, both over n. A nested loop where the inner loop runs `range(i)` is still O(n^2), since it does about n * n / 2 steps.

O(log n) is logarithmic: the problem is halved each step, as in `while i > 1: i //= 2`. O(n log n) is a loop over n with a halving loop inside it.

O(n^3) comes from three nested loops over n. An inner loop with a fixed number of steps, such as `range(10)`, only multiplies by a constant, so it does not change the class.

To count steps exactly for a small n, trace the loops by hand: for nested loops over range(n), the inner body runs n * n times.
