#include "device.hpp"

namespace automotive {

class Engine : public Device {
public:
    void ignite();
};

class TurboEngine : public Engine, protected Config {
};

void Engine::ignite() {
    start();
    Device::stop();
}

void helper() {
    Engine engine;
    engine.ignite();
    Device* dev = &engine;
    dev->stop();
    automotive::globalCounter = 5;
}

} // namespace automotive
