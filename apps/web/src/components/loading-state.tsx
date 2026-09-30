import { Panel, RecChip } from "@/components/brand/primitives";

/** What a dashboard page shows while its server fetch is in flight: a recorder's light and an empty panel. */
export function LoadingState({ label }: { label: string }) {
  return (
    <div role="status" className="flex flex-col gap-6">
      <RecChip tone="ink">{label}</RecChip>
      <Panel className="h-40 opacity-60">{null}</Panel>
    </div>
  );
}
