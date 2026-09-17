export default function SopQueryTool() {
  return (
    <div className="relative h-screen w-screen overflow-hidden bg-[#1B3A5C] font-body text-white">
      <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(rgba(255,255,255,0.05)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.05)_1px,transparent_1px)] bg-[length:2vw_2vh]" />
      <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(rgba(255,255,255,0.1)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.1)_1px,transparent_1px)] bg-[length:10vw_10vh]" />
      <div className="pointer-events-none absolute inset-[3vh_3vw] border border-white/20" />
      <div className="pointer-events-none absolute inset-[5vh_5vw] border border-white/10" />
      <div className="relative flex h-full flex-col justify-between px-[7vw] py-[7vh]">
        <div className="flex justify-between">
          <div>
            <div className="text-[0.7vw] uppercase tracking-[0.2em] text-white/50">Drawing No.</div>
            <div className="font-mono text-[1vw] font-semibold">SQT-001</div>
          </div>
          <div className="text-right">
            <div className="text-[0.7vw] uppercase tracking-[0.2em] text-white/50">Date</div>
            <div className="font-mono text-[1vw]">2026-09-17</div>
          </div>
        </div>
        <div>
          <div className="mb-[1.5vh] text-[0.8vw] uppercase tracking-[0.3em] text-white/50">Project Title</div>
          <h1 className="m-0 max-w-[80vw] font-light text-[6vw] leading-[0.9] tracking-[0.05em]">SOP QUERY</h1>
          <h1 className="m-0 max-w-[80vw] font-light text-[6vw] leading-[0.9] tracking-[0.05em]">TOOL</h1>
          <div className="mt-[2vh] h-px w-[8vw] bg-white/40" />
          <p className="mt-[1.5vh] max-w-[42vw] text-[1.2vw] font-light leading-[1.6] text-white/65">
            A grounded question-answering system for SBA SOP 50 10 8
          </p>
          <p className="mt-[0.8vh] max-w-[42vw] font-mono text-[0.9vw] text-[#BAE6FD]">
            Project overview / September 2026
          </p>
        </div>
        <div className="flex justify-between border-t border-white/20 pt-[1.5vh]">
          <div>
            <div className="text-[0.6vw] uppercase tracking-[0.15em] text-white/40">Prepared By</div>
            <div className="font-mono text-[0.9vw]">SOP QUERY TOOL</div>
          </div>
          <div>
            <div className="text-[0.6vw] uppercase tracking-[0.15em] text-white/40">Classification</div>
            <div className="font-mono text-[0.9vw]">PROJECT OVERVIEW</div>
          </div>
          <div>
            <div className="text-[0.6vw] uppercase tracking-[0.15em] text-white/40">Scale</div>
            <div className="font-mono text-[0.9vw]">1:1</div>
          </div>
        </div>
      </div>
    </div>
  );
}