#include <iostream>
#include <uaplatformlayer.h>
#include <ClientSessionFactory.h>
#include <Board.h>

int main(int argc, char** argv)
{
    UaPlatformLayer::init();
    UaClientSdk::UaSession* session = ClientSessionFactory::connect(UaString(argv[1]));
    if (!session) { std::cerr << "connection failed" << std::endl; return 2; }
    UaoClient::Board board(session, UaNodeId(UaString("asmemf-dro-02.Slot 1"), 2));
    OpcUa_Int32 slot = board.readSlotNumber();
    std::cout << "UAO client read slotNumber=" << slot << std::endl;
    return slot == 7 ? 0 : 3;
}
