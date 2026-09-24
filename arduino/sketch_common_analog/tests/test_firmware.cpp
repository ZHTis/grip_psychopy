#include <cstdint>
#include <string>
#include <sstream>
#include <iomanip>
#include <iostream>
#include "GripSerialBuffer.h"
uint32_t fakeUs = 0;
uint32_t micros() { return fakeUs; }
const int A0 = 0;
int analogRead(int) { fakeUs += 104; return 512; }
struct MockSerial
{
  std::string bytes, input;
  int available() { return static_cast<int>(input.size()); }
  int read() { int c=input.front(); input.erase(0,1); return c; }
  int capacity = 64;
  void begin(int) {}
  int availableForWrite() { return capacity; }
  void print(const char* value) { bytes += value; }
  void print(char value) { bytes += value; }
  void print(uint32_t value) { bytes += std::to_string(value); }
  void print(float value, int precision)
  { std::ostringstream s; s << std::fixed << std::setprecision(precision) << value; bytes += s.str(); }
  void println(uint32_t value) { print(value); bytes += "\r\n"; }
} Serial;
#include "../sketch_common_analog.ino"
void Check(bool value) { if (!value) throw std::runtime_error("Firmware scheduling test failed"); }
int main()
{
  setup();
  for (unsigned n=0;n<1024;++n) {
    fakeUs=((nextSampleUs+3)/4)*4; loop();
  }
  GripSerialBuffer q;q.Reset(2048,false,true,1000000.0/256);
  q.Feed(Serial.bytes.data(),Serial.bytes.size(),0);
  Check(q.Size()==1024);
  for (unsigned n=0;n<1024;++n) {
    auto s=q.Pop(); uint32_t ideal=((n+1)*1000000UL)/256;
    Check(s.deviceSequence==n && s.deviceUs>=ideal && s.deviceUs-ideal<=3);
    if (n==1023) Check(s.deviceUs==4000000);
  }
  Serial.bytes.clear();Serial.capacity=0;fakeUs=nextSampleUs;loop();Check(Serial.bytes.empty());
  Serial.capacity=64;fakeUs=nextSampleUs;loop();
  q.Reset(16,false,true,3906.25);q.Feed(Serial.bytes.data(),Serial.bytes.size(),0);
  Check(q.Pop().deviceSequence==1025);
  Serial.bytes.clear();fakeUs=nextSampleUs+8000;loop();
  q.Reset(16,false,true,3906.25);q.Feed(Serial.bytes.data(),Serial.bytes.size(),0);
  Check(q.Size()==1 && q.Pop().deviceSequence==1028);
  Serial.bytes.clear();nextSampleUs=UINT32_MAX-5000;sampleSequence=UINT32_MAX;sampleFraction=0;
  fakeUs=nextSampleUs;loop();fakeUs=nextSampleUs;loop();
  q.Reset(16,false,true,3906.25);q.Feed(Serial.bytes.data(),Serial.bytes.size(),0);
  Check(q.Size()==2 && q.Pop().deviceSequence==UINT32_MAX && q.Pop().deviceSequence==0);
  Serial.bytes.clear();Serial.input="Q,123\n";fakeUs=nextSampleUs-500;loop();
  Check(Serial.bytes.empty() && !Serial.input.empty());
  fakeUs=nextSampleUs-3000;loop();
  q.Reset(16,false,true,3906.25);q.Feed(Serial.bytes.data(),Serial.bytes.size(),0,99);
  GripSerialBuffer::SyncReply reply;Check(q.TakeSync(reply) && reply.id==123 && reply.rx==fakeUs && reply.tx==fakeUs);
  std::cout << "PASS: exact fractional 256 Hz schedule, 4-us clock quantization, TX loss, missed deadlines, wrap, guarded sync\n";
}
