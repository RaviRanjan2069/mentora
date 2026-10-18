---
title: Week 9 - Classes and objects
week: 9
---
# Classes and objects

A class is a blueprint for objects. `class Counter:` defines a class, and `Counter(5)` creates an object (an instance) of it.

`__init__` is the method that runs when an object is created. Its first parameter, `self`, is the new object, and `self.n = start` stores an attribute on that object.

Methods are functions defined inside a class. Calling `c.inc(2)` passes c as self automatically.

Attributes set on self belong to one object. Attributes defined directly in the class body are class attributes shared by every instance; a list defined in the class body is one shared list, so appending through one object shows up in all of them.

A subclass inherits from a parent class: `class Pet(Animal):`. A method defined in the subclass overrides the parent's method with the same name. `super().__init__(...)` calls the parent's version.

`__str__` controls what `print(obj)` shows. Without it, Python prints a default text with the class name and a memory address.
