#ifndef GRIP_SERIAL_BUFFER_H
#define GRIP_SERIAL_BUFFER_H

#include <cmath>
#include <cctype>
#include <cstdint>
#include <cstdlib>
#include <deque>
#include <stdexcept>
#include <string>
#include <vector>

// One complete CSV record is one sample. Host receive times are NOT ADC times.
// Kept independent of BCI2000 so packet fragmentation/order can be tested.
class GripSerialBuffer
{
 public:
  struct Sample
  {
    double voltage; uint16_t receivedMs; uint16_t id;
    uint32_t deviceSequence = 0, deviceUs = 0;
    bool timed = false, valid = true;
    uint64_t receivedUs = 0;
  };

  struct SyncReply { uint32_t id, rx, tx; uint64_t hostRx; };
  bool TakeSync(SyncReply& s) { if (mSync.empty()) return false; s=mSync.front(); mSync.pop_front(); return true; }
  void Reset(size_t capacity, bool synchronize = true, bool requireTiming = false, double periodUs = 10000, uint32_t maxMissing = 0)
  {
    mSamples.clear(); mSync.clear(); mLine.clear(); mMaxMissing = maxMissing; mCapacity = capacity;
    mSynchronizing = synchronize; mId = 0;
    mRequireTiming = requireTiming; mPeriodUs = periodUs; mHavePrevious = false;
  }
  size_t Size() const { return mSamples.size(); }
  Sample Pop()
  {
    if (mSamples.empty()) throw std::runtime_error("Empty grip sample queue");
    auto sample = mSamples.front(); mSamples.pop_front(); return sample;
  }
  void Feed(const char* bytes, size_t length, uint16_t receivedMs, uint64_t receivedUs = 0)
  {
    for (size_t i = 0; i < length; ++i)
    {
      char c = bytes[i];
      // Opening/purging a live stream may cut a record in half. Synchronize
      // once, before acquisition starts; never discard records during a run.
      if (mSynchronizing) { if (c == '\n') mSynchronizing = false; continue; }
      if (c != '\n')
      {
        if (mLine.size() >= 128) throw std::runtime_error("Grip serial line exceeds 128 bytes (missing newline/corrupt frame)");
        mLine += c;
        continue;
      }
      if (mLine.compare(0,2,"S,") == 0)
      {
        std::string line=mLine; if (!line.empty() && line.back()=='\r') line.pop_back();
        std::vector<std::string> fields; size_t start=2, comma;
        while ((comma=line.find(',',start))!=std::string::npos) { fields.push_back(line.substr(start,comma-start)); start=comma+1; }
        fields.push_back(line.substr(start));
        if (fields.size()!=3 || mSync.size()>=16) throw std::runtime_error("Invalid/excessive sync response");
        mSync.push_back({Unsigned(fields[0]),Unsigned(fields[1]),Unsigned(fields[2]),receivedUs});
        mLine.clear(); continue;
      }
      auto value = Parse(mLine);
      if (mSamples.size() >= mCapacity)
        throw std::runtime_error("Grip serial sample queue overflow; acquisition cannot keep up");
      value.receivedMs = receivedMs; value.receivedUs = receivedUs; value.id = mId++;
      mSamples.push_back(value);
      mLine.clear();
    }
  }

 private:
  static double Number(const std::string& field)
  {
    const char* begin = field.c_str();
    char* end = nullptr;
    double value = std::strtod(begin, &end);
    if (end == begin || !std::isfinite(value))
      throw std::runtime_error("Invalid/non-finite grip serial CSV number");
    while (*end && std::isspace(static_cast<unsigned char>(*end))) ++end;
    if (*end) throw std::runtime_error("Unexpected suffix in grip serial CSV number");
    return value;
  }
  static uint32_t Unsigned(const std::string& field)
  {
    if (field.empty()) throw std::runtime_error("Missing grip sequence/timestamp");
    uint64_t value = 0;
    for (char c : field)
    {
      if (c < '0' || c > '9') throw std::runtime_error("Invalid grip sequence/timestamp");
      value = value * 10 + (c - '0');
      if (value > UINT32_MAX) throw std::runtime_error("Grip sequence/timestamp exceeds uint32");
    }
    return static_cast<uint32_t>(value);
  }
  Sample Parse(std::string line)
  {
    if (!line.empty() && line.back() == '\r') line.pop_back();
    std::vector<std::string> fields;
    size_t start = 0, comma;
    while ((comma = line.find(',', start)) != std::string::npos)
    { fields.push_back(line.substr(start, comma - start)); start = comma + 1; }
    fields.push_back(line.substr(start));
    if (fields.size() != 2 && fields.size() != 4)
      throw std::runtime_error("Expected temperature,voltage[,sequence,micros] in grip CSV");
    if (mRequireTiming && fields.size() != 4)
      throw std::runtime_error("Timed grip firmware required: upload the fixed-rate sketch, or explicitly select legacy mode");
    Number(fields[0]);
    Sample sample{Number(fields[1]), 0, 0};
    if (fields.size() == 4)
    {
      sample.timed = true;
      sample.deviceSequence = Unsigned(fields[2]);
      sample.deviceUs = Unsigned(fields[3]);
      if (mHavePrevious)
      {
        uint32_t delta = sample.deviceSequence - mPrevious.deviceSequence;
        if (delta == 0 || delta > mMaxMissing + 1)
          throw std::runtime_error("Grip sequence duplicate/reset/long gap; reconfigure to start a new acquisition identity");
        uint32_t interval = sample.deviceUs - mPrevious.deviceUs;
        if (interval < 0.8 * mPeriodUs * delta || interval > 1.2 * mPeriodUs * delta)
          throw std::runtime_error("Grip device sample interval does not match SamplingRate (or a sampling deadline was missed)");
        if (mSamples.size() + delta > mCapacity) throw std::runtime_error("Grip queue overflow including missing slots");
        for (uint32_t i=1;i<delta;++i)
        {
          Sample missing{}; missing.valid=false; missing.deviceSequence=mPrevious.deviceSequence+i;
          missing.id=mId++; // No fabricated device/receive timestamp or measurement.
          mSamples.push_back(missing);
        }
      }
      mPrevious = sample; mHavePrevious = true;
    }
    else if (mHavePrevious)
      throw std::runtime_error("Grip stream changed from timed to legacy format");
    return sample;
  }
  std::deque<Sample> mSamples;
  std::deque<SyncReply> mSync;
  uint32_t mMaxMissing = 0;
  std::string mLine;
  size_t mCapacity = 4096;
  uint16_t mId = 0;
  bool mSynchronizing = true;
  bool mRequireTiming = false, mHavePrevious = false;
  double mPeriodUs = 10000;
  Sample mPrevious{};
};
#endif
