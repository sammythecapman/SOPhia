export default function IngestionControls() {
  return (
    <div className="relative h-screen w-screen overflow-hidden bg-[#1B3A5C] font-body text-white">
      <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(rgba(255,255,255,0.05)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.05)_1px,transparent_1px)] bg-[length:2vw_2vh]" />
      <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(rgba(255,255,255,0.1)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.1)_1px,transparent_1px)] bg-[length:10vw_10vh]" />
      <div className="pointer-events-none absolute inset-[3vh_3vw] border border-white/25" />
      <div className="pointer-events-none absolute inset-[5vh_5vw] border border-white/10" />
      <div className="relative flex h-full flex-col px-[7vw] py-[7vh]">
        <div className="flex justify-between">
          <div>
            <div className="text-[0.8vw] uppercase tracking-[0.2em] text-white/55">Section 03</div>
            <div className="font-mono text-[1.1vw] font-semibold">DATA CONTROLS</div>
          </div>
          <div className="text-right font-mono text-[1vw] text-[#BAE6FD]">REF: SQT-ING-03</div>
        </div>
        <div className="mt-[6vh] flex flex-1 gap-[6vw]">
          <div className="flex w-[36vw] flex-col justify-center">
            <h2 className="m-0 font-light text-[4.2vw] leading-[0.95] tracking-[0.05em]">INGESTION<br />CONTROLS</h2>
            <div className="mt-[3vh] h-px w-[11vw] bg-white/50" />
            <div className="mt-[3vh] border border-white/35 bg-white/[0.04] p-[2vw]">
              <div className="font-mono text-[1.1vw] text-[#BAE6FD]">CURRENT DOCUMENT PREVIEW</div>
              <div className="mt-[1vh] font-mono text-[5vw] font-light leading-none">422</div>
              <div className="mt-[0.8vh] text-[1.2vw] text-white/70">chunks / database rows: 0</div>
            </div>
          </div>
          <div className="flex flex-1 flex-col justify-center gap-[1.7vh]">
            <div className="border-l-2 border-[#BAE6FD] pl-[1.7vw]">
              <div className="font-mono text-[1.2vw] text-[#BAE6FD]">PREVIEW</div>
              <div className="mt-[0.7vh] text-[1.65vw]">Preview-only mode prints section references and chunk text</div>
            </div>
            <div className="border-l-2 border-[#BAE6FD] pl-[1.7vw]">
              <div className="font-mono text-[1.2vw] text-[#BAE6FD]">NO WRITE</div>
              <div className="mt-[0.7vh] text-[1.65vw]">No embeddings or database writes happen during preview</div>
            </div>
            <div className="border-l-2 border-[#BAE6FD] pl-[1.7vw]">
              <div className="font-mono text-[1.2vw] text-[#BAE6FD]">APPROVAL</div>
              <div className="mt-[0.7vh] text-[1.65vw]">Explicit approval is required for the full pass</div>
            </div>
            <div className="border-l-2 border-[#BAE6FD] pl-[1.7vw]">
              <div className="font-mono text-[1.2vw] text-[#BAE6FD]">RESILIENCE</div>
              <div className="mt-[0.7vh] text-[1.65vw]">Batching, retries, progress tracking, and safe reruns protect the full pass</div>
            </div>
            <div className="border-l-2 border-[#BAE6FD] pl-[1.7vw]">
              <div className="font-mono text-[1.2vw] text-[#BAE6FD]">PREVIEW STATUS</div>
              <div className="mt-[0.7vh] text-[1.65vw]">Current document preview: 422 chunks; database rows: 0</div>
            </div>
          </div>
        </div>
        <div className="flex justify-between border-t border-white/20 pt-[1.5vh] font-mono text-[0.85vw] text-white/55">
          <span>SOP QUERY TOOL / DATA CONTROLS</span>
          <span>PAGE 04</span>
        </div>
      </div>
    </div>
  );
}