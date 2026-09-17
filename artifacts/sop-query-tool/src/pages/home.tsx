import { useState } from "react";
import { useQuerySop } from "@workspace/api-client-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertTitle, AlertDescription } from "@/components/ui/alert";
import { 
  Search, 
  BookOpen, 
  CheckCircle2, 
  HelpCircle,
  AlertCircle,
  ArrowRight,
  Library
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

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
    <div className="min-h-screen bg-background text-foreground flex flex-col relative overflow-hidden">
      {/* Subtle Background Pattern */}
      <div className="absolute inset-0 z-0 pointer-events-none opacity-[0.03]" style={{ backgroundImage: 'radial-gradient(circle at 1px 1px, black 1px, transparent 0)', backgroundSize: '24px 24px' }}></div>
      
      <header className="w-full py-6 px-8 border-b border-border/50 bg-background/80 backdrop-blur-sm sticky top-0 z-10 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="bg-primary p-2 rounded-md">
            <Library className="w-5 h-5 text-primary-foreground" />
          </div>
          <div>
            <h1 className="text-xl font-serif font-medium text-primary m-0 leading-none">SOP 50 10 8</h1>
            <span className="text-xs text-muted-foreground uppercase tracking-widest font-sans font-semibold mt-1 block">Lender Policy Query</span>
          </div>
        </div>
      </header>

      <main className="flex-1 w-full max-w-4xl mx-auto p-6 md:p-8 flex flex-col gap-8 z-10">
        
        {/* Intro Section - only visible when no result and not loading */}
        <AnimatePresence>
          {!result && !isPending && (
            <motion.div 
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, height: 0, overflow: 'hidden' }}
              transition={{ duration: 0.3 }}
              className="mt-12 mb-4 text-center max-w-2xl mx-auto"
            >
              <h2 className="text-4xl md:text-5xl font-serif text-primary mb-4 leading-tight">
                Ask a policy question.
              </h2>
              <p className="text-muted-foreground text-lg">
                Search the authoritative Small Business Administration SOP 50 10 8 documentation. Grounded answers, direct citations.
              </p>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Search Box */}
        <motion.div 
          layout
          className="w-full relative z-20"
        >
          <Card className="shadow-lg border-primary/10 overflow-hidden ring-1 ring-black/5">
            <form onSubmit={handleSubmit} className="relative flex flex-col">
              <Textarea 
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="E.g., What are the equity injection requirements for a change of ownership?"
                className="min-h-[120px] resize-none border-0 focus-visible:ring-0 rounded-none text-lg p-6 bg-transparent placeholder:text-muted-foreground/60 leading-relaxed font-serif"
                disabled={isPending}
                data-testid="input-question"
              />
              <div className="flex items-center justify-between px-4 py-3 bg-secondary/30 border-t border-border/50">
                <span className="text-xs text-muted-foreground flex items-center gap-1.5 font-medium">
                  <kbd className="px-1.5 py-0.5 bg-background border rounded text-[10px] font-sans shadow-sm">Enter</kbd> to submit
                </span>
                <Button 
                  type="submit" 
                  disabled={!question.trim() || isPending}
                  className="rounded-full pl-5 pr-4 shadow-sm"
                  data-testid="button-submit-query"
                >
                  {isPending ? "Searching..." : "Search Policy"}
                  {isPending ? (
                    <motion.div 
                      animate={{ rotate: 360 }} 
                      transition={{ repeat: Infinity, duration: 1, ease: "linear" }}
                      className="ml-2 w-4 h-4 border-2 border-primary-foreground/30 border-t-primary-foreground rounded-full"
                    />
                  ) : (
                    <ArrowRight className="w-4 h-4 ml-2" />
                  )}
                </Button>
              </div>
            </form>
          </Card>
        </motion.div>

        {/* Error State */}
        {error && (
          <motion.div 
            initial={{ opacity: 0, y: 5 }} 
            animate={{ opacity: 1, y: 0 }}
            className="w-full"
          >
            <Alert variant="destructive" className="bg-destructive/10 border-destructive/20 text-destructive-foreground">
              <AlertCircle className="h-4 w-4" />
              <AlertTitle className="font-serif">Query Failed</AlertTitle>
              <AlertDescription>
                We could not process your question. Please try refining your terminology or try again later.
              </AlertDescription>
            </Alert>
          </motion.div>
        )}

        {/* Loading State */}
        {isPending && (
          <motion.div 
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="w-full space-y-6 mt-4"
          >
            <div className="space-y-3">
              <Skeleton className="h-6 w-3/4 bg-primary/10" />
              <Skeleton className="h-6 w-full bg-primary/10" />
              <Skeleton className="h-6 w-5/6 bg-primary/10" />
            </div>
            
            <div className="pt-6 border-t border-border/50">
              <Skeleton className="h-5 w-40 mb-4 bg-primary/5" />
              <div className="grid gap-4 md:grid-cols-2">
                <Skeleton className="h-40 w-full rounded-lg bg-primary/5" />
                <Skeleton className="h-40 w-full rounded-lg bg-primary/5" />
              </div>
            </div>
          </motion.div>
        )}

        {/* Results State */}
        <AnimatePresence mode="wait">
          {result && !isPending && (
            <motion.div 
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              className="w-full flex flex-col gap-8 pb-16"
              data-testid="container-results"
            >
              {/* Answer Section */}
              <div className="prose prose-slate max-w-none prose-headings:font-serif prose-p:leading-relaxed prose-p:text-slate-700">
                <h3 className="flex items-center gap-2 text-lg font-sans font-semibold tracking-tight text-primary mb-4 border-b border-border/50 pb-2">
                  <BookOpen className="w-5 h-5" />
                  Policy Answer
                </h3>
                <div className="text-lg leading-loose font-serif text-foreground/90 whitespace-pre-wrap">
                  {result.answer}
                </div>
              </div>

              {/* Citations Section */}
              {result.sources && result.sources.length > 0 && (
                <div className="mt-4">
                  <h3 className="flex items-center gap-2 text-sm font-sans font-semibold tracking-wider text-muted-foreground uppercase mb-4">
                    Supporting Citations
                  </h3>
                  <div className="grid gap-4 md:grid-cols-2">
                    {result.sources.map((source, idx) => (
                      <Card key={idx} className="bg-secondary/20 border-border/50 shadow-sm flex flex-col h-full" data-testid={`card-source-${idx}`}>
                        <CardHeader className="py-4 px-5 border-b border-border/50 bg-secondary/30 flex flex-row items-start justify-between gap-4">
                          <div>
                            <CardTitle className="text-sm font-sans text-primary">Section {source.section_ref}</CardTitle>
                          </div>
                          {source.verified ? (
                            <Badge variant="default" className="bg-emerald-700 hover:bg-emerald-800 text-white font-medium text-[10px] uppercase tracking-wider py-0.5 flex gap-1">
                              <CheckCircle2 className="w-3 h-3" />
                              Verified
                            </Badge>
                          ) : (
                            <Badge variant="secondary" className="bg-amber-100 text-amber-800 hover:bg-amber-200 border-amber-200 font-medium text-[10px] uppercase tracking-wider py-0.5 flex gap-1">
                              <HelpCircle className="w-3 h-3" />
                              Unverified
                            </Badge>
                          )}
                        </CardHeader>
                        <CardContent className="p-5 flex-1 flex flex-col">
                          <blockquote className="text-sm font-serif text-foreground/80 italic border-l-2 border-primary/20 pl-4 my-2 leading-relaxed flex-1">
                            "{source.quote}"
                          </blockquote>
                          
                          {source.source_chunk && (
                            <div className="mt-4 pt-4 border-t border-border/50">
                              <p className="text-xs text-muted-foreground font-sans uppercase tracking-widest mb-2 font-semibold">Full Context</p>
                              <div className="text-xs text-muted-foreground leading-relaxed line-clamp-3 hover:line-clamp-none transition-all">
                                {source.source_chunk}
                              </div>
                            </div>
                          )}
                        </CardContent>
                      </Card>
                    ))}
                  </div>
                </div>
              )}
            </motion.div>
          )}
        </AnimatePresence>

      </main>
    </div>
  );
}