type DiffLine = {
  kind: "hunk" | "add" | "del" | "ctx" | "meta";
  text: string;
};

function parsePatch(patch: string): DiffLine[] {
  return patch.replace(/\r\n/g, "\n").split("\n").map((text) => {
    if (text.startsWith("@@")) {
      return { kind: "hunk", text };
    }
    if (text.startsWith("+++") || text.startsWith("---") || text.startsWith("diff ")) {
      return { kind: "meta", text };
    }
    if (text.startsWith("+")) {
      return { kind: "add", text };
    }
    if (text.startsWith("-")) {
      return { kind: "del", text };
    }
    return { kind: "ctx", text };
  });
}

const LINE_CLASS: Record<DiffLine["kind"], string> = {
  hunk: "bg-blue-50 text-blue-800",
  add: "bg-emerald-50 text-emerald-800",
  del: "bg-red-50 text-red-800",
  ctx: "text-zinc-800",
  meta: "text-zinc-500",
};

export function DiffView({ patch }: { patch: string | null }) {
  if (!patch) {
    return (
      <p className="text-sm text-zinc-500">
        No textual diff for this file. It may be binary, empty, or too large for
        GitHub to include a patch.
      </p>
    );
  }

  const lines = parsePatch(patch);

  return (
    <pre className="overflow-x-auto rounded-lg border bg-zinc-50 text-xs leading-6">
      <code>
        {lines.map((line, index) => (
          <div
            key={`${index}-${line.kind}`}
            className={`whitespace-pre px-3 ${LINE_CLASS[line.kind]}`}
          >
            {line.text.length === 0 ? " " : line.text}
          </div>
        ))}
      </code>
    </pre>
  );
}
