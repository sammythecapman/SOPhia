export default function TheRetrievalPipeline() {
  return (
    <div className="relative h-screen w-screen overflow-hidden bg-[#1B3A5C] font-body text-white">
      <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(rgba(255,255,255,0.05)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.05)_1px,transparent_1px)] bg-[length:2vw_2vh]" />
      <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(rgba(255,255,255,0.1)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.1)_1px,transparent_1px)] bg-[length:10vw_10vh]" />
      <div className="pointer-events-none absolute inset-[3vh_3vw] border border-white/25" />
      <div className="pointer-events-none absolute inset-[5vh_5vw] border border-white/10" />
      <div className="relative flex h-full flex-col px-[7vw] py-[7vh]">
        <div className="flex justify-between">
          <div>
            <div className="text-[0.8vw] uppercase tracking-[0.2em] text-white/55">Section 02</div>
            <div className="font-mono text-[1.1vw] font-semibold">RETRIEVAL SYSTEM</div>
          </div>
          <div className="text-right font-mono text-[1vw] text-[#BAE6FD]">REF: SQT-RET-02</div>
        </div>
        <div className="mt-[5vh]">
          <h2 className="m-0 font-light text-[3.6vw] tracking-[0.05em]">THE RETRIEVAL PIPELINE</h2>
          <div className="mt-[1.7vh] h-px w-[13vw] bg-white/45" />
        </div>
        <div className="mt-[5vh] flex flex-1 items-center gap-[1.2vw]">
          <div className="flex h-[35vh] flex-1 flex-col justify-between border border-white/35 bg-white/[0.04] p-[1.8vw]">
            <div className="font-mono text-[1.3vw] text-[#BAE6FD]">01 / INGEST</div>
            <div>
              <div className="text-[2vw] font-semibold">DOCX</div>
              <p className="mt-[1vh] text-[1.15vw] leading-[1.45] text-white/70">DOCX headings become section-aware chunks</p>
            </div>
          </div>
          <div className="font-mono text-[2vw] text-[#BAE6FD]">→</div>
          <div className="flex h-[35vh] flex-1 flex-col justify-between border border-white/35 bg-white/[0.04] p-[1.8vw]">
            <div className="font-mono text-[1.3vw] text-[#BAE6FD]">02 / EMBED</div>
            <div>
              <div className="text-[2vw] font-semibold">VECTOR</div>
              <p className="mt-[1vh] text-[1.15vw] leading-[1.45] text-white/70">OpenAI text-embedding-3-small represents each chunk and question</p>
            </div>
          </div>
          <div className="font-mono text-[2vw] text-[#BAE6FD]">→</div>
          <div className="flex h-[35vh] flex-1 flex-col justify-between border border-white/35 bg-white/[0.04] p-[1.8vw]">
            <div className="font-mono text-[1.3vw] text-[#BAE6FD]">03 / RANK</div>
            <div>
              <div className="text-[2vw] font-semibold">PGVECTOR</div>
              <p className="mt-[1vh] text-[1.15vw] leading-[1.45] text-white/70">PostgreSQL + pgvector ranks matches by cosine similarity</p>
            </div>
          </div>
          <div className="font-mono text-[2vw] text-[#BAE6FD]">→</div>
          <div className="flex h-[35vh] flex-1 flex-col justify-between border border-white/35 bg-white/[0.04] p-[1.8vw]">
            <div className="font-mono text-[1.3vw] text-[#BAE6FD]">04 / ANSWER</div>
            <div>
              <div className="text-[2vw] font-semibold">CLAUDE</div>
              <p className="mt-[1vh] text-[1.15vw] leading-[1.45] text-white/70">Claude composes a constrained answer from delimited context</p>
            </div>
          </div>
        </div>
        <div className="border-t border-white/20 pt-[2vh] text-[1.15vw] text-white/70">
          The API returns answer text plus grounded source excerpts
        </div>
        <div className="mt-[1.5vh] flex justify-between font-mono text-[0.85vw] text-white/55">
          <span>SOP QUERY TOOL / RETRIEVAL SYSTEM</span>
          <span>PAGE 03</span>
        </div>
      </div>
    </div>
  );
}