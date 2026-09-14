"use client";

import Link from "next/link";

import {
  LeanTable,
  LeanTableCell,
  LeanTableHead,
  LeanTableHeader,
  LeanTableRow,
  Table,
  TableBody,
} from "@/components/lean-table";
import type { PullRequestFile } from "@/lib/api";

export function ChangedFilesTable({
  files,
  hrefForFile,
}: {
  files: PullRequestFile[];
  hrefForFile: (file: PullRequestFile) => string;
}) {
  if (files.length === 0) {
    return null;
  }

  return (
    <LeanTable>
      <Table>
        <LeanTableHeader>
          <LeanTableRow>
            <LeanTableHead>File</LeanTableHead>
            <LeanTableHead>Status</LeanTableHead>
            <LeanTableHead className="text-right">Changes</LeanTableHead>
          </LeanTableRow>
        </LeanTableHeader>
        <TableBody>
          {files.map((file) => (
            <LeanTableRow key={file.id}>
              <LeanTableCell>
                <Link
                  href={hrefForFile(file)}
                  title={file.filename}
                  className="block max-w-[36rem] truncate font-mono text-sm text-[#fafafa] hover:text-[#67e8f9] focus-visible:text-[#67e8f9] focus-visible:ring-2 focus-visible:ring-[#22d3ee]/70 focus-visible:outline-none"
                >
                  {file.filename}
                </Link>
                {file.previous_filename ? (
                  <div className="mt-1 text-xs text-[#71717a]">
                    renamed from {file.previous_filename}
                  </div>
                ) : null}
              </LeanTableCell>
              <LeanTableCell className="capitalize text-[#a1a1aa]">
                {file.status}
              </LeanTableCell>
              <LeanTableCell className="text-right font-mono text-xs tabular-nums">
                <span className="text-[#4ade80]">+{file.additions}</span>{" "}
                <span className="text-[#f87171]">-{file.deletions}</span>
              </LeanTableCell>
            </LeanTableRow>
          ))}
        </TableBody>
      </Table>
    </LeanTable>
  );
}
