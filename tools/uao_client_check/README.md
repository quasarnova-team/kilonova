# UAO C++ client check

What is this?
-------------

The end-to-end proof that a UaoForQuasar-generated C++ client (compiled against the
commercial UASDK) works unmodified against kilonova. Verified 2026-07-11: python device
logic set `slotNumber=7` on the production ATCA design; the C++ client read it back
(exit code 0).

Basic usage mode
----------------

1. Generate client classes in a quasar sandbox (`UaoForQuasar/generateClass.py Board`)
   and copy `generated/` plus UaoForQuasar's `supplementary_src`/`supplementary_include`
   next to `main.cpp`.
1. Serve kilonova on the host: `python serve.py` (edit paths/port inside).
1. Build in a UASDK toolchain image:
   `docker run --rm -v $PWD:/work -v <uasdk>:/opt/uasdk:ro <el9-image> bash /work/build.sh`
1. Run: `docker run ... /work/uaotest opc.tcp://host.docker.internal:<port>`
1. Exit code 0 means the generated client read the value python device logic set.
