// Fixed-rate grip acquisition: 256 Hz, A0, classic 5 V / 10-bit Arduino ADC.
// CSV: temperature_placeholder,voltage,sequence,device_sample_time_us
// Timestamp is taken immediately BEFORE analogRead(), not at host reception.
// Both uint32 counters wrap naturally. The host checks sequence and timing.
// 1e6/256 = 3906.25 us. Carry the fraction instead of rounding the rate.
const uint32_t SAMPLE_RATE_HZ = 256;
const uint32_t SERIAL_BAUD = 250000;
uint16_t sampleFraction = 0;
uint32_t nextSampleUs = 0;
uint32_t sampleSequence = 0;

void AdvanceSampleDeadline()
{
  nextSampleUs += 1000000UL / SAMPLE_RATE_HZ;
  sampleFraction += 1000000UL % SAMPLE_RATE_HZ;
  if (sampleFraction >= SAMPLE_RATE_HZ) { ++nextSampleUs; sampleFraction -= SAMPLE_RATE_HZ; }
}

void setup()
{
  Serial.begin(SERIAL_BAUD);
  nextSampleUs = micros();
  AdvanceSampleDeadline();
}

void SampleGrip()
{
  uint32_t now = micros();
  if (int32_t(now - nextSampleUs) < 0)
    return;

  // Do not take bursts of catch-up samples and call them regularly spaced.
  // Missed deadlines or TX-buffer exhaustion produce a visible sequence gap.
  uint32_t sequence = sampleSequence++;
  AdvanceSampleDeadline();
  while (int32_t(now-nextSampleUs) >= 0) {
    sequence=sampleSequence++;
    AdvanceSampleDeadline();
  }
  // A complete line is <= 35 bytes for this ADC. Reserve extra room so
  // Serial.print cannot block the sampling loop on classic AVR HardwareSerial.
  if (Serial.availableForWrite() < 48)
    return;

  uint32_t sampledUs = micros();
  int raw = analogRead(A0);
  float voltage = raw * (5.0f / 1023.0f);
  Serial.print("0.00,");
  Serial.print(voltage, 3);
  Serial.print(',');
  Serial.print(sequence);
  Serial.print(',');
  Serial.println(sampledUs);
}

char syncRequest[16]; uint8_t syncLength=0; bool syncDropping=false, syncReady=false;
uint32_t syncToken=0, syncRx=0;
void ServiceSync()
{
  // Keep decimal sync formatting away from the next sampling deadline.
  if (int32_t(nextSampleUs-micros()) < 1500) return;
  // Bound command work; never wait for bytes or TX capacity.
  for (uint8_t n=0;n<16 && Serial.available();++n)
  {
    char c=static_cast<char>(Serial.read());
    if (c=='\n')
    {
      uint32_t received=micros();
      if (!syncDropping && syncLength>2 && syncRequest[0]=='Q' && syncRequest[1]==',')
      {
        uint32_t token=0; bool good=true;
        for (uint8_t i=2;i<syncLength;++i) {
          char d=syncRequest[i];
          if (d<'0' || d>'9' || token>(UINT32_MAX-uint32_t(d-'0'))/10) { good=false; break; }
          token=token*10+uint32_t(d-'0');
        }
        if (good && !syncReady) { syncToken=token;syncRx=received;syncReady=true; }
      }
      syncLength=0; syncDropping=false;
    }
    else if (!syncDropping) {
      if (syncLength<sizeof(syncRequest)) syncRequest[syncLength++]=c;
      else syncDropping=true;
    }
  }
  // Reply <=36 bytes. Leave sample priority to the next loop; no blocking writes.
  if (syncReady && Serial.availableForWrite()>=48) {
    uint32_t sent=micros();
    Serial.print("S,");Serial.print(syncToken);Serial.print(',');
    Serial.print(syncRx);Serial.print(',');Serial.println(sent);
    syncReady=false;
  }
}
void loop() { SampleGrip(); ServiceSync(); }
