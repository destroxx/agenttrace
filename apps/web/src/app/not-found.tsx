import Link from "next/link";

export default function NotFound() {
  return (
    <section className="flex flex-col gap-3">
      <h2 className="text-lg font-semibold">Not found</h2>
      <p className="text-sm text-muted-foreground">
        There is no project or run at this address. It may have been deleted, or the id
        in the URL is incomplete.
      </p>
      <Link href="/" className="text-sm underline underline-offset-4">
        Back to projects
      </Link>
    </section>
  );
}
