#pragma once
#include <Arduino.h>

// Edit both lists here. Index 0..7 means bit 0..7 (weights 1,2,4,8,16,32,64,128).
// Wire outputPins[i] to feedbackPins[i]. Analog pin symbols A0..A5 are allowed.
constexpr uint8_t outputPins[]   = {2, 3, 4, 5, 6, 7, 8, 9};
constexpr uint8_t feedbackPins[] = {A5, A4, A3, A2, A1, A0, 12, 13};

static_assert(sizeof(outputPins)/sizeof(outputPins[0]) == 8, "outputPins requires exactly 8 pins");
static_assert(sizeof(feedbackPins)/sizeof(feedbackPins[0]) == 8, "feedbackPins requires exactly 8 pins");
