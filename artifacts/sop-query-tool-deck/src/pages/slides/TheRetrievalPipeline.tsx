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
        <div className="mt-[4vh] grid flex-1 grid-cols-2 gap-[1.5vw]">
          <div className="border border-white/35 bg-white/[0.04] p-[1.5vw]">
            <div className="font-mono text-[1.2vw] text-[#BAE6FD]">01 / INGEST</div>
            <div className="mt-[1.5vh] text-[1.9vw] font-semibold">DOCX chunks</div>
            <p className="mt-[1vh] text-[1.6vw] leading-[1.35] text-white/75">DOCX content is split into section-aware chunks</p>
          </div>
          <div className="border border-white/35 bg-white/[0.04] p-[1.5vw]">
            <div className="font-mono text-[1.2vw] text-[#BAE6FD]">02 / EMBED</div>
            <div className="mt-[1.5vh] text-[1.9vw] font-semibold">Vector representation</div>
            <p className="mt-[1vh] text-[1.6vw] leading-[1.35] text-white/75">text-embedding-3-small converts chunks and questions into vectors</p>
          </div>
          <div className="border border-white/35 bg-white/[0.04] p-[1.5vw]">
            <div className="font-mono text-[1.2vw] text-[#BAE6FD]">03 / RANK</div>
            <div className="mt-[1.5vh] text-[1.9vw] font-semibold">PostgreSQL + pgvector</div>
            <p className="mt-[1vh] text-[1.6vw] leading-[1.35] text-white/75">PostgreSQL + pgvector ranks matches by cosine similarity</p>
          </div>
          <div className="border border-white/35 bg-white/[0.04] p-[1.5vw]">
            <div className="font-mono text-[1.2vw] text-[#BAE6FD]">04 / ANSWER</div>
            <div className="mt-[1.5vh] text-[1.9vw] font-semibold">Claude context</div>
            <p className="mt-[1vh] text-[1.6vw] leading-[1.35] text-white/75">Claude answers from retrieved context only</p>
          </div>
          <div className="col-span-2 border border-white/35 bg-white/[0.04] p-[1.5vw]">
            <div className="flex items-baseline gap-[2vw]">
              <div className="font-mono text-[1.2vw] text-[#BAE6FD]">05 / RETURN</div>
              <div className="text-[1.9vw] font-semibold">API excerpts</div>
            </div>
            <p className="mt-[1vh] text-[1.6vw] leading-[1.35] text-white/75">The API returns answers with grounded source excerpts</p>
          </div>
        </div>
        <div className="mt-[1.5vh] flex justify-between font-mono text-[0.85vw] text-white/55">
          <span>SOP QUERY TOOL / RETRIEVAL SYSTEM</span>
          <span>PAGE 03</span>
        </div>
      </div>
    </div>
  );
}