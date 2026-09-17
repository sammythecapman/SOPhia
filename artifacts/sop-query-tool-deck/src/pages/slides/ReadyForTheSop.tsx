export default function ReadyForTheSop() {
  return (
    <div className="relative h-screen w-screen overflow-hidden bg-[#1B3A5C] font-body text-white">
      <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(rgba(255,255,255,0.05)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.05)_1px,transparent_1px)] bg-[length:2vw_2vh]" />
      <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(rgba(255,255,255,0.1)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.1)_1px,transparent_1px)] bg-[length:10vw_10vh]" />
      <div className="pointer-events-none absolute inset-[3vh_3vw] border border-white/25" />
      <div className="pointer-events-none absolute inset-[5vh_5vw] border border-white/10" />
      <div className="relative flex h-full flex-col px-[7vw] py-[7vh]">
        <div className="flex justify-between">
          <div>
            <div className="text-[0.8vw] uppercase tracking-[0.2em] text-white/55">Section 04</div>
            <div className="font-mono text-[1.1vw] font-semibold">PROJECT STATUS</div>
          </div>
          <div className="text-right font-mono text-[1vw] text-[#BAE6FD]">REF: SQT-END-04</div>
        </div>
        <div className="flex flex-1 flex-col items-center justify-center text-center">
          <div className="relative mb-[5vh] flex h-[16vw] w-[16vw] items-center justify-center rounded-full border border-white/40">
            <div className="absolute inset-[-1vw] rounded-full border border-dashed border-white/20" />
            <div className="flex h-[9vw] w-[9vw] items-center justify-center rounded-full border-2 border-white/80 bg-white/[0.05]">
              <div className="font-mono text-[3vw] font-light">&gt;_</div>
            </div>
          </div>
          <h2 className="m-0 font-light text-[4.5vw] tracking-[0.08em]">READY FOR THE SOP</h2>
          <div className="my-[3vh] h-px w-[12vw] bg-white/50" />
          <p className="max-w-[46vw] text-[1.25vw] font-light leading-[1.6] text-white/70">
            React frontend and Flask API are running. PostgreSQL pgvector schema and IVFFLAT index are initialized. The uploaded SOP is awaiting explicit ingestion approval.
          </p>
          <div className="mt-[4vh] border border-white/40 bg-white/[0.08] px-[3vw] py-[1.7vh]">
            <div className="font-mono text-[0.85vw] uppercase tracking-[0.2em] text-white/55">Next step</div>
            <div className="mt-[0.8vh] text-[1.3vw]">Review the preview, then approve the embedding pass</div>
          </div>
        </div>
        <div className="flex justify-between border-t border-white/20 pt-[1.5vh] font-mono text-[0.85vw] text-white/55">
          <span>SOP QUERY TOOL / PROJECT STATUS</span>
          <span>PAGE 05</span>
        </div>
      </div>
    </div>
  );
}