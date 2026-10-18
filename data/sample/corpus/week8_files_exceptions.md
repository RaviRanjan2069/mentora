---
title: Week 8 - Files and exceptions
week: 8
---
# File handling

`open(name, mode)` opens a file. Mode `'r'` reads and is the default, `'w'` writes and empties the file first, `'a'` appends to the end, and `'x'` creates a new file and fails if it already exists. Opening a missing file for reading raises a FileNotFoundError.

Use a with block: `with open("data.txt") as f:`. The file is closed automatically when the block ends, even if an error happens inside it.

`f.read()` returns the whole file as one string. `f.readlines()` returns a list of strings, one per line, each still ending with a newline character. Looping with `for line in f:` reads one line at a time.

`line.strip()` removes the newline and surrounding spaces. `text.split()` splits a string into words.

`f.write(text)` writes a string and returns the number of characters written. It does not add a newline for you.

# Exceptions

An exception is an error raised while a program runs. Common ones: ZeroDivisionError (dividing by zero), IndexError (index out of range), KeyError (missing dictionary key), ValueError (right type, wrong value, such as `int("abc")`), TypeError (wrong type, such as `"a" + 1`), NameError (an undefined name) and AttributeError (a missing method or attribute).

A try block runs code that might fail. If an exception happens, Python jumps to the first matching except block and skips the rest of the try block.

An else block runs only if the try block raised no exception. A finally block always runs, whether or not there was an exception.

Put specific except blocks before general ones such as `except Exception`, because Python uses the first block that matches.

`raise ValueError("message")` signals an error yourself. `except ValueError as e:` gives you the exception object, and `print(e)` shows its message.
