set -e
cd /work
UASDK=/opt/uasdk
rm -rf shim && mkdir shim
for h in supplementary_include/*.h; do
  base=$(basename $h)
  case $base in UaoClient*) continue;; esac
  printf '#include <%s>
' "$base" > supplementary_include/UaoClient$base
done
ln -s $UASDK/include/uaclientcpp shim/uaclient
ln -s $UASDK/include/uabasecpp shim/uabase
ln -s $UASDK/include/uapkicpp shim/uapki
ln -s $UASDK/include/uastack shim/uastack
ln -s $UASDK/include/xmlparsercpp shim/xmlparser
g++ -std=c++17 -o uaotest main.cpp generated/Board.cpp supplementary_src/ClientSessionFactory.cpp supplementary_src/UaoExceptions.cpp \
  /logit/src/LogIt.cpp /logit/src/LogItInstance.cpp /logit/src/LogLevels.cpp \
  /logit/src/ComponentAttributes.cpp /logit/src/LogRecord.cpp /logit/src/StdOutLog.cpp /logit/src/LogSinks.cpp \
  -DLOGIT_BACKEND_STDOUTLOG -DBACKEND_UATOOLKIT \
  -I generated -I supplementary_include -I /logit/include -I shim \
  -I $UASDK/include/uastack -I $UASDK/include/uabasecpp -I $UASDK/include/uaclientcpp -I $UASDK/include/uapkicpp \
  -L $UASDK/lib -Wl,--start-group -luaclientcpp -luabasecpp -luapkicpp -luastack -lxmlparsercpp -Wl,--end-group -lxml2 -lssl -lcrypto -lpthread
echo BUILD-OK
