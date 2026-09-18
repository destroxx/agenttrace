import { ApiStatus } from "@/components/api-status";
import { fetchHealth } from "@/lib/health";

// The health report reflects live infrastructure, so it must never be baked
// into a prerendered page.
export const dynamic = "force-dynamic";

export default async function Home() {
  const initialResult = await fetchHealth();

  return (
    <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col justify-center gap-8 px-6 py-16">
      <header className="flex flex-col gap-2">
        <h1 className="text-3xl font-semibold tracking-tight">AgentTrace</h1>
        <p className="text-muted-foreground">
          Record-and-replay regression testing for AI agents.
        </p>
      </header>
      <ApiStatus initialResult={initialResult} />
    </main>
  );
}
