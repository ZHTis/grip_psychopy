// Upload to the SECOND Arduino. Grip Arduino firmware is unchanged.
// Protocol: HELLO -> READY,1; M,event_id,code,pulse_ms -> ACK,... then DONE,...
// Pin order is defined in PinMap.h, independently for outputs and inputs.
// M,id,code,width = output + readback. O,id,code,width = output only (no feedback reads).
// Replies after pulse completion: B8,readback or OUT,- (no measured feedback).
#include <Arduino.h>
#include <stdlib.h>
#include <string.h>

#include "PinMap.h"

bool pinConfigValid = false;

bool validatePins() {
  for (uint8_t i = 0; i < 8; ++i) {
    if (outputPins[i] < 2 || feedbackPins[i] < 2 ||
        outputPins[i] >= NUM_DIGITAL_PINS || feedbackPins[i] >= NUM_DIGITAL_PINS) return false;
    if (digitalPinToPort(outputPins[i]) == NOT_A_PIN ||
        digitalPinToPort(feedbackPins[i]) == NOT_A_PIN) return false;
    for (uint8_t j = 0; j < 8; ++j) {
      if (outputPins[i] == feedbackPins[j]) return false;
      if (i != j && (outputPins[i] == outputPins[j] || feedbackPins[i] == feedbackPins[j])) return false;
    }
  }
  return true;
}

void reportReady() {
  if (!pinConfigValid) { Serial.println("ERR,PIN_CONFIG"); return; }
  Serial.print("PINS");
  for (uint8_t i = 0; i < 8; ++i) { Serial.print(','); Serial.print(outputPins[i]); }
  for (uint8_t i = 0; i < 8; ++i) { Serial.print(','); Serial.print(feedbackPins[i]); }
  Serial.println();
  Serial.println("READY,1");
}

uint8_t readFeedback() {
  uint8_t code = 0;
  for (uint8_t bit = 0; bit < 8; ++bit)
    if (digitalRead(feedbackPins[bit]) == HIGH) code |= (1 << bit);
  return code;
}

char lineBuffer[64];
uint8_t used = 0;
bool overflowed = false;

void outputCode(uint8_t code) {
#if defined(__AVR_ATmega328P__)
  bool standardOrder = true;
  for (uint8_t bit = 0; bit < 8; ++bit)
    if (outputPins[bit] != bit + 2) standardOrder = false;
  if (standardOrder) {
    uint8_t saved = SREG;
    noInterrupts();
    PORTD = (PORTD & 0x03) | ((code & 0x3f) << 2);
    PORTB = (PORTB & 0xfc) | (code >> 6);
    SREG = saved;
    return;
  }
#endif
  for (uint8_t bit = 0; bit < 8; ++bit)
    digitalWrite(outputPins[bit], (code & (1 << bit)) ? HIGH : LOW);
}

bool number(char* text, unsigned long& value) {
  if (!text || !*text) return false;
  for (char* p = text; *p; ++p) if (*p < '0' || *p > '9') return false;
  char* end;
  value = strtoul(text, &end, 10);
  return *end == 0;
}

void reply(const char* type, unsigned long id, unsigned long code, unsigned long stamp, uint8_t readback, bool loopback) {
  Serial.print(type); Serial.print(','); Serial.print(id); Serial.print(',');
  Serial.print(code); Serial.print(','); Serial.print(stamp);
  if (loopback) { Serial.print(",B8,"); Serial.println(readback); }
  else Serial.println(",OUT,-");
}

void processLine() {
  if (!strcmp(lineBuffer, "HELLO")) { reportReady(); return; }
  if (!pinConfigValid) { Serial.println("ERR,PIN_CONFIG"); return; }
  char* command = strtok(lineBuffer, ",");
  unsigned long id, code, width;
  if (!command || (strcmp(command, "M") && strcmp(command, "O")) || !number(strtok(NULL, ","), id) ||
      !number(strtok(NULL, ","), code) || !number(strtok(NULL, ","), width) ||
      strtok(NULL, ",") || code > 255 || width < 1 || width > 1000) {
    outputCode(0); Serial.println("ERR,FORMAT"); return;
  }
  const bool loopback = !strcmp(command, "M");
  outputCode((uint8_t)code);
  unsigned long onset = micros();
  uint8_t feedbackDuring = loopback ? readFeedback() : 0;
  // Measure pulse duration from output onset; UART replies wait until after reset.
  while ((unsigned long)(micros() - onset) < width * 1000UL) {}
  outputCode(0);
  unsigned long offset = micros();
  uint8_t feedbackAfter = loopback ? readFeedback() : 0;
  reply("ACK", id, code, onset, feedbackDuring, loopback);
  reply("DONE", id, code, offset, feedbackAfter, loopback);
  delay(2); // Explicit zero gap allows repeated identical codes to retrigger.
}

void setup() {
  Serial.begin(115200);
  pinConfigValid = validatePins();
  if (!pinConfigValid) { reportReady(); return; }
  for (uint8_t bit = 0; bit < 8; ++bit) {
    pinMode(feedbackPins[bit], INPUT);
    digitalWrite(feedbackPins[bit], LOW); // Disable pull-ups
  }
  for (uint8_t bit = 0; bit < 8; ++bit) { digitalWrite(outputPins[bit], LOW); pinMode(outputPins[bit], OUTPUT); }
  outputCode(0);
  reportReady();
}

void loop() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      lineBuffer[used] = 0;
      if (overflowed) { if (pinConfigValid) outputCode(0); Serial.println("ERR,LENGTH"); }
      else if (used) processLine();
      used = 0; overflowed = false;
    } else if (used < sizeof(lineBuffer)-1 && !overflowed) lineBuffer[used++] = c;
    else overflowed = true;
  }
}
