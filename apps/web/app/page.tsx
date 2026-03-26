import { HealthResponseSchema } from "@dental-chatbot/shared-types";

import { Button } from "@/components/ui/button";

export default function Home() {
  const sample = HealthResponseSchema.parse({
    status: "ok",
    service: "web",
    database: "sqlite",
  });

  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col gap-6 px-6 py-16">
      <h1 className="text-3xl font-semibold tracking-tight">Dental Chatbot</h1>
      <p className="text-slate-600">
        Next.js frontend is running. Shared type check:{" "}
        <code className="rounded bg-slate-200 px-1.5 py-0.5 text-sm">{sample.service}</code>
      </p>
      <p className="text-sm text-slate-500">
        API URL (from env):{" "}
        <code className="rounded bg-slate-200 px-1.5 py-0.5">
          {process.env.NEXT_PUBLIC_API_URL ?? "(set NEXT_PUBLIC_API_URL)"}
        </code>
      </p>
      <div>
        <Button type="button" variant="outline" size="sm">
          shadcn/ui button
        </Button>
      </div>
    </main>
  );
}
