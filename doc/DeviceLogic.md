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

Blocking device logic
---------------------

Two kinds of handlers, one rule:

- **`async def`** — runs on the server's event loop. Never block in it: no vendor SDK
  calls, no `time.sleep`, no synchronous sockets. One blocking call stalls every session.
- **plain `def`** — kilonova runs it in its thread pool (`Server(offload_workers=8)`).
  Blocking calls are safe here: a slow driver delays this one transaction, nothing else.

```python
@server.read("sca1.adc")
def read_adc(obj):                         # plain def: offloaded, may block
    return caen.read_voltage(slot=3)       # blocking vendor call — safe

@server.method("sca1.reset")
async def reset(obj):                      # mixed: offload only the blocking part
    await server.offload(caen.reset)
    await obj.setOnline(0)                 # async API — on the loop, as it must be
```

A plain-`def` handler runs off the loop, so it must not call async APIs (`set_cv`,
setters) directly — return the value instead, or use the mixed style above. Independent
source variables in one read transaction refresh concurrently; the Design's mutex
domains still serialize exactly what they declare. Under domain `no`, two overlapping
reads of the *same* variable may commit in either order (last writer wins) — declare
`of_this_variable` if that matters, exactly as in C++.

The server watches its own loop: if something blocks it longer than
`Server(watchdog=0.25)` seconds, it logs a warning naming the device logic that was
running (`watchdog=None` disables this).

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

Synchronization domains
-----------------------

The Design's mutex declarations are honoured with asyncio locks: source-variable
`addressSpaceRead/WriteUseMutex` and method `addressSpaceCallUseMutex` serialize device
access per declared domain (`of_this_operation`, `of_this_variable` / `of_this_method`,
`of_containing_object`, `of_parent_of_containing_object`); domain `no` runs concurrently,
exactly as on the C++ server. `handpicked` means the framework applies no lock — you hold your own inside the
handler, exactly as on the C++ server where the developer supplies the mutex
(in a plain-`def` handler that is a `threading.Lock`, not an `asyncio.Lock`).

Method `executionSynchronicity` is parsed and both values behave like C++'s
*asynchronous* mode by construction: handlers are awaited coroutines or pool-offloaded
functions, so a slow method never blocks the server loop, and the client's Call
completes when the handler finishes (C++'s `finishCall`).

Server configuration
--------------------

`kilonova run --design D --config C [--opcua_backend_config ServerConfig.xml]` consumes the
same three files as a C++ quasar server, unmodified. From ServerConfig.xml kilonova honours
the endpoint URL (`[NodeName]` = all interfaces), security policy/mode pairs (None,
Basic256Sha256 Sign / SignAndEncrypt with server certificate + key) and identity tokens
(anonymous / user-password); unsupported knobs (PKI trust lists, session limits, tracing)
are logged as warnings, never silently dropped. The configuration schema is as strict as
the C++ Configurator: required scalars, defaults, array size facets, key uniqueness.
