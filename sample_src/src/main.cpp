#include "device.hpp"

namespace A {
namespace B {
void process() {
}
} // namespace B
} // namespace A

namespace X::Y {
void nested() {
    A::B::process();
}
} // namespace X::Y

template <typename T>
class Container {
public:
    void add(T value) {
        count++;
    }
    int count;
};

template <typename T>
void processValue(T value) {
}

int main() {
    automotive::Device device;
    device.start();
    device.stop();
    A::B::process();
    X::Y::nested();
    Container<int> container;
    container.add(3);
    processValue(42);
    unresolvedExternalCall();
    return 0;
}
