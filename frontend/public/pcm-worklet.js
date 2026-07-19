class EmotionFlowPCMProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.samples = [];
    this.phase = 0;
    this.targetRate = 16000;
    this.targetSamples = 4000;
  }

  process(inputs) {
    const input = inputs[0]?.[0];
    if (!input) return true;

    // Stateful rate conversion avoids losing a fractional sample at every 128-frame block.
    for (let index = 0; index < input.length; index++) {
      this.phase += this.targetRate;
      if (this.phase >= sampleRate) {
        this.phase -= sampleRate;
        this.samples.push(Math.max(-1, Math.min(1, input[index])));
      }
    }

    while (this.samples.length >= this.targetSamples) {
      const frame = this.samples.splice(0, this.targetSamples);
      const pcm = new Int16Array(this.targetSamples);
      for (let index = 0; index < frame.length; index++) {
        pcm[index] = frame[index] < 0 ? frame[index] * 32768 : frame[index] * 32767;
      }
      this.port.postMessage(pcm.buffer, [pcm.buffer]);
    }
    return true;
  }
}

registerProcessor("emotionflow-pcm", EmotionFlowPCMProcessor);
