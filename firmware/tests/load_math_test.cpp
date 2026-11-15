#include <cassert>
#include <cmath>
#include <cstdint>

#include "lib/logic/load_math.hpp"

namespace {

bool near(float actual, float expected, float tolerance) {
    return std::fabs(actual - expected) <= tolerance;
}

} // namespace

int main() {
    using ElectronicLoad::Logic::Math::currentToDacCode;
    using ElectronicLoad::Logic::Math::fastCurrentFromAdcCode;
    using ElectronicLoad::Logic::Math::ntcTemperatureFromAdcCode;

    assert(currentToDacCode(-1.0f) == 0U);
    assert(currentToDacCode(0.0f) == 0U);
    assert(currentToDacCode(5.0f) == 13107U);
    assert(currentToDacCode(25.0f) == UINT16_MAX);

    assert(near(fastCurrentFromAdcCode(310U), 1.0f, 0.01f));

    float temperatureC = 0.0f;
    assert(ntcTemperatureFromAdcCode(372U, temperatureC));
    assert(near(temperatureC, 25.0f, 0.2f));
    assert(!ntcTemperatureFromAdcCode(0U, temperatureC));
    assert(!ntcTemperatureFromAdcCode(4095U, temperatureC));

    return 0;
}
