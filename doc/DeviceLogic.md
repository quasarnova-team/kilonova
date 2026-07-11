# Device logic

What is this?
-------------

In C++ quasar you implement `D<Class>` methods. In kilonova there is no generated
skeleton: you register plain async Python functions by dotted address. Everything below is
the entire user API.

Objects and cache variables
---------------------------

```python
server = Server("Design.xml", config_path="config.xml")
await server.start()                       # or: async with server:

sca1 = server.objects["sca1"]              # dotted addresses, as in the address space
await sca1.setOnline(42)                   # generated setter (quasar naming: setMyVar)
await sca1.set_cv("online", 42)            # same thing, explicit
await sca1.set_cv("online", 0, status=ua.StatusCodes.Bad)   # value + status
value = await sca1.get_cv("online")        # None while status is bad
```

`set_cv` raises on refused writes (type mismatch, null into `nullForbidden`) and on
integer range violations — no silent drops.

Methods
-------

```python
@server.method("sca1.scale")
async def scale(obj, factor):              # obj is the owning QuasarObject
    return factor * 2.0                    # mapped to the Design's return values
```

- Argument counts are validated (`BadArgumentsMissing` / `BadTooManyArguments`).
- Unregistered methods answer `BadNotImplemented`.
- Multiple return values: return a tuple. A single array return value is never unpacked.

Source variables
----------------

```python
@server.read("sca1.adc")                   # addressSpaceRead: runs INSIDE the client read
async def read_adc(obj):
    return await hw.read()                 # value
    # or: return value, ua.StatusCodes.Good
    # or: return ua.DataValue(...)

@server.write("sca1.dac")                  # addressSpaceWrite
async def write_dac(obj, value):
    if not 0 <= value <= 10:
        raise ua.UaStatusCodeError(ua.StatusCodes.BadOutOfRange)   # client gets this
    await hw.write(value)
```

Until the first interaction a source variable serves `BadWaitingForInitialData`.

Delegated cache variables
-------------------------

`addressSpaceWrite="delegated"` cache variables use the same `@server.write` decorator: the
handler runs before the value is stored, its exception status is returned to the client,
and an unregistered delegated write answers `BadNotImplemented`. Server-side `set_cv` never
triggers the handler (it *is* device logic).

Calculated variables and free variables
---------------------------------------

Config-level, exactly as in C++ quasar:

```xml
<FreeVariable name="fv" type="Double" initialValue="5"/>
<CalculatedVariable name="sum" value="$thisObjectAddress.fv + 7"/>
<CalculatedVariableGenericFormula name="Doubled" formula="$thisObjectAddress.fv * 2"/>
```

Formulas are compiled to a whitelisted AST (numbers, addresses, `+ - * / % ^`) — never
`eval`. Dependents recompute inside the write that changed an input; null/bad inputs
propagate `BadWaitingForInitialData`.

Logging
-------

Standard Python `logging`, loggers `kilonova.*`. The StandardMetaData log-level nodes
(`TRC/DBG/INF/WRN/ERR`) set those loggers at runtime, like LogIt on a C++ server; a config
`<StandardMetaData>` section sets initial levels.
