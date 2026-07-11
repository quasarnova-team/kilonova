# Calculated variables

What is this?
-------------

Config-level variables computed from other variables — the same feature and dialect as
C++ quasar's CalculatedVariables module (muParser). Declared in config.xml, evaluated
live: a dependent recomputes inside the write that changed its input.

Declaring
---------

```xml
<FreeVariable name="fv" type="Double" initialValue="5" accessLevel="RW"/>
<CalculatedVariable name="celsius" value="$thisObjectAddress.raw / 100 - 273.15"/>
<CalculatedVariable name="ok" value="a1.celsius" status="a1.raw &gt; 0" isBoolean="false"
                    initialValue="0"/>
<CalculatedVariableGenericFormula name="Doubled" formula="$thisObjectAddress.fv * 2"/>
```

- `value` — the formula. `initialValue` — published Good until the first successful
  evaluation. `status` — a second formula: non-zero means Good, zero means Bad.
  `isBoolean="true"` — publish as Boolean (value ≠ 0).
- FreeVariables are standalone writable variables (`accessLevel`: R / RW / W).

Formula dialect
---------------

Same as muParser on the C++ server:

| Kind | Supported |
|------|-----------|
| Operators | `+ - * / % ^` (power), unary `-`, comparisons `== != < <= > >=`, `&& \|\|`, ternary `c ? a : b` |
| Functions | `sin cos tan asin acos atan sinh cosh tanh asinh acosh atanh log ln log2 log10 exp sqrt sign rint abs min max sum avg pow` (`log` and `ln` are both base e, as in muParser) |
| Constants | `_pi`, `_e` |
| Inputs | dotted addresses (`tc.fv`); escape dashes/slashes in names as `\-` `\/` |

Meta-functions
--------------

- `$thisObjectAddress` (alias `$_`) — address of the object the variable is declared in
- `$parentObjectAddress(numLevelsUp=N)` — N levels above that
- `$applyGenericFormula(Name)` — inline a `CalculatedVariableGenericFormula`

Both address meta-functions escape dashes and slashes automatically.

Status propagation
------------------

Inputs still `BadWaitingForInitialData` propagate `BadWaitingForInitialData`; any other
bad or null input propagates `Bad` — identical to the C++ change-listener semantics.

Security note
-------------

Formulas compile to a whitelisted AST evaluated in-process — never `eval`; anything
outside the table above is rejected at configuration load.
