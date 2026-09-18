import { useState } from "react";
import { useQuerySop } from "@workspace/api-client-react";
import type {
  SopGuarantorRow,
  SopProposition,
  SopSource,
} from "@workspace/api-client-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertTitle, AlertDescription } from "@/components/ui/alert";
import {
  AlertCircle,
  AlertTriangle,
  ArrowRight,
  BookOpen,
  FileText,
  Library,
  ShieldCheck,
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

function formatDate(date: string) {
  const parsed = new Date(`${date}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) return date;
  return parsed.toLocaleDateString("en-US", {
    month: "long",
    day: "numeric",
    year: "numeric",
  });
}

function contextWindow(source: SopSource) {
  const text = source.source_chunk;
  const quoteStart = text.indexOf(source.quote);
  if (quoteStart < 0) {
    return { before: "", quote: "", after: text };
  }
  const windowStart = Math.max(0, quoteStart - 420);
  const windowEnd = Math.min(text.length, quoteStart + source.quote.length + 420);
  return {
    before: `${windowStart > 0 ? "… " : ""}${text.slice(windowStart, quoteStart)}`,
    quote: source.quote,
    after: `${text.slice(quoteStart + source.quote.length, windowEnd)}${
      windowEnd < text.length ? " …" : ""
    }`,
  };
}

function CitationCard({ source }: { source: SopSource }) {
  const context = contextWindow(source);
  return (
    <details id={`citation-${source.source_id}`} className="rounded-lg border border-border/60 bg-white/70 shadow-sm">
      <summary className="cursor-pointer list-none px-5 py-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-sm font-sans leading-relaxed text-primary">{source.section_ref}</p>
            <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
              <span>{source.source_version}</span>
              <span aria-hidden="true">·</span>
              <span>
                {source.page_number ? `Page ${source.page_number}` : "Page not recorded"}
              </span>
              <span aria-hidden="true">·</span>
              <span>Open cited passage</span>
            </div>
          </div>
          <div className="flex shrink-0 flex-wrap gap-2">
            {source.applicability_status === "not_applicable" ? (
              <Badge
                variant="outline"
                className="gap-1 border-rose-300 bg-rose-50 text-[10px] font-semibold uppercase tracking-wider text-rose-800"
              >
                <AlertTriangle className="h-3 w-3" />
                Not applicable
              </Badge>
            ) : source.supports_conclusion ? (
              <Badge
                variant="outline"
                className="gap-1 border-primary/30 bg-primary/5 text-[10px] font-semibold uppercase tracking-wider text-primary"
              >
                <ShieldCheck className="h-3 w-3" />
                Supports this conclusion
              </Badge>
            ) : (
              <Badge
                variant="outline"
                className="gap-1 border-amber-300 bg-amber-50 text-[10px] font-semibold uppercase tracking-wider text-amber-800"
              >
                <AlertTriangle className="h-3 w-3" />
                Support not established
              </Badge>
            )}
          </div>
        </div>
      </summary>
      <div className="border-t border-border/60 px-5 py-5">
        <div className="rounded-md bg-secondary/10 px-4 py-4 font-serif text-sm leading-7 text-foreground/75">
          <span>{context.before}</span>
          <mark className="rounded bg-amber-200/80 px-1 py-0.5 text-foreground">
            {context.quote || source.quote}
          </mark>
          <span>{context.after}</span>
        </div>
        {source.applicability_reason && (
          <p className="mt-4 rounded-md border border-rose-200 bg-rose-50 px-4 py-3 text-xs leading-relaxed text-rose-900">
            {source.applicability_reason}
          </p>
        )}
      </div>
    </details>
  );
}

function ProvisionsToRead({ sources }: { sources: SopSource[] }) {
  if (sources.length === 0) return null;
  return (
    <section className="rounded-lg border border-border/60 bg-white/70 px-5 py-4">
      <div className="flex items-center gap-2">
        <FileText className="h-4 w-4 text-primary" />
        <h3 className="font-sans text-xs font-semibold uppercase tracking-widest text-primary">
          Provisions to read
        </h3>
      </div>
      <ul className="mt-3 space-y-2 text-sm text-foreground/80">
        {sources.map((source) => (
          <li key={`${source.source_id}-${source.page_number}`} className="flex gap-2">
            <span className="text-primary">•</span>
            <span>
              <a className="hover:underline" href={`#citation-${source.source_id}`}>
                {source.section_ref}
                <span className="ml-2 text-xs text-muted-foreground">
                  {source.page_number ? `Page ${source.page_number}` : "Page not recorded"}
                </span>
              </a>
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function RejectedEvidence({ sources }: { sources: SopSource[] }) {
  if (sources.length === 0) return null;
  return (
    <details className="rounded-lg border border-amber-200 bg-amber-50/60">
      <summary className="cursor-pointer list-none px-5 py-4 text-xs font-semibold uppercase tracking-widest text-amber-900">
        Retrieved evidence reviewed and rejected · {sources.length} provisions
      </summary>
      <div className="space-y-2 border-t border-amber-200 px-5 py-4 text-xs text-amber-950">
        {sources.map((source, index) => (
          <div key={`${source.source_id}-${index}`} className="border-b border-amber-200/70 pb-2 last:border-0 last:pb-0">
            <div className="font-semibold">
              {source.section_ref} · {source.page_number ? `Page ${source.page_number}` : "Page not recorded"}
            </div>
            {source.applicability_reason && <div>{source.applicability_reason}</div>}
          </div>
        ))}
      </div>
    </details>
  );
}

function Proposition({
  proposition,
  seenCitationIds,
}: {
  proposition: SopProposition;
  seenCitationIds: Set<number>;
}) {
  return (
    <div className="space-y-4 rounded-lg border border-border/50 bg-white/60 p-5">
      <p className="font-serif text-lg leading-8 text-foreground/90">{proposition.text}</p>
      <div className="space-y-4">
        {proposition.citations.map((source, index) => {
          const alreadyShown = seenCitationIds.has(source.source_id);
          seenCitationIds.add(source.source_id);
          return alreadyShown ? (
            <div
              key={`${source.source_id}-${index}`}
              className="rounded-md border border-border/50 bg-secondary/10 px-4 py-3 text-xs text-muted-foreground"
            >
                        <a className="hover:underline" href={`#citation-${source.source_id}`}>
                          See cited passage above ·{" "}
                          {source.page_number ? `Page ${source.page_number}` : "source page not recorded"}
                        </a>
            </div>
          ) : (
            <CitationCard key={`${source.source_id}-${index}`} source={source} />
          );
        })}
      </div>
    </div>
  );
}

function GuarantorTable({
  rows,
  seenCitationIds,
}: {
  rows: SopGuarantorRow[];
  seenCitationIds: Set<number>;
}) {
  return (
    <div className="overflow-x-auto rounded-lg border border-border/60 bg-white/70">
      <table className="w-full min-w-[920px] border-collapse text-left text-sm">
        <thead className="bg-secondary/30 text-[10px] uppercase tracking-widest text-muted-foreground">
          <tr>
            <th className="px-4 py-3 font-semibold">Party</th>
            <th className="px-4 py-3 font-semibold">Capacity</th>
            <th className="px-4 py-3 font-semibold">Ownership</th>
            <th className="px-4 py-3 font-semibold">Guaranty</th>
            <th className="px-4 py-3 font-semibold">Triggering provision</th>
            <th className="px-4 py-3 font-semibold">Additional conditions</th>
            <th className="px-4 py-3 font-semibold">Status</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={`${row.party}-${row.capacity}-${index}`} className="border-t border-border/50 align-top">
              <td className="px-4 py-4 font-semibold text-primary">{row.party}</td>
              <td className="px-4 py-4 text-foreground/80">{row.capacity}</td>
              <td className="px-4 py-4 text-foreground/80">
                {row.ownership_percentage == null
                  ? "Not stated"
                  : `${row.ownership_percentage}%`}
                {row.ownership_comparison && (
                  <div className="mt-1 text-xs leading-relaxed text-muted-foreground">
                    {row.ownership_comparison}
                  </div>
                )}
              </td>
              <td className="px-4 py-4 font-medium text-foreground/90">{row.guaranty_type}</td>
              <td className="px-4 py-4 text-foreground/80">{row.triggering_provision}</td>
              <td className="px-4 py-4 text-foreground/80">{row.additional_conditions}</td>
              <td className="px-4 py-4">
                <Badge
                  variant="outline"
                  className={
                    row.status === "required"
                      ? "border-emerald-700/30 bg-emerald-50 text-[10px] font-semibold uppercase tracking-wider text-emerald-800"
                      : "border-amber-300 bg-amber-50 text-[10px] font-semibold uppercase tracking-wider text-amber-800"
                  }
                >
                  {row.status === "required" ? "Required" : "Unresolved"}
                </Badge>
                <div className="mt-3 space-y-2">
                  {row.citations.map((source, citationIndex) => {
                    const alreadyShown = seenCitationIds.has(source.source_id);
                    seenCitationIds.add(source.source_id);
                    return alreadyShown ? (
                      <div
                        key={`${source.source_id}-${citationIndex}`}
                        className="text-[11px] text-muted-foreground"
                      >
                        <a className="hover:underline" href={`#citation-${source.source_id}`}>
                          See cited passage above ·{" "}
                          {source.page_number ? `Page ${source.page_number}` : "source page not recorded"}
                        </a>
                      </div>
                    ) : (
                      <CitationCard key={`${source.source_id}-${citationIndex}`} source={source} />
                    );
                  })}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function Home() {
  const [question, setQuestion] = useState("");
  const { mutate, data: result, isPending, error } = useQuerySop();

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!question.trim()) return;
    mutate({ data: { question: question.trim() } });
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  return (
    <div className="relative flex min-h-screen flex-col overflow-hidden bg-background text-foreground">
      <div
        className="pointer-events-none absolute inset-0 z-0 opacity-[0.03]"
        style={{
          backgroundImage:
            "radial-gradient(circle at 1px 1px, black 1px, transparent 0)",
          backgroundSize: "24px 24px",
        }}
      />

      <header className="sticky top-0 z-10 flex w-full items-center justify-between border-b border-border/50 bg-background/90 px-6 py-5 backdrop-blur-sm md:px-8">
        <div className="flex items-center gap-3">
          <div className="rounded-md bg-primary p-2">
            <Library className="h-5 w-5 text-primary-foreground" />
          </div>
          <div>
            <h1 className="m-0 font-serif text-xl font-medium leading-none text-primary">
              SOP 50 10 8.1
            </h1>
            <span className="mt-1 block font-sans text-xs font-semibold uppercase tracking-widest text-muted-foreground">
              Lender Policy Query
            </span>
          </div>
        </div>
      </header>

      <main className="z-10 mx-auto flex w-full max-w-5xl flex-1 flex-col gap-8 p-6 md:p-8">
        <AnimatePresence>
          {!result && !isPending && (
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, height: 0, overflow: "hidden" }}
              transition={{ duration: 0.3 }}
              className="mx-auto mb-4 mt-12 max-w-2xl text-center"
            >
              <h2 className="mb-4 font-serif text-4xl leading-tight text-primary md:text-5xl">
                Ask a policy question.
              </h2>
              <p className="text-lg text-muted-foreground">
                Search the authoritative Small Business Administration SOP 50 10 8.1
                documentation. Every conclusion is tied to a source passage.
              </p>
            </motion.div>
          )}
        </AnimatePresence>

        <motion.div layout className="relative z-20 w-full">
          <Card className="overflow-hidden border-primary/10 shadow-lg ring-1 ring-black/5">
            <form onSubmit={handleSubmit} className="relative flex flex-col">
              <Textarea
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="E.g., Do ROBS funds count toward the equity injection, and who must provide the guaranty?"
                className="min-h-[120px] resize-none rounded-none border-0 bg-transparent p-6 font-serif text-lg leading-relaxed placeholder:text-muted-foreground/60 focus-visible:ring-0"
                disabled={isPending}
                data-testid="input-question"
              />
              <div className="flex items-center justify-between border-t border-border/50 bg-secondary/30 px-4 py-3">
                <span className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                  <kbd className="rounded border bg-background px-1.5 py-0.5 font-sans text-[10px] shadow-sm">
                    Enter
                  </kbd>{" "}
                  to submit
                </span>
                <Button
                  type="submit"
                  disabled={!question.trim() || isPending}
                  className="rounded-full pl-5 pr-4 shadow-sm"
                  data-testid="button-submit-query"
                >
                  {isPending ? "Analyzing..." : "Search Policy"}
                  {isPending ? (
                    <motion.div
                      animate={{ rotate: 360 }}
                      transition={{ repeat: Infinity, duration: 1, ease: "linear" }}
                      className="ml-2 h-4 w-4 rounded-full border-2 border-primary-foreground/30 border-t-primary-foreground"
                    />
                  ) : (
                    <ArrowRight className="ml-2 h-4 w-4" />
                  )}
                </Button>
              </div>
            </form>
          </Card>
        </motion.div>

        {error && (
          <motion.div initial={{ opacity: 0, y: 5 }} animate={{ opacity: 1, y: 0 }}>
            <Alert
              variant="destructive"
              className="border-destructive/20 bg-destructive/10 text-destructive-foreground"
            >
              <AlertCircle className="h-4 w-4" />
              <AlertTitle className="font-serif">Query Failed</AlertTitle>
              <AlertDescription>
                We could not complete the policy analysis. Please try again or simplify the
                question.
              </AlertDescription>
            </Alert>
          </motion.div>
        )}

        {isPending && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="mt-4 space-y-6">
            <div className="space-y-3">
              <Skeleton className="h-6 w-3/4 bg-primary/10" />
              <Skeleton className="h-6 w-full bg-primary/10" />
              <Skeleton className="h-6 w-5/6 bg-primary/10" />
            </div>
            <div className="border-t border-border/50 pt-6">
              <Skeleton className="mb-4 h-5 w-48 bg-primary/5" />
              <Skeleton className="h-48 w-full rounded-lg bg-primary/5" />
            </div>
          </motion.div>
        )}

        <AnimatePresence mode="wait">
          {result && !isPending && (
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              className="flex w-full flex-col gap-8 pb-16"
              data-testid="container-results"
            >
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/50 pb-4">
                <div className="flex items-center gap-2">
                  <BookOpen className="h-5 w-5 text-primary" />
                  <h3 className="font-sans text-lg font-semibold tracking-tight text-primary">
                    Policy Answer
                  </h3>
                </div>
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  <span>{result.source_version}</span>
                  <span>·</span>
                  <span>Effective {formatDate(result.effective_date)}</span>
                </div>
              </div>

              {(result.version_warning || result.date_warning) && (
                <Alert className="border-amber-300 bg-amber-50 text-amber-950">
                  <AlertTriangle className="h-4 w-4" />
                  <AlertTitle>Version and effective-date notice</AlertTitle>
                  <AlertDescription className="space-y-1">
                    {result.version_warning && <p>{result.version_warning}</p>}
                    {result.date_warning && <p>{result.date_warning}</p>}
                  </AlertDescription>
                </Alert>
              )}

              <Card className="border-primary/15 bg-primary/[0.04] shadow-sm">
                <CardHeader className="pb-3">
                  <CardTitle className="text-xs font-semibold uppercase tracking-widest text-primary">
                    Bottom line
                  </CardTitle>
                </CardHeader>
                <CardContent className="font-serif text-xl leading-8 text-foreground/90">
                  {result.summary}
                </CardContent>
              </Card>

              <ProvisionsToRead sources={result.provisions_to_read ?? []} />

              <div className="space-y-7">
                {(() => {
                  const seenCitationIds = new Set<number>();
                  const rejected = Array.from(
                    new Map(
                      result.subanswers
                        .flatMap((subanswer) => subanswer.rejected_citations)
                        .map((source) => [
                          `${source.source_id}-${source.applicability_reason ?? ""}`,
                          source,
                        ]),
                    ).values(),
                  );
                  return (
                    <>
                      {result.subanswers.map((subanswer, index) => (
                        <section key={`${subanswer.question}-${index}`} className="space-y-4">
                          {result.subanswers.length > 1 && (
                            <h4 className="font-sans text-sm font-semibold uppercase tracking-wider text-muted-foreground">
                              {subanswer.question}
                            </h4>
                          )}
                          {subanswer.support_status === "not_established" && (
                            <Alert className="border-amber-300 bg-amber-50 text-amber-950">
                              <AlertTriangle className="h-4 w-4" />
                              <AlertTitle>Support not established</AlertTitle>
                              <AlertDescription>
                                {subanswer.support_note ??
                                  "The retrieved rule did not establish the applied conclusion."}
                              </AlertDescription>
                            </Alert>
                          )}
                          {subanswer.support_status === "not_applicable" && (
                            <Alert className="border-rose-300 bg-rose-50 text-rose-950">
                              <AlertTriangle className="h-4 w-4" />
                              <AlertTitle>Provision not applicable to this transaction type</AlertTitle>
                              <AlertDescription>
                                {subanswer.support_note ??
                                  "The retrieved provision governs a different transaction or fact pattern."}
                              </AlertDescription>
                            </Alert>
                          )}
                          {(subanswer.support_status === "no_responsive_provision" ||
                            subanswer.support_status === "retrieval_empty") && (
                            <Alert className="border-amber-300 bg-amber-50 text-amber-950">
                              <AlertTriangle className="h-4 w-4" />
                              <AlertTitle>Retrieval found no responsive provision</AlertTitle>
                              <AlertDescription>{subanswer.support_note}</AlertDescription>
                            </Alert>
                          )}
                          {subanswer.applied_conclusion && (
                            <section className="space-y-2">
                              <h5 className="font-sans text-xs font-semibold uppercase tracking-widest text-primary">
                                Applied conclusion
                              </h5>
                              <Proposition
                                proposition={subanswer.applied_conclusion}
                                seenCitationIds={seenCitationIds}
                              />
                            </section>
                          )}
                          {subanswer.guarantor_rows.length > 0 && (
                            <section className="space-y-2">
                              <h5 className="font-sans text-xs font-semibold uppercase tracking-widest text-primary">
                                Guarantors by party and capacity
                              </h5>
                              <GuarantorTable
                                rows={subanswer.guarantor_rows}
                                seenCitationIds={seenCitationIds}
                              />
                            </section>
                          )}
                          {subanswer.propositions.length > 0 && (
                            <section className="space-y-2">
                              <h5 className="font-sans text-xs font-semibold uppercase tracking-widest text-muted-foreground">
                                Supporting SOP provisions
                              </h5>
                              {subanswer.propositions.map((proposition, propositionIndex) => (
                                <Proposition
                                  key={`${subanswer.question}-${propositionIndex}`}
                                  proposition={proposition}
                                  seenCitationIds={seenCitationIds}
                                />
                              ))}
                            </section>
                          )}
                        </section>
                      ))}
                      <RejectedEvidence sources={rejected} />
                    </>
                  );
                })()}
              </div>

              {result.other_issues.length > 0 && (
                <section className="space-y-4 border-t border-border/50 pt-6">
                  <div className="flex items-center gap-2">
                    <AlertTriangle className="h-5 w-5 text-amber-700" />
                    <h3 className="font-sans text-sm font-semibold uppercase tracking-wider text-amber-900">
                      Other issues identified
                    </h3>
                  </div>
                  {result.other_issues.map((issue, index) => (
                    <Proposition
                      key={`other-issue-${index}`}
                      proposition={issue}
                      seenCitationIds={new Set<number>()}
                    />
                  ))}
                </section>
              )}
            </motion.div>
          )}
        </AnimatePresence>
      </main>
    </div>
  );
}