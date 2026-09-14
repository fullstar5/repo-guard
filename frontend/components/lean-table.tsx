import type { ReactNode } from "react";

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";

export function LeanTable({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "overflow-hidden rounded-xl border border-[#3f3f46] bg-[#18181b]",
        className,
      )}
    >
      {children}
    </div>
  );
}

export function LeanTableHeader({ children }: { children: ReactNode }) {
  return <TableHeader className="[&_tr]:border-[#27272a]">{children}</TableHeader>;
}

export function LeanTableHead({
  children,
  className,
}: {
  children?: ReactNode;
  className?: string;
}) {
  return (
    <TableHead
      className={cn(
        "h-11 px-4 text-xs font-medium tracking-wide text-[#a1a1aa]",
        className,
      )}
    >
      {children}
    </TableHead>
  );
}

export function LeanTableRow({
  children,
  className,
}: {
  children?: ReactNode;
  className?: string;
}) {
  return (
    <TableRow
      className={cn(
        "border-[#27272a] hover:bg-[#27272a]/60",
        className,
      )}
    >
      {children}
    </TableRow>
  );
}

export function LeanTableCell({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return <TableCell className={cn("px-4 py-3.5", className)}>{children}</TableCell>;
}

export { Table, TableBody };
