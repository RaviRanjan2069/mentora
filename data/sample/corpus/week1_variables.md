---
title: Week 1 - Variables, types and expressions
week: 1
---
# Variables and assignment

A variable is a name that refers to a value. In Python you create a variable by assignment, for example `count = 3`. The equals sign means "store the value on the right under the name on the left"; it does not mean mathematical equality.

You can assign a new value to an existing variable at any time. After `count = 3` followed by `count = count + 1`, the variable count refers to 4.

Variable names may contain letters, digits and underscores, but they cannot start with a digit. Names are case sensitive, so `Total` and `total` are different variables.

# Basic data types

Every value in Python has a type. The four basic types in this course are int for whole numbers, float for numbers with a decimal point, str for text, and bool for the truth values True and False.

You can check the type of a value with the built-in function `type`. For example, `type(3.5)` returns float.

Converting between types is called casting. `int("42")` turns the string "42" into the integer 42, and `str(7)` turns the integer 7 into the string "7".

# Expressions and operators

An expression combines values and operators to produce a new value. The arithmetic operators are `+`, `-`, `*`, `/`, `//` and `%`.

The `/` operator always produces a float, so `7 / 2` gives 3.5. The `//` operator performs floor division, so `7 // 2` gives 3. The `%` operator gives the remainder, so `7 % 2` gives 1.

Operator precedence decides the order of evaluation: multiplication and division are evaluated before addition and subtraction. Use parentheses to make the order explicit.

# Input and output

The `print` function writes values to the screen. The `input` function reads a line typed by the user and always returns a string, so you must cast it with `int` or `float` before doing arithmetic.
