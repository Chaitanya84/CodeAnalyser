#ifndef DEVICE_HPP
#define DEVICE_HPP

namespace automotive {

class Device {
public:
    Device();
    virtual ~Device();
    void start();
    void stop();
    int state;
protected:
    int errorCount;
};

struct Config {
    int baudRate;
    const char* name;
};

} // namespace automotive

#endif
