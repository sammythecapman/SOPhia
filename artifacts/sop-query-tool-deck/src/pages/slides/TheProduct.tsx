export default function TheProduct() {
  return (
    <div className="relative h-screen w-screen overflow-hidden bg-[#1B3A5C] font-body text-white">
      <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(rgba(255,255,255,0.05)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.05)_1px,transparent_1px)] bg-[length:2vw_2vh]" />
      <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(rgba(255,255,255,0.1)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.1)_1px,transparent_1px)] bg-[length:10vw_10vh]" />
      <div className="pointer-events-none absolute inset-[3vh_3vw] border border-white/25" />
      <div className="pointer-events-none absolute inset-[4vh_4vw] border-2 border-white/20" />
      <div className="relative flex h-full flex-col px-[8vw] py-[8vh]">
        <div className="flex justify-between">
          <div>
            <div className="text-[0.8vw] uppercase tracking-[0.2em] text-white/55">Section 01</div>
            <div className="font-mono text-[1.1vw] font-semibold">PRODUCT SCOPE</div>
          </div>
          <div className="text-right font-mono text-[1vw] text-[#BAE6FD]">REF: SQT-PRD-01</div>
        </div>
        <div className="mt-[8vh] flex flex-1 gap-[7vw]">
          <div className="w-[38vw]">
            <h2 className="m-0 font-light text-[4.5vw] leading-[0.95] tracking-[0.05em]">THE<br />PRODUCT</h2>
            <div className="mt-[3vh] h-px w-[10vw] bg-white/50" />
            <p className="mt-[2vh] max-w-[31vw] text-[1.25vw] font-light leading-[1.55] text-white/70">
              A focused research workspace for asking policy questions and seeing exactly where every answer comes from.
            </p>
          </div>
          <div className="flex flex-1 flex-col gap-[2.2vh] pt-[1vh]">
            <div className="border border-white/30 bg-white/[0.04] px-[2vw] py-[1.7vh]">
              <div className="font-mono text-[1.25vw] text-[#BAE6FD]">01</div>
              <div className="mt-[0.7vh] text-[1.7vw]">Ask policy questions in plain language</div>
            </div>
            <div className="border border-white/30 bg-white/[0.04] px-[2vw] py-[1.7vh]">
              <div className="font-mono text-[1.25vw] text-[#BAE6FD]">02</div>
              <div className="mt-[0.7vh] text-[1.7vw]">Retrieve the most relevant SOP passages</div>
            </div>
            <div className="border border-white/30 bg-white/[0.04] px-[2vw] py-[1.7vh]">
              <div className="font-mono text-[1.25vw] text-[#BAE6FD]">03</div>
              <div className="mt-[0.7vh] text-[1.7vw]">Answer only from retrieved context</div>
            </div>
            <div className="border border-white/30 bg-white/[0.04] px-[2vw] py-[1.7vh]">
              <div className="font-mono text-[1.25vw] text-[#BAE6FD]">04</div>
              <div className="mt-[0.7vh] text-[1.7vw]">Show exact quotes and source sections</div>
            </div>
            <div className="border border-white/30 bg-white/[0.04] px-[2vw] py-[1.7vh]">
              <div className="font-mono text-[1.25vw] text-[#BAE6FD]">05</div>
              <div className="mt-[0.7vh] text-[1.7vw]">Mark each citation verified or unverified</div>
            </div>
          </div>
        </div>
        <div className="flex justify-between border-t border-white/20 pt-[1.5vh] font-mono text-[0.85vw] text-white/55">
          <span>SOP QUERY TOOL / PRODUCT SCOPE</span>
          <span>PAGE 02</span>
        </div>
      </div>
    </div>
  );
}