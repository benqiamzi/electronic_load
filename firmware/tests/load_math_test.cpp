#include <cassert>
#include <cmath>
#include <cstdint>
#include <limits>

#include "lib/logic/load_math.hpp"

namespace {

bool near(float actual, float expected, float tolerance) {
    return std::fabs(actual - expected) <= tolerance;
}

} // namespace

int main() {
    using ElectronicLoad::Logic::Math::currentToDacCode;
    using ElectronicLoad::Logic::Math::dacCodeToVoltage;
    using ElectronicLoad::Logic::Math::dacVoltageToCode;
    using ElectronicLoad::Logic::Math::fastCurrentFromAdcCode;
    using ElectronicLoad::Logic::Math::fastCurrentToAdcCode;
    using ElectronicLoad::Logic::Math::ntcTemperatureFromAdcCode;
    using ElectronicLoad::Logic::Math::protectionThresholdsValid;
    using ElectronicLoad::Logic::Math::splitCurrent;
    using ElectronicLoad::Logic::LoadChannelMode;

    assert(protectionThresholdsValid({}));
    assert(protectionThresholdsValid({0.01f, 0.01f, 0.01f, 30.0f}));
    assert(!protectionThresholdsValid({30.01f, 2.75f, 50.0f, 80.0f}));
    assert(!protectionThresholdsValid({30.0f, 0.0f, 50.0f, 80.0f}));
    assert(!protectionThresholdsValid({30.0f, 2.75f, 50.01f, 80.0f}));
    assert(!protectionThresholdsValid({30.0f, 2.75f, 50.0f, 81.0f}));
    assert(!protectionThresholdsValid({30.0f, 2.75f, std::numeric_limits<float>::quiet_NaN(), 80.0f}));

    assert(currentToDacCode(-1.0f) == 0U);
    assert(currentToDacCode(0.0f) == 0U);
    assert(currentToDacCode(5.0f) == 26214U);
    assert(currentToDacCode(25.0f) == UINT16_MAX);
    assert(dacVoltageToCode(0.0f) == 0U);
    assert(dacVoltageToCode(2.5f) == UINT16_MAX);
    assert(near(dacCodeToVoltage(dacVoltageToCode(1.25f)), 1.25f, 0.0001f));

    assert(near(fastCurrentFromAdcCode(310U), 1.0f, 0.01f));
    assert(fastCurrentToAdcCode(0.0f) == 0U);
    assert(fastCurrentToAdcCode(-1.0f) == 0U);
    assert(fastCurrentToAdcCode(1.0f) == 310U);
    assert(fastCurrentToAdcCode(2.0f) == 620U);

    const auto channelA = splitCurrent(2.0f, LoadChannelMode::A);
    assert(near(channelA.channelA, 2.0f, 0.0001f));
    assert(near(channelA.channelB, 0.0f, 0.0001f));
    const auto channelB = splitCurrent(2.0f, LoadChannelMode::B);
    assert(near(channelB.channelA, 0.0f, 0.0001f));
    assert(near(channelB.channelB, 2.0f, 0.0001f));
    const auto both = splitCurrent(2.0f, LoadChannelMode::Both);
    assert(near(both.channelA, 1.0f, 0.0001f));
    assert(near(both.channelB, 1.0f, 0.0001f));

    float temperatureC = 0.0f;
    assert(ntcTemperatureFromAdcCode(372U, temperatureC));
    assert(near(temperatureC, 25.0f, 0.2f));
    assert(!ntcTemperatureFromAdcCode(0U, temperatureC));
    assert(!ntcTemperatureFromAdcCode(4095U, temperatureC));

    return 0;
}
