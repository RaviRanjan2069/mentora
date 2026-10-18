---
title: Week 6 - Functions and scope
week: 6
---
# Functions

A function is defined with `def`, a name, parameters in parentheses and an indented body. Calling the function runs the body with the arguments you pass.

`return value` ends the function and sends the value back to the caller. A function that reaches the end of its body without a return statement returns None, so `print(f(3))` prints None if f never returns anything.

A parameter can have a default value: in `def f(x, y=2)`, calling `f(5)` uses y = 2, while `f(5, 3)` uses y = 3.

Keyword arguments are matched by name, not position: `f(c=1, a=2, b=3)` sets a = 2, b = 3 and c = 1 whatever order you write them in.

Functions can call other functions. Breaking a task into small functions, each with one job, makes code easier to test and reuse.

# Scope and parameters

A variable assigned inside a function is local to that function. Assigning `x = 10` inside a function does not change a global variable called x.

To change a global variable from inside a function, declare it with `global x` first. Use this sparingly; returning a value is usually clearer.

If a function assigns to a name anywhere in its body, that name is local for the whole function. Reading it before the assignment raises an UnboundLocalError.

Parameters receive references to the arguments. Rebinding a parameter (`n = n + 1`) does not affect the caller's variable, but mutating a list argument (`lst.append(4)`) changes the caller's list, because both names refer to the same list.

An inner function can read variables of the function that encloses it. This is called a closure.
