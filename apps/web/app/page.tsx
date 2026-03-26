import ConversationSimulator from "@/components/ConversationSimulator";

export default function Home() {
  return (
    <main className="min-h-screen bg-background flex flex-col items-center justify-center py-12 px-4">
      <div className="text-center mb-8 max-w-lg">
        <h1 className="text-2xl font-bold text-foreground tracking-tight mb-2">
          Bright Smile Dental — Maya
        </h1>
        <p className="text-sm text-muted-foreground">
          Missed-call SMS assistant · tap the reply chips or type freely
        </p>
      </div>

      <ConversationSimulator />

      <div className="h-20" />
    </main>
  );
}
