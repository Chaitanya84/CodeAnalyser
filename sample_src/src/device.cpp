#include "device.hpp"

namespace automotive {

int globalCounter;
static int internalState;

Device::Device() : state(0), errorCount(0) {
    globalCounter++;
}

Device::~Device() {
    stop();
}

void Device::start() {
    state = 1;
    internalState = state;
}

void Device::stop() {
    state = 0;
}

} // namespace automotive
